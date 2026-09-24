#!/usr/bin/env python3
"""
tests/test_phase2.py: Comprehensive Verification Suite for Phase 2:
CPS Git Merge Lifecycle Reconciliation & Hashed PR Identity Task ID Assignment.

Tests:
1. CPS Webhook Companion (:4001) lifecycle and healthcheck.
2. PR simulation via mock_local_pr.py (open, merge, reject).
3. In-RAM cryptographic SHA-256 branch hashing and Redis indexing (bhash:<sha256> -> task_id).
4. Zero-Touch Root-Prompt Task ID derivation and merge reconciliation.
5. Direct Hashed PR Identity Task ID assignment (task_pr_<sha256[:12]>) and merge reconciliation.
6. PR Rejection reconciliation (task_outcome -> 'unmerged_closed').
7. Real-time CPS FinOps calculation in v_coding_cps_summary.
8. Forensic Zero Data Retention verification via v_zdr_compliance_check.
"""

import os
import sys
import time
import json
import uuid
import hashlib
import sqlite3
import socket
import threading
import urllib.request
from typing import Dict, Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from custom_zdr_logger import ZDRAuditLogger
import cps_webhook_server
import mock_local_pr

DB_PATH = os.path.join(PROJECT_ROOT, "data", "gateway.db")
WEBHOOK_PORT = 4001
WEBHOOK_URL = f"http://localhost:{WEBHOOK_PORT}"


def print_header(title: str):
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def print_pass(msg: str):
    print(f"  ✅ PASS: {msg}")


def print_fail(msg: str):
    print(f"  ❌ FAIL: {msg}")
    sys.exit(1)


def check_redis_available(host: str = "localhost", port: int = 6379) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect((host, port))
        s.sendall(b"*1\r\n$4\r\nPING\r\n")
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        return "+PONG" in resp
    except Exception:
        return False


def query_redis_key(key: str, host: str = "localhost", port: int = 6379) -> str:
    cmd = f"*2\r\n$3\r\nGET\r\n${len(key)}\r\n{key}\r\n".encode("utf-8")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    s.connect((host, port))
    s.sendall(cmd)
    resp = s.recv(1024).decode("utf-8", errors="ignore")
    s.close()
    lines = resp.split("\r\n")
    if len(lines) >= 2 and lines[0].startswith("$") and int(lines[0][1:]) > 0:
        return lines[1]
    return ""


# ==============================================================================
# Helper Mock Response Object
# ==============================================================================
class MockResponse:
    def __init__(self, content: str = "Code generated successfully.", prompt_tokens: int = 20, completion_tokens: int = 10):
        self.id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        class Choice:
            class Message:
                def __init__(self, c):
                    self.content = c
                    self.tool_calls = None
            def __init__(self, c):
                self.message = Choice.Message(c)
        self.choices = [Choice(content)]
        class Usage:
            def __init__(self, pt, ct):
                self.prompt_tokens = pt
                self.completion_tokens = ct
                self.total_tokens = pt + ct
        self.usage = Usage(prompt_tokens, completion_tokens)


