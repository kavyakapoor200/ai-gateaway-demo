"""
Minimal Local AI Gateway: Hardened Zero Data Retention (ZDR) Audit Logger
------------------------------------------------------------------------
Custom LiteLLM callback logger for the Minimal Local AI Gateway PoC.
Features:
1. In-RAM Cryptographic SHA-256 Hashing: 0 bytes of cleartext prompts/completions persisted.
2. Zero-Touch Task Correlation: Deterministic root-prompt hashing (messages[1] -> task_id).
3. In-Flight Branch Sniffing: Detects git branch tool calls/messages, writes bhash:<sha256> -> task_id to Redis.
4. Single-Table SQLite Ledger: Writes operational metadata directly into gateway_audit_ledger (WAL mode).
"""

import os
import sys
import re
import json
import time
import uuid
import hashlib
import sqlite3
import socket
import fnmatch
from typing import Any, Dict, Optional, List, Set, Union

# Gracefully inherit from LiteLLM CustomLogger if installed
try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:
    class CustomLogger:
        """Standalone fallback for offline test and benchmark execution."""
        pass

try:
    from fastapi import HTTPException
except ImportError:
    class HTTPException(Exception):
        """Fallback HTTPException when fastapi is unavailable."""
        def __init__(self, status_code: int, detail: Any = None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(str(detail))

# Neutralize LiteLLM's internal naive auth check (which lacks wildcard/pruning/audit support)
# in favor of ZDRAuditLogger.async_pre_call_hook Ingress PEP.
try:
    import litellm.proxy.auth.auth_checks as litellm_auth_checks
    async def _noop_check_tools_allowlist(request_body: dict, valid_token: Any, team_object: Any, route: str) -> None:
        return None
    litellm_auth_checks.check_tools_allowlist = _noop_check_tools_allowlist
except Exception:
    pass


class ZDRAuditLogger(CustomLogger):
    """
    Hardened ZDR Audit Logger compliant with sqlite_schema.sql (gateway_audit_ledger).
    Calculates SHA-256 digests in memory and records zero plaintext.
    """

    _POLICY_INTERCEPT_CACHE: Dict[str, Dict[str, Any]] = {}
    _RECENT_KEY_INTERCEPT: Dict[str, Dict[str, Any]] = {}

    def __init__(self, db_path: Optional[str] = None, redis_host: Optional[str] = None, redis_port: Optional[int] = None):
        super().__init__()
        # Determine database path
        if db_path:
            self.db_path = db_path
        elif os.environ.get("DB_PATH"):
            self.db_path = os.environ.get("DB_PATH")
        elif os.path.exists("/app/data"):
            self.db_path = "/app/data/gateway.db"
        elif os.path.exists("data"):
            self.db_path = "data/gateway.db"
        elif os.path.exists("/app"):
            self.db_path = "/app/gateway.db"
        else:
            self.db_path = "gateway.db"

        # Ensure directory exists
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        self.redis_host = redis_host or os.environ.get("REDIS_HOST", "localhost")
        self.redis_port = int(redis_port or os.environ.get("REDIS_PORT", 6379))

        # Regex for sniffing Git branch checkout/creation
        self._branch_regex = re.compile(
            r'(?:git\s+checkout\s+(?:-b\s+)?|git\s+switch\s+(?:-c\s+)?|git\s+branch\s+)([a-zA-Z0-9_\-\.\/]+)',
            re.IGNORECASE
        )
        self._ensure_schema()

    def _ensure_schema(self):
        """Ensures gateway_audit_ledger and analytical views exist, with self-healing migrations."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gateway_audit_ledger';")
            if not cur.fetchone():
                candidates = [
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "sqlite_schema.sql"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "sqlite_schema.sql"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "sqlite_schema.sql"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sqlite_schema.sql")
                ]
                schema_path = next((p for p in candidates if os.path.exists(p)), None)
                if schema_path:
                    with open(schema_path, "r") as f:
                        conn.executescript(f.read())
                else:
                    # Embedded self-healing fallback DDL
                    conn.executescript("""
                    CREATE TABLE IF NOT EXISTS gateway_audit_ledger (
                        request_id TEXT PRIMARY KEY,
                        trace_id TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        api_key_alias TEXT NOT NULL,
                        caller_role TEXT NOT NULL DEFAULT 'developer',
                        model_requested TEXT NOT NULL,
                        model_routed TEXT NOT NULL,
                        fallback_triggered INTEGER DEFAULT 0,
                        http_status INTEGER NOT NULL,
                        latency_ms REAL NOT NULL,
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd REAL NOT NULL DEFAULT 0.0,
                        prompt_sha256 TEXT NOT NULL,
                        completion_sha256 TEXT NOT NULL,
                        zdr_verified INTEGER DEFAULT 1,
                        task_id TEXT,
                        task_outcome TEXT DEFAULT 'pending',
                        policy_action TEXT DEFAULT NULL,
                        violating_tools TEXT DEFAULT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_trace_id ON gateway_audit_ledger(trace_id);
                    CREATE INDEX IF NOT EXISTS idx_task_id ON gateway_audit_ledger(task_id);
                    CREATE INDEX IF NOT EXISTS idx_created_at ON gateway_audit_ledger(created_at);
                    CREATE INDEX IF NOT EXISTS idx_policy_action ON gateway_audit_ledger(policy_action);
                    CREATE VIEW IF NOT EXISTS v_coding_cps_summary AS
                    SELECT 
                        task_id,
                        COUNT(request_id) AS total_turns,
                        SUM(prompt_tokens + completion_tokens) AS total_tokens,
                        ROUND(SUM(cost_usd), 6) AS accumulated_cost_usd,
                        task_outcome,
                        CASE 
                            WHEN task_outcome = 'verified_success' THEN ROUND(SUM(cost_usd), 6)
                            ELSE NULL 
                        END AS final_cps_usd
                    FROM gateway_audit_ledger
                    WHERE task_id IS NOT NULL
                    GROUP BY task_id, task_outcome;
                    CREATE VIEW IF NOT EXISTS v_zdr_compliance_check AS
                    SELECT 
                        COUNT(*) AS total_records,
                        SUM(CASE WHEN LENGTH(prompt_sha256) = 64 AND prompt_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END) AS valid_prompt_hashes,
                        SUM(CASE WHEN LENGTH(completion_sha256) = 64 AND completion_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END) AS valid_completion_hashes,
                        SUM(CASE WHEN zdr_verified = 1 THEN 1 ELSE 0 END) AS zdr_flags_valid,
                        CASE 
                            WHEN COUNT(*) = 0 THEN 'NO RECORDS YET'
                            WHEN COUNT(*) = SUM(CASE WHEN LENGTH(prompt_sha256) = 64 AND prompt_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END)
                             AND COUNT(*) = SUM(CASE WHEN LENGTH(completion_sha256) = 64 AND completion_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END)
                            THEN '100% COMPLIANT - ZERO PLAINTEXT DETECTED'
                            ELSE 'VIOLATION DETECTED - AUDIT REQUIRED'
                        END AS compliance_status
                    FROM gateway_audit_ledger;
                    """)
            else:
                # Self-healing migration for existing databases
                cur.execute("PRAGMA table_info(gateway_audit_ledger);")
                existing_cols = {row[1] for row in cur.fetchall()}
                if "policy_action" not in existing_cols:
                    cur.execute("ALTER TABLE gateway_audit_ledger ADD COLUMN policy_action TEXT DEFAULT NULL;")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_policy_action ON gateway_audit_ledger(policy_action);")
                if "violating_tools" not in existing_cols:
                    cur.execute("ALTER TABLE gateway_audit_ledger ADD COLUMN violating_tools TEXT DEFAULT NULL;")
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"[!] ZDRAuditLogger: Schema bootstrap notice: {e}", file=sys.stderr)

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a thread-safe connection configured with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        """Computes deterministic SHA-256 hash in memory. Raw payload is never persisted."""
        if payload is None:
            return hashlib.sha256(b"").hexdigest()
        if isinstance(payload, str):
            p_bytes = payload.encode("utf-8", errors="replace")
        elif isinstance(payload, (bytes, bytearray)):
            p_bytes = bytes(payload)
        else:
            try:
                p_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")
            except Exception:
                p_bytes = str(payload).encode("utf-8", errors="replace")
        return hashlib.sha256(p_bytes).hexdigest()

    @staticmethod
    def derive_task_id_from_pr(branch_or_ref: str) -> str:
        """
        Derives deterministic task_id directly from the cryptographic SHA-256
        hash of the Git branch/PR identity:
        task_id = "task_pr_" + SHA256(branch)[:12]
        """
        if not branch_or_ref:
            return "task_pr_unknown"
        clean_branch = branch_or_ref.strip()
        if clean_branch.startswith("refs/heads/"):
            clean_branch = clean_branch[len("refs/heads/"):]
        bhash = hashlib.sha256(clean_branch.encode("utf-8")).hexdigest()
        return f"task_pr_{bhash[:12]}"

    def _derive_task_id(self, key_alias: str, messages: Optional[List[Dict[str, Any]]], branch_name: Optional[str] = None) -> Optional[str]:
        """
        Derives deterministic task_id via Root-Prompt Tree Invariance formula:
        TaskDigest = SHA-256(KeyAlias + "::" + root_user_prompt[:500])
        task_id = "task_" + TaskDigest[:16]
        
        If branch_name is provided, can also derive task_id directly from the hashed PR identity.
        """
        if branch_name:
            return self.derive_task_id_from_pr(branch_name)

        if not messages or not isinstance(messages, list):
            return None

        # Locate root user prompt (first user message)
        root_content = None
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    root_content = content.strip()
                    break
                elif isinstance(content, list):
                    # Multimodal / structured content
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and "text" in p]
                    root_content = " ".join(text_parts).strip()
                    break

        if not root_content:
            # Fallback to the first message if no explicit user role found
            first_msg = messages[0] if messages else {}
            root_content = str(first_msg.get("content", ""))[:500]

        digest_input = f"{key_alias}::{root_content[:500]}".encode("utf-8", errors="replace")
        task_digest = hashlib.sha256(digest_input).hexdigest()
        return f"task_{task_digest[:16]}"

    def _sniff_and_index_branch(self, messages: Any, tool_calls: Any, task_id: str):
        """
        Sniffs in-flight Git branch names in RAM, computes SHA-256, and stores
        bhash:<sha256> -> task_id in Redis with 7-day TTL.
        Zero cleartext branch names are persisted in Redis.
        """
        if not task_id:
            return

        detected_branch = None

        # 1. Search direct tool_calls parameter
        if tool_calls:
            calls_str = json.dumps(tool_calls) if not isinstance(tool_calls, str) else tool_calls
            match = self._branch_regex.search(calls_str)
            if match:
                detected_branch = match.group(1)

        # 2. Search message history (both content and embedded tool_calls)
        if not detected_branch and isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, dict):
                    # Check msg tool_calls
                    if "tool_calls" in msg and msg["tool_calls"]:
                        tc_str = json.dumps(msg["tool_calls"])
                        m = self._branch_regex.search(tc_str)
                        if m:
                            detected_branch = m.group(1)
                            break
                    # Check serialized message text
                    m_str = json.dumps(msg)
                    m = self._branch_regex.search(m_str)
                    if m:
                        detected_branch = m.group(1)
                        break

        if detected_branch:
            # Strip trailing quotes or semicolons or braces
            detected_branch = detected_branch.strip("'\";,)} \n\r\t")
            bhash = hashlib.sha256(detected_branch.encode("utf-8")).hexdigest()
            self._write_redis_bhash(bhash, task_id)

    def _write_redis_bhash(self, bhash: str, task_id: str, ttl_seconds: int = 604800):
        """Stores bhash:<sha256> -> task_id in Redis via direct TCP socket protocol."""
        key = f"bhash:{bhash}"
        # RESP command: SET key value EX ttl
        cmd = f"*5\r\n$3\r\nSET\r\n${len(key)}\r\n{key}\r\n${len(task_id)}\r\n{task_id}\r\n$2\r\nEX\r\n${len(str(ttl_seconds))}\r\n{ttl_seconds}\r\n".encode("utf-8")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((self.redis_host, self.redis_port))
            s.sendall(cmd)
            resp = s.recv(1024).decode("utf-8", errors="ignore")
            s.close()
            if "+OK" in resp:
                # Successfully indexed in Redis
                pass
        except Exception as e:
            # Graceful degraded operation: logging continues even if Redis is unreachable
            print(f"[!] ZDRAuditLogger: Redis bhash index notice: {e}", file=sys.stderr)

    def _calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Computes micro-cent costs based on local baseline rate card."""
        m = (model or "").lower().replace(".", "-")
        if "mock" in m:
            p_cost, c_cost = (0.00, 0.00)
        elif "gpt-4o-mini" in m:
            p_cost, c_cost = (0.15, 0.60)
        elif "gpt-4o" in m:
            p_cost, c_cost = (2.50, 10.00)
        elif "claude-3-5-sonnet" in m or "sonnet" in m:
            p_cost, c_cost = (3.00, 15.00)
        else:
            p_cost, c_cost = (2.50, 10.00)

        cost = ((prompt_tokens / 1_000_000.0) * p_cost) + ((completion_tokens / 1_000_000.0) * c_cost)
        return round(cost, 6)


    def log_success_event(self, kwargs: Dict[str, Any], response_obj: Any, start_time: Any, end_time: Any) -> bool:
        """Logs successful request metadata into gateway_audit_ledger."""
        try:
            litellm_params = kwargs.get("litellm_params", {})
            model_req = kwargs.get("model") or "gpt-4o"
            model_routed = litellm_params.get("model") or model_req
            fallback_triggered = 1 if model_req != model_routed else 0

            meta = {**kwargs.get("metadata", {}), **litellm_params.get("metadata", {}), **kwargs.get("litellm_metadata", {})}
            key_alias = meta.get("_zdr_key_alias") or meta.get("user_api_key_alias") or meta.get("key_alias") or kwargs.get("user") or "sk-agent-developer"
            caller_role = meta.get("role") or meta.get("user_role") or "developer"
            # Extract active OpenTelemetry trace ID or fallback
            trace_id = None
            try:
                from opentelemetry import trace
                span = trace.get_current_span()
                if span and span.get_span_context().is_valid:
                    trace_id = format(span.get_span_context().trace_id, "032x")
            except Exception:
                pass
            if not trace_id:
                raw_tid = kwargs.get("litellm_trace_id") or meta.get("litellm_trace_id") or meta.get("trace_id")
                if raw_tid:
                    cleaned = str(raw_tid).replace("-", "").lower()
                    trace_id = cleaned[:32].zfill(32)
                else:
                    trace_id = uuid.uuid4().hex

            # 1. Ephemeral cryptographic hash of input prompt
            messages = kwargs.get("messages")
            prompt_sha256 = meta.get("_zdr_prompt_sha256") or self._hash_payload(messages)

            # 2. Ephemeral cryptographic hash of model output (and extract tool_calls for branch sniffing)
            content = ""
            tool_calls = None
            if response_obj and hasattr(response_obj, "choices") and response_obj.choices:
                choice = response_obj.choices[0]
                msg = getattr(choice, "message", None) or getattr(choice, "delta", None)
                if msg:
                    content = getattr(msg, "content", "") or ""
                    tool_calls = getattr(msg, "tool_calls", None)
            elif isinstance(response_obj, dict):
                choices = response_obj.get("choices", [])
                if choices:
                    msg = choices[0].get("message") or choices[0].get("delta") or {}
                    content = msg.get("content") or ""
                    tool_calls = msg.get("tool_calls")
            
            completion_payload = content if not tool_calls else {"content": content, "tool_calls": tool_calls}
            completion_sha256 = self._hash_payload(completion_payload)

            # 3. Token usage extraction
            prompt_tokens, completion_tokens = 0, 0
            if response_obj and hasattr(response_obj, "usage") and response_obj.usage:
                u = response_obj.usage
                prompt_tokens = getattr(u, "prompt_tokens", 0) or 0
                completion_tokens = getattr(u, "completion_tokens", 0) or 0
            elif isinstance(response_obj, dict) and "usage" in response_obj:
                u = response_obj["usage"]
                prompt_tokens = u.get("prompt_tokens", 0) or 0
                completion_tokens = u.get("completion_tokens", 0) or 0

            # Use LiteLLM reported cost if available, otherwise calculate
            reported_cost = kwargs.get("response_cost")
            if reported_cost is not None and reported_cost > 0:
                cost_usd = round(float(reported_cost), 6)
            else:
                cost_usd = self._calculate_cost(model_routed, prompt_tokens, completion_tokens)

            # 4. Latency calculation
            if hasattr(start_time, "timestamp") and hasattr(end_time, "timestamp"):
                latency_ms = round((end_time.timestamp() - start_time.timestamp()) * 1000.0, 2)
            else:
                latency_ms = round((float(end_time) - float(start_time)) * 1000.0, 2)

            req_id = (
                getattr(response_obj, "id", None)
                or (response_obj.get("id") if isinstance(response_obj, dict) else None)
                or f"req-{uuid.uuid4().hex[:12]}"
            )

            # 5. Zero-Touch Task ID Derivation & Branch Sniffing
            task_id = meta.get("_zdr_task_id") or self._derive_task_id(key_alias, messages)
            self._sniff_and_index_branch(messages, tool_calls, task_id)

            policy_action = meta.get("_zdr_policy_action")
            violating_tools = meta.get("_zdr_violating_tools")

            # Fallback for Anthropic /v1/messages endpoints where LiteLLM does not propagate data["metadata"]
            if not policy_action:
                cached_entry = ZDRAuditLogger._POLICY_INTERCEPT_CACHE.pop(prompt_sha256, None)
                if not cached_entry and key_alias in ZDRAuditLogger._RECENT_KEY_INTERCEPT:
                    recent = ZDRAuditLogger._RECENT_KEY_INTERCEPT[key_alias]
                    if time.time() - recent.get("time", 0) < 120:
                        cached_entry = recent
                if cached_entry:
                    policy_action = cached_entry.get("policy_action")
                    violating_tools = cached_entry.get("violating_tools")
                    if caller_role == "developer" and cached_entry.get("role"):
                        caller_role = cached_entry.get("role")

            if caller_role == "developer" and "intern" in key_alias.lower():
                caller_role = "intern"

            # 6. Insert metadata into SQLite gateway_audit_ledger
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO gateway_audit_ledger (
                    request_id, trace_id, api_key_alias, caller_role,
                    model_requested, model_routed, fallback_triggered,
                    http_status, latency_ms, prompt_tokens, completion_tokens,
                    cost_usd, prompt_sha256, completion_sha256, zdr_verified,
                    task_id, task_outcome, policy_action, violating_tools
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'pending', ?, ?)
            """, (
                req_id, trace_id, key_alias, caller_role,
                model_req, model_routed, fallback_triggered,
                200, latency_ms, prompt_tokens, completion_tokens,
                cost_usd, prompt_sha256, completion_sha256,
                task_id, policy_action, violating_tools
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[!] ZDRAuditLogger Error in log_success_event: {e}", file=sys.stderr)
            return False

    def log_failure_event(self, kwargs: Dict[str, Any], response_obj: Any, start_time: Any, end_time: Any, error: Optional[str] = None, http_status: Optional[int] = None) -> bool:
        """Logs failed/rejected request metadata into gateway_audit_ledger."""
        try:
            litellm_params = kwargs.get("litellm_params", {})
            model_req = kwargs.get("model") or "unknown"
            model_routed = litellm_params.get("model") or model_req

            meta = {**kwargs.get("metadata", {}), **litellm_params.get("metadata", {}), **kwargs.get("litellm_metadata", {})}
            key_alias = meta.get("_zdr_key_alias") or meta.get("user_api_key_alias") or meta.get("key_alias") or kwargs.get("user") or "unknown"
            caller_role = meta.get("role") or meta.get("user_role") or "developer"
            # Extract active OpenTelemetry trace ID or fallback
            trace_id = None
            try:
                from opentelemetry import trace
                span = trace.get_current_span()
                if span and span.get_span_context().is_valid:
                    trace_id = format(span.get_span_context().trace_id, "032x")
            except Exception:
                pass
            if not trace_id:
                raw_tid = kwargs.get("litellm_trace_id") or meta.get("litellm_trace_id") or meta.get("trace_id")
                if raw_tid:
                    cleaned = str(raw_tid).replace("-", "").lower()
                    trace_id = cleaned[:32].zfill(32)
                else:
                    trace_id = uuid.uuid4().hex

            messages = kwargs.get("messages")
            prompt_sha256 = meta.get("_zdr_prompt_sha256") or self._hash_payload(messages)
            completion_sha256 = self._hash_payload("")
            task_id = meta.get("_zdr_task_id") or self._derive_task_id(key_alias, messages)

            status = http_status
            if status is None:
                if isinstance(response_obj, Exception):
                    status = getattr(response_obj, "status_code", None) or getattr(response_obj, "http_status", None)
                elif isinstance(response_obj, dict):
                    status = response_obj.get("status_code")

            task_outcome = "failed"
            err_str = f"{error or ''} {response_obj or ''} {kwargs.get('exception', '')}"
            policy_action = meta.get("_zdr_policy_action")
            violating_tools = meta.get("_zdr_violating_tools")

            if "tool_not_allowed" in err_str or "Tool execution policy violation" in err_str:
                status = 403
                task_outcome = "tool_policy_rejected"
                policy_action = "strict_reject"
                # Extract violating tools & role from response_obj or exception detail
                v_list = None
                exc = kwargs.get("exception") or error
                for candidate in (response_obj, exc):
                    if hasattr(candidate, "detail") and isinstance(candidate.detail, dict):
                        err_info = candidate.detail.get("error", {})
                        v_list = err_info.get("violating_tools")
                        if err_info.get("role"):
                            caller_role = err_info["role"]
                        break
                    elif isinstance(candidate, dict):
                        err_info = candidate.get("error", {})
                        v_list = err_info.get("violating_tools")
                        if err_info.get("role"):
                            caller_role = err_info["role"]
                        break

                if not v_list:
                    import re, ast
                    match = re.search(r"permitted\s+(?:for\s+this\s+API\s+key|for\s+role\s+[^:]+):\s*(\[[^\]]+\])", err_str)
                    if match:
                        try:
                            v_list = ast.literal_eval(match.group(1))
                        except Exception:
                            pass

                if v_list:
                    violating_tools = json.dumps(sorted(v_list)) if isinstance(v_list, (list, set, tuple)) else str(v_list)
            elif status is None:
                status = 500

            if hasattr(start_time, "timestamp") and hasattr(end_time, "timestamp"):
                latency_ms = round((end_time.timestamp() - start_time.timestamp()) * 1000.0, 2)
            else:
                latency_ms = round((float(end_time) - float(start_time)) * 1000.0, 2)

            req_id = f"req-{uuid.uuid4().hex[:12]}"
            task_id = self._derive_task_id(key_alias, messages)

            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO gateway_audit_ledger (
                    request_id, trace_id, api_key_alias, caller_role,
                    model_requested, model_routed, fallback_triggered,
                    http_status, latency_ms, prompt_tokens, completion_tokens,
                    cost_usd, prompt_sha256, completion_sha256, zdr_verified,
                    task_id, task_outcome, policy_action, violating_tools
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 0, 0, 0.0, ?, ?, 1, ?, ?, ?, ?)
            """, (
                req_id, trace_id, key_alias, caller_role,
                model_req, model_routed, status, latency_ms,
                prompt_sha256, completion_sha256, task_id, task_outcome,
                policy_action, violating_tools
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[!] ZDRAuditLogger Error in log_failure_event: {e}", file=sys.stderr)
            return False

    async def async_log_success_event(self, kwargs: Dict[str, Any], response_obj: Any, start_time: Any, end_time: Any):
        """Asynchronous hook for LiteLLM async pipelines."""
        return self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(self, kwargs: Dict[str, Any], response_obj: Any, start_time: Any, end_time: Any):
        """Asynchronous hook for LiteLLM async failure pipelines."""
        return self.log_failure_event(kwargs, response_obj, start_time, end_time)

    @staticmethod
    def _read_prop(target: Any, prop: str, default: Any = None) -> Any:
        if target is None:
            return default
        if isinstance(target, dict):
            return target.get(prop, default)
        return getattr(target, prop, default)

    @classmethod
    def _extract_tool_names(cls, data: Dict[str, Any]) -> List[str]:
        tool_names = []
        if not data or not isinstance(data, dict):
            return tool_names
        
        # 1. Anthropic & OpenAI standard 'tools' parameter
        raw_tools = data.get("tools")
        if isinstance(raw_tools, list):
            for t in raw_tools:
                if isinstance(t, dict):
                    # Anthropic schema: {"name": "..."}
                    if "name" in t and isinstance(t["name"], str):
                        tool_names.append(t["name"])
                    # OpenAI schema: {"type": "function", "function": {"name": "..."}}
                    elif "function" in t and isinstance(t["function"], dict):
                        fn_name = t["function"].get("name")
                        if fn_name and isinstance(fn_name, str):
                            tool_names.append(fn_name)
                    elif "type" in t and isinstance(t["type"], str) and t["type"] != "function":
                        tool_names.append(t["type"])
        
        # 2. Legacy OpenAI 'functions' parameter
        raw_functions = data.get("functions")
        if isinstance(raw_functions, list):
            for f in raw_functions:
                if isinstance(f, dict):
                    fn_name = f.get("name")
                    if fn_name and isinstance(fn_name, str):
                        tool_names.append(fn_name)
                        
        return tool_names

    @classmethod
    def _get_whitelisted_tools(cls, user_api_key_dict: Any) -> Optional[Set[str]]:
        """
        Extracts whitelisted tools from user_api_key_dict:
        Returns:
          - None if no tool restrictions apply (or '*' is present)
          - Set[str] of permitted tool names/patterns if a whitelist is enforced
        """
        if not user_api_key_dict:
            return None

        # 1. Resolve role (inspect direct property and metadata)
        meta = cls._read_prop(user_api_key_dict, "metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}

        user_role = (
            meta.get("role")
            or cls._read_prop(user_api_key_dict, "user_role")
            or cls._read_prop(user_api_key_dict, "role")
        )
        if user_role in ("proxy_admin", "admin"):
            return None

        # 2. Inspect key metadata for explicit allowed_tools
        meta_allowed = meta.get("allowed_tools")
        if meta_allowed is not None:
            if isinstance(meta_allowed, list):
                if "*" in meta_allowed:
                    return None
                return set(meta_allowed)
            elif isinstance(meta_allowed, str):
                if meta_allowed == "*":
                    return None
                return {meta_allowed}

        # 3. Inspect key permissions
        perms = cls._read_prop(user_api_key_dict, "permissions") or {}
        if isinstance(perms, str):
            try:
                perms = json.loads(perms)
            except Exception:
                perms = {}
        if isinstance(perms, dict):
            perms_allowed = perms.get("allowed_tools") or perms.get("mcp_tools")
            if perms_allowed is not None:
                if isinstance(perms_allowed, list):
                    if "*" in perms_allowed:
                        return None
                    return set(perms_allowed)

        # 4. Check object_permission (from Postgres LiteLLM_ObjectPermissionTable / LiteLLM UI)
        # Developers bypass object_permission restrictions unless an explicit whitelist was set in metadata
        if user_role != "developer":
            obj_perm = cls._read_prop(user_api_key_dict, "object_permission")
            if not obj_perm and user_api_key_dict:
                obj_perm_id = cls._read_prop(user_api_key_dict, "object_permission_id")
                if obj_perm_id:
                    db_url = os.environ.get("DATABASE_URL")
                    if db_url and "postgres" in db_url:
                        try:
                            import psycopg2
                            conn = psycopg2.connect(db_url)
                            with conn.cursor() as cur:
                                cur.execute('SELECT mcp_tool_permissions, blocked_tools FROM "LiteLLM_ObjectPermissionTable" WHERE object_permission_id = %s;', (obj_perm_id,))
                                row = cur.fetchone()
                                if row:
                                    obj_perm = {"mcp_tool_permissions": row[0], "blocked_tools": row[1]}
                            conn.close()
                        except Exception:
                            pass

            if obj_perm:
                allowed = set()
                mcp_tool_perms = cls._read_prop(obj_perm, "mcp_tool_permissions")
                if isinstance(mcp_tool_perms, str):
                    try:
                        mcp_tool_perms = json.loads(mcp_tool_perms)
                    except Exception:
                        mcp_tool_perms = {}
                if isinstance(mcp_tool_perms, dict) and mcp_tool_perms:
                    for srv_id, tools in mcp_tool_perms.items():
                        if isinstance(tools, (list, set, tuple)):
                            allowed.update(tools)
                    if allowed:
                        return allowed

        # 5. REQ-MCP-07 Default Role Policy:
        # Developer = *, Intern = ["read_file", "git_status", "git_diff"]
        if user_role == "developer":
            return None
        elif user_role == "intern":
            return {"read_file", "git_status", "git_diff"}

        return None

    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,
        cache: Any,
        data: Dict[str, Any],
        call_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Gateway Ingress Policy Enforcement Point & ZDR Sanitizer:
        1. (SUB-POC-04) Intercepts incoming requests and verifies declared tools against key's whitelist.
           - tool_policy="strict_reject": Aborts with HTTP 403: tool_not_allowed on violation.
           - tool_policy="filter" (default): Prunes disallowed tools so LLM cannot call them,
             allowing coding agents to initialize and function without session crashes.
        2. Scrubs sensitive secrets (AWS keys, API keys, email addresses) into [REDACTED].
        3. Sniffs in-flight Git branch operations and registers ephemeral bhash in Redis.
        """
        try:
            # 1. Gate: MCP Tool Ingress PEP Whitelist Verification & Virtual Tool Pruning
            tools_requested = self._extract_tool_names(data)
            if tools_requested:
                whitelisted_tools = self._get_whitelisted_tools(user_api_key_dict)
                if whitelisted_tools is not None:
                    # Check for blocked tools on object_permission if present
                    obj_perm = self._read_prop(user_api_key_dict, "object_permission")
                    blocked_tools = set()
                    if obj_perm:
                        b_list = self._read_prop(obj_perm, "blocked_tools") or []
                        if isinstance(b_list, (list, set, tuple)):
                            blocked_tools.update(b_list)

                    violating_tools = []
                    for tool in tools_requested:
                        if tool in blocked_tools:
                            violating_tools.append(tool)
                            continue
                        # Match against whitelist (exact or wildcard)
                        matched = any(tool == pat or fnmatch.fnmatch(tool, pat) for pat in whitelisted_tools)
                        if not matched:
                            violating_tools.append(tool)

                    if violating_tools:
                        key_alias = (
                            self._read_prop(user_api_key_dict, "key_alias")
                            or self._read_prop(user_api_key_dict, "key_name")
                            or "unknown_key"
                        )
                        meta = self._read_prop(user_api_key_dict, "metadata") or {}
                        if isinstance(meta, str):
                            try:
                                meta = json.loads(meta)
                            except Exception:
                                meta = {}
                        if not isinstance(meta, dict):
                            meta = {}

                        tool_policy = meta.get("tool_policy", "filter")
                        caller_role = meta.get("role") or self._read_prop(user_api_key_dict, "role") or "developer"
                        data.setdefault("metadata", {})["role"] = caller_role

                        if tool_policy in ("strict_reject", "strict_whitelist"):
                            msg = (
                                f"Tool execution policy violation: The following requested tool(s) "
                                f"are not permitted for this API key: {sorted(violating_tools)}. "
                                f"Allowed tools: {sorted(whitelisted_tools)}."
                            )
                            print(f"[!] MCP Ingress PEP Intercept: key='{key_alias}', violating={sorted(violating_tools)}", file=sys.stderr)
                            raise HTTPException(
                                status_code=403,
                                detail={
                                    "error": {
                                        "message": msg,
                                        "type": "permission_error",
                                        "param": "tools",
                                        "code": "tool_not_allowed",
                                        "violating_tools": sorted(violating_tools),
                                        "allowed_tools": sorted(whitelisted_tools),
                                        "key_alias": key_alias,
                                        "role": caller_role,
                                        "policy_action": "strict_reject",
                                    }
                                },
                            )
                        else:
                            # Tool Pruning / Virtual Tool Shielding mode (Default for coding agent compatibility)
                            # Strip unallowed tools so LLM never sees them, preventing illegal execution
                            # while keeping the agent session healthy and functional (HTTP 200 OK).
                            data.setdefault("metadata", {})["_zdr_policy_action"] = "filter"
                            data["metadata"]["_zdr_violating_tools"] = json.dumps(sorted(violating_tools))
                            data.setdefault("litellm_metadata", {})["_zdr_policy_action"] = "filter"
                            data["litellm_metadata"]["_zdr_violating_tools"] = json.dumps(sorted(violating_tools))

                            # Ephemeral cache bridge for Anthropic /v1/messages logging
                            p_sha = self._hash_payload(data.get("messages"))
                            cache_entry = {
                                "policy_action": "filter",
                                "violating_tools": json.dumps(sorted(violating_tools)),
                                "role": caller_role,
                                "key_alias": key_alias,
                                "time": time.time(),
                            }
                            ZDRAuditLogger._POLICY_INTERCEPT_CACHE[p_sha] = cache_entry
                            ZDRAuditLogger._RECENT_KEY_INTERCEPT[key_alias] = cache_entry
                            violating_set = set(violating_tools)

                            # 1. Prune standard 'tools' parameter
                            raw_tools = data.get("tools")
                            if isinstance(raw_tools, list):
                                pruned_tools = []
                                for t in raw_tools:
                                    if isinstance(t, dict):
                                        t_name = t.get("name")
                                        if not t_name and "function" in t and isinstance(t["function"], dict):
                                            t_name = t["function"].get("name")
                                        if not t_name and "type" in t and t["type"] != "function":
                                            t_name = t["type"]
                                        if t_name and t_name in violating_set:
                                            continue
                                    pruned_tools.append(t)
                                if pruned_tools:
                                    data["tools"] = pruned_tools
                                else:
                                    data.pop("tools", None)

                            # 2. Prune legacy 'functions' parameter
                            raw_functions = data.get("functions")
                            if isinstance(raw_functions, list):
                                pruned_funcs = [
                                    f for f in raw_functions
                                    if not (isinstance(f, dict) and f.get("name") in violating_set)
                                ]
                                if pruned_funcs:
                                    data["functions"] = pruned_funcs
                                else:
                                    data.pop("functions", None)

                            # 3. Clean up tool_choice if pointing to a pruned tool
                            tool_choice = data.get("tool_choice")
                            if isinstance(tool_choice, dict):
                                tc_name = tool_choice.get("name") or tool_choice.get("function", {}).get("name")
                                if tc_name in violating_set:
                                    data.pop("tool_choice", None)

                            print(
                                f"[i] MCP Ingress PEP Pruned: key='{key_alias}', "
                                f"pruned={sorted(violating_tools)}, "
                                f"remaining_tools={len(data.get('tools') or [])}",
                                file=sys.stderr
                            )

            # 2. Gate: Ingress Secret Redaction, Prompt Hashing & In-Flight Branch Sniffing
            messages = data.get("messages")
            if messages and isinstance(messages, list):
                for msg in messages:
                    if isinstance(msg, dict) and "content" in msg and isinstance(msg["content"], str):
                        content = msg["content"]
                        # AWS Secret Key
                        content = re.sub(r'(?i)AKIA[0-9A-Z]{16}', '[REDACTED]', content)
                        # API Secret Keys (exclude proxy user bearer keys if not a secret)
                        content = re.sub(r'sk-(?!agent-)[a-zA-Z0-9_\-]{20,}', '[REDACTED]', content)
                        # Email Addresses
                        content = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED]', content)
                        msg["content"] = content

                key_alias = None
                if user_api_key_dict:
                    if isinstance(user_api_key_dict, dict):
                        key_alias = user_api_key_dict.get("key_alias") or user_api_key_dict.get("key_name") or user_api_key_dict.get("api_key")
                    else:
                        key_alias = getattr(user_api_key_dict, "key_alias", None) or getattr(user_api_key_dict, "key_name", None)
                if not key_alias:
                    key_alias = data.get("metadata", {}).get("user_api_key_alias") or data.get("user") or "sk-agent-developer"

                prompt_sha256 = self._hash_payload(messages)
                task_id = self._derive_task_id(key_alias, messages)

                meta = data.setdefault("metadata", {})
                meta["_zdr_prompt_sha256"] = prompt_sha256
                meta["_zdr_task_id"] = task_id
                meta["_zdr_key_alias"] = key_alias

                tool_calls = data.get("tools") or data.get("tool_calls")
                self._sniff_and_index_branch(messages, tool_calls, task_id)
        except HTTPException:
            raise
        except Exception as e:
            print(f"[!] ZDRAuditLogger: Notice in async_pre_call_hook: {e}", file=sys.stderr)

        return data


# Export singleton instances for LiteLLM Proxy dynamic loading
zdr_logger = ZDRAuditLogger()
zdr_audit_logger = zdr_logger