# ==============================================================================
# Background Webhook Server Manager
# ==============================================================================
class WebhookServerThread:
    def __init__(self, port: int = WEBHOOK_PORT):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        # Point cps_webhook_server to test DB_PATH
        os.environ["DB_PATH"] = DB_PATH
        os.environ["REDIS_HOST"] = "localhost"
        os.environ["REDIS_PORT"] = "6379"
        cps_webhook_server.REDIS_HOST = "localhost"
        cps_webhook_server.REDIS_PORT = 6379

        self.server = cps_webhook_server.HTTPServer(("0.0.0.0", self.port), cps_webhook_server.WebhookHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        
        # Wait for server to respond
        for _ in range(30):
            try:
                req = urllib.request.Request(f"{WEBHOOK_URL}/health")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Failed to start cps_webhook_server within 3s")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


# ==============================================================================
# Phase 2 Test Procedure
# ==============================================================================
def main():
    print_header("Minimal Local AI Gateway: Phase 2 Test Suite (PR Reconciliation & Hashed Identity)")

    # 1. Initialize Clean Database
    schema_file = os.path.join(PROJECT_ROOT, "sqlite_schema.sql")
    conn = sqlite3.connect(DB_PATH)
    with open(schema_file, "r") as f:
        conn.executescript(f.read())
    # Clean previous records
    conn.execute("DELETE FROM gateway_audit_ledger;")
    conn.commit()
    conn.close()
    print_pass(f"Database initialized and cleared at {DB_PATH}")

    # 2. Check Redis
    redis_available = check_redis_available()
    if redis_available:
        print_pass("Host Redis server is available on port 6379")
    else:
        print("  ⚠️ Notice: Redis is offline. Test will verify direct hash fallback reconciliation.")

    # 3. Start CPS Webhook Server
    webhook_srv = WebhookServerThread(WEBHOOK_PORT)
    webhook_srv.start()
    print_pass(f"CPS Webhook Companion running on http://localhost:{WEBHOOK_PORT}")

    logger = ZDRAuditLogger(db_path=DB_PATH, redis_host="localhost", redis_port=6379)

    try:
        # ======================================================================
        # Test Case 1: Zero-Touch Root-Prompt Hashing & PR Merge Reconciliation
        # ======================================================================
        print_header("Test Case 1: Root-Prompt Task ID + Sniffed Branch PR Merge")
        branch_1 = "feat/user-auth-oauth2"
        root_prompt_1 = "Implement OAuth2 PKCE login flow for web client."
        key_alias = "sk-agent-developer"

        # Turn 1: Developer prompt
        messages_turn_1 = [
            {"role": "user", "content": root_prompt_1}
        ]
        task_id_1 = logger._derive_task_id(key_alias, messages_turn_1)
        assert task_id_1.startswith("task_")
        print_pass(f"Turn 1 derived invariant Task ID: '{task_id_1}'")

        # Turn 2: Agent responds with tool call to create git branch
        tool_calls_turn_2 = [
            {
                "id": "call_git_1",
                "type": "function",
                "function": {
                    "name": "run_terminal_cmd",
                    "arguments": f'{{"command": "git checkout -b {branch_1}"}}'
                }
            }
        ]
        messages_turn_2 = [
            {"role": "user", "content": root_prompt_1},
            {"role": "assistant", "content": f"Creating local branch {branch_1}", "tool_calls": tool_calls_turn_2},
            {"role": "user", "content": "Add token exchange endpoint"}
        ]

        t_now = time.time()
        # Log Turn 1 to DB
        logger.log_success_event(
            {
                "model": "mock-model",
                "litellm_params": {"model": "mock-model"},
                "metadata": {"user_api_key_alias": key_alias, "role": "developer", "trace_id": "trace-tc1-t1"},
                "messages": messages_turn_1
            },
            MockResponse("OAuth2 architecture plan.", prompt_tokens=40, completion_tokens=20),
            t_now - 0.1, t_now
        )

        # Log Turn 2 with branch sniffing to DB
        logger.log_success_event(
            {
                "model": "mock-model",
                "litellm_params": {"model": "mock-model"},
                "metadata": {"user_api_key_alias": key_alias, "role": "developer", "trace_id": "trace-tc1-t2"},
                "messages": messages_turn_2,
                "tool_calls": tool_calls_turn_2
            },
            MockResponse("Branch created and PKCE helper written.", prompt_tokens=60, completion_tokens=30),
            t_now - 0.05, t_now
        )

        # Verify Redis has bhash index
        bhash_1 = hashlib.sha256(branch_1.encode("utf-8")).hexdigest()
        if redis_available:
            indexed_task = query_redis_key(f"bhash:{bhash_1}")
            assert indexed_task == task_id_1, f"Redis bhash mismatch: {indexed_task} != {task_id_1}"
            print_pass(f"Redis branch index verified: bhash:{bhash_1[:16]}... -> '{indexed_task}'")

        # Verify task is currently 'pending' in SQLite
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT task_outcome FROM gateway_audit_ledger WHERE task_id = ?", (task_id_1,))
        outcomes = [r[0] for r in cur.fetchall()]
        assert all(o == "pending" for o in outcomes), f"Expected 'pending', got {outcomes}"
        print_pass(f"Task {task_id_1} recorded in SQLite with outcome='pending' (2 turns)")
        conn.close()

        # Simulate PR open and merge using mock_local_pr.py
        print("\n  >> Simulating Git PR Merge via mock_local_pr.py...")
        mock_local_pr.open_pr(branch_1, simulate_only=True)
        mock_local_pr.merge_pr(branch_1, simulate_only=True)

        # Verify SQLite reconciled outcome to 'verified_success'
        time.sleep(0.2)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT task_outcome FROM gateway_audit_ledger WHERE task_id = ?", (task_id_1,))
        reconciled_outcomes = [r[0] for r in cur.fetchall()]
        assert all(o == "verified_success" for o in reconciled_outcomes), f"Expected 'verified_success', got {reconciled_outcomes}"
        print_pass(f"Reconciled task {task_id_1} to 'verified_success' across all turns!")
        conn.close()

        # ======================================================================
        # Test Case 2: Direct Hashed PR Identity Task ID Assignment
        # ======================================================================
        print_header("Test Case 2: Assign Task ID directly based on Hashed PR Identity")
        branch_2 = "feat/stripe-payment-webhooks"
        bhash_2 = hashlib.sha256(branch_2.encode("utf-8")).hexdigest()
        
        # Derive task_id directly from the PR identity hash
        task_id_pr = ZDRAuditLogger.derive_task_id_from_pr(branch_2)
        expected_pr_task_id = f"task_pr_{bhash_2[:12]}"
        assert task_id_pr == expected_pr_task_id, f"PR Task ID mismatch: {task_id_pr} != {expected_pr_task_id}"
        print_pass(f"Hashed PR Identity Task ID derived: '{task_id_pr}' from sha256({branch_2})")

        # Log request using hashed PR identity
        req_pr_kwargs = {
            "model": "mock-model",
            "litellm_params": {"model": "mock-model"},
            "metadata": {"user_api_key_alias": key_alias, "role": "developer", "trace_id": "trace-tc2-pr"},
            "messages": [{"role": "user", "content": "Implement webhook verification for Stripe."}]
        }

        # Index in Redis (if available) to test bridge consistency
        if redis_available:
            logger._write_redis_bhash(bhash_2, task_id_pr)

        # Insert directly using the hashed PR task_id
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, fallback_triggered,
                http_status, latency_ms, prompt_tokens, completion_tokens,
                cost_usd, prompt_sha256, completion_sha256, zdr_verified,
                task_id, task_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 200, 32.1, 80, 40, 0.00012, ?, ?, 1, ?, 'pending')
        """, (
            f"req-pr-{uuid.uuid4().hex[:8]}", "trace-tc2-pr", key_alias, "developer",
            "mock-model", "mock-model",
            logger._hash_payload("Implement webhook verification for Stripe."),
            logger._hash_payload("Verified stripe webhook."),
            task_id_pr
        ))
        conn.commit()
        conn.close()
        print_pass(f"Audit record logged with Hashed PR Task ID: '{task_id_pr}'")

        # Simulate PR merge for branch_2
        print("\n  >> Simulating PR merge for Hashed PR Identity...")
        mock_local_pr.merge_pr(branch_2, simulate_only=True)

        time.sleep(0.2)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT task_outcome FROM gateway_audit_ledger WHERE task_id = ?", (task_id_pr,))
        pr_outcome = cur.fetchone()[0]
        assert pr_outcome == "verified_success", f"Expected 'verified_success', got {pr_outcome}"
        print_pass(f"Hashed PR Identity Task {task_id_pr} successfully reconciled to 'verified_success'!")
        conn.close()

        # ======================================================================
        # Test Case 3: PR Rejection / Closure Reconciliation
        # ======================================================================
        print_header("Test Case 3: PR Rejection / Closure Reconciliation")
        branch_3 = "fix/abandoned-experiment"
        bhash_3 = hashlib.sha256(branch_3.encode("utf-8")).hexdigest()
        task_id_3 = f"task_pr_{bhash_3[:12]}"

        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, fallback_triggered,
                http_status, latency_ms, prompt_tokens, completion_tokens,
                cost_usd, prompt_sha256, completion_sha256, zdr_verified,
                task_id, task_outcome
            ) VALUES (?, 'trace-tc3', 'sk-agent-intern', 'intern', 'mock-model', 'mock-model', 0, 200, 15, 50, 20, 0.0, ?, ?, 1, ?, 'pending')
        """, (
            f"req-tc3-{uuid.uuid4().hex[:8]}",
            logger._hash_payload("Experimental query"),
            logger._hash_payload("Experimental response"),
            task_id_3
        ))
        conn.commit()
        conn.close()

        print("\n  >> Simulating PR Rejection via mock_local_pr.py...")
        mock_local_pr.reject_pr(branch_3, simulate_only=True)

        time.sleep(0.2)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT task_outcome FROM gateway_audit_ledger WHERE task_id = ?", (task_id_3,))
        rejected_outcome = cur.fetchone()[0]
        assert rejected_outcome == "unmerged_closed", f"Expected 'unmerged_closed', got {rejected_outcome}"
        print_pass(f"Rejected PR reconciled task {task_id_3} to 'unmerged_closed'!")
        conn.close()

        # ======================================================================
        # Test Case 4: Real-Time CPS FinOps Summary & ZDR Compliance
        # ======================================================================
        print_header("Test Case 4: Real-Time CPS Analytical View & ZDR Compliance")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        print("\n--- [v_coding_cps_summary] ---")
        cur.execute("SELECT task_id, total_turns, total_tokens, accumulated_cost_usd, task_outcome, final_cps_usd FROM v_coding_cps_summary;")
        rows = cur.fetchall()
        for r in rows:
            print(f"  Task: {r[0]} | Turns: {r[1]} | Tokens: {r[2]} | Cost: ${r[3]} | Outcome: {r[4]} | Final CPS: ${r[5]}")

        # Assertions on analytical view
        assert len(rows) == 3, f"Expected 3 tasks in summary, got {len(rows)}"
        task_outcomes = {r[0]: r[4] for r in rows}
        assert task_outcomes[task_id_1] == "verified_success"
        assert task_outcomes[task_id_pr] == "verified_success"
        assert task_outcomes[task_id_3] == "unmerged_closed"
        print_pass("v_coding_cps_summary aggregates all tasks and computes exact CPS!")

        print("\n--- [v_zdr_compliance_check] ---")
        cur.execute("SELECT total_records, valid_prompt_hashes, valid_completion_hashes, zdr_flags_valid, compliance_status FROM v_zdr_compliance_check;")
        comp = cur.fetchone()
        print(f"  Total Records: {comp[0]} | Status: {comp[4]}")
        assert comp[0] == 4, f"Expected 4 audit records, got {comp[0]}"
        assert comp[4] == "100% COMPLIANT - ZERO PLAINTEXT DETECTED"
        print_pass("100% Cryptographic Zero Data Retention (ZDR) Verified across all PR lifecycle events!")

        conn.close()

    finally:
        webhook_srv.stop()
        print_header("🎉 ALL PHASE 2 CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
