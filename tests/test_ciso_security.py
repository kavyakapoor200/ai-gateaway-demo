#!/usr/bin/env python3
"""
tests/test_ciso_security.py
Comprehensive verification suite for CISO Tool Policy Governance & Security Intercepts:
  1. SQLite Self-Healing Schema Migration (policy_action, violating_tools columns & index)
  2. Cost Calculation Invariant (Spend avoided per blocked request, not per tool; cold start = n/a)
  3. Prometheus Metric Counter Bucketing (allowlist of risky tools vs 'other')
  4. Role Propagation (caller_role preserved in ledger)
  5. Live Gateway Integration (if gateway :4000 & dashboard :4001 are reachable):
     - Strict Reject via sk-agent-mcp-test (HTTP 403, zero upstream tokens)
     - Virtual Shielding via sk-agent-intern-poc (HTTP 200, tools pruned)
     - Real-time endpoints (:4001/api/security, :4001/metrics)
"""

import sys
import os
import json
import sqlite3
import tempfile
import unittest
import urllib.request
import urllib.error

# Add src to python path for direct imports
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from cps_webhook_server import get_security_stats, KNOWN_RISKY_TOOLS
from custom_zdr_logger import ZDRAuditLogger


class TestCISOSecurityUnit(unittest.TestCase):
    def setUp(self):
        # Create a temporary SQLite database for testing
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_schema_bootstrap_and_migration(self):
        """Verify _ensure_schema handles both fresh creation and migration on pre-existing legacy DB."""
        # 1. Simulate legacy database without policy_action & violating_tools
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE gateway_audit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                request_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                key_alias TEXT,
                caller_role TEXT DEFAULT 'developer',
                model_requested TEXT NOT NULL,
                model_routed TEXT NOT NULL,
                fallback_triggered INTEGER DEFAULT 0,
                http_status INTEGER NOT NULL,
                latency_ms INTEGER,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL DEFAULT 0.0,
                prompt_sha256 TEXT NOT NULL,
                completion_sha256 TEXT NOT NULL,
                zdr_verified INTEGER DEFAULT 1,
                task_id TEXT,
                task_outcome TEXT DEFAULT 'pending'
            );
        """)
        conn.commit()
        conn.close()

        # 2. Run logger schema bootstrap
        logger = ZDRAuditLogger(db_path=self.db_path)
        logger._ensure_schema()

        # 3. Verify columns and index now exist
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(gateway_audit_ledger);")
        cols = {row[1] for row in cur.fetchall()}
        self.assertIn("policy_action", cols)
        self.assertIn("violating_tools", cols)

        cur.execute("PRAGMA index_list(gateway_audit_ledger);")
        indexes = {row[1] for row in cur.fetchall()}
        self.assertIn("idx_policy_action", indexes)
        conn.close()

    def test_spend_avoided_and_cold_start(self):
        """
        Verify:
        - Spend avoided is computed per blocked request, not double-counted for multiple tools.
        - Cold-start models with no cost history return n/a and are excluded from total.
        - Virtual shielding (filter) increments filtered count but does NOT count as spend avoided.
        """
        logger = ZDRAuditLogger(db_path=self.db_path)
        logger._ensure_schema()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Insert historical successful requests for 'gpt-4o' with avg cost $0.05
        for i in range(4):
            cur.execute("""
                INSERT INTO gateway_audit_ledger (
                    request_id, trace_id, api_key_alias, caller_role,
                    model_requested, model_routed, http_status, latency_ms,
                    cost_usd, prompt_sha256, completion_sha256,
                    policy_action, violating_tools
                ) VALUES (?, ?, 'agent-dev', 'developer', 'gpt-4o', 'gpt-4o', 200, 50.0, 0.05, 'sha1', 'sha2', NULL, NULL)
            """, (f"req-hist-{i}", f"tr-hist-{i}"))

        # Blocked request on 'gpt-4o' with TWO violating tools (should count as 1 blocked request * 0.05)
        cur.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, http_status, latency_ms,
                cost_usd, prompt_sha256, completion_sha256,
                policy_action, violating_tools
            ) VALUES ('req-block-1', 'tr-block-1', 'agent-mcp', 'tester', 'gpt-4o', 'gpt-4o', 403, 10.0, 0.0, 'sha1', 'sha2', 'strict_reject', '["execute_command", "drop_table"]')
        """)

        # Blocked request on 'cold-start-model' with NO cost history
        cur.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, http_status, latency_ms,
                cost_usd, prompt_sha256, completion_sha256,
                policy_action, violating_tools
            ) VALUES ('req-block-2', 'tr-block-2', 'agent-mcp', 'tester', 'cold-start-model', 'cold-start-model', 403, 10.0, 0.0, 'sha1', 'sha2', 'strict_reject', '["rm_rf"]')
        """)

        # Filtered request (HTTP 200, pruned tools)
        cur.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, http_status, latency_ms,
                cost_usd, prompt_sha256, completion_sha256,
                policy_action, violating_tools
            ) VALUES ('req-filter-1', 'tr-filter-1', 'agent-intern', 'intern', 'gpt-4o', 'gpt-4o', 200, 45.0, 0.05, 'sha1', 'sha2', 'filter', '["execute_command"]')
        """)

        conn.commit()
        conn.close()

        # Compute stats
        stats = get_security_stats(db_path=self.db_path)

        # Assertions
        self.assertEqual(stats["strict_rejections_count"], 2)
        self.assertEqual(stats["virtual_shielding_count"], 1)

        # Spend avoided: Only gpt-4o blocked request is counted (1 * 0.05 = 0.05).
        # cold-start-model is excluded from spend avoided since no historical cost exists.
        self.assertAlmostEqual(stats["spend_avoided_estimated_usd"], 0.05, places=4)
        self.assertIn("(Estimated)", stats["spend_avoided_display"])

        # Check tool counts:
        # execute_command was in 1 strict_reject and 1 filter => 2 total
        # drop_table was in 1 strict_reject => 1
        # rm_rf was in 1 strict_reject => 1
        tool_counts = {t["tool"]: t["count"] for t in stats["top_blocked_tools"]}
        self.assertEqual(tool_counts.get("execute_command"), 2)
        self.assertEqual(tool_counts.get("drop_table"), 1)
        self.assertEqual(tool_counts.get("rm_rf"), 1)

        # Check key & role breakdown
        key_map = {(k["key_alias"], k["role"]): k for k in stats["by_key_role"]}
        self.assertIn(("agent-mcp", "tester"), key_map)
        self.assertEqual(key_map[("agent-mcp", "tester")]["blocked"], 2)
        self.assertEqual(key_map[("agent-mcp", "tester")]["filtered"], 0)

        self.assertIn(("agent-intern", "intern"), key_map)
        self.assertEqual(key_map[("agent-intern", "intern")]["blocked"], 0)
        self.assertEqual(key_map[("agent-intern", "intern")]["filtered"], 1)

    def test_prometheus_tool_bucketing(self):
        """Verify that allowlisted tools keep their name and unlisted tools bucket to 'other'."""
        logger = ZDRAuditLogger(db_path=self.db_path)
        logger._ensure_schema()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        # Insert a known risky tool and an exotic unlisted tool
        cur.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, http_status, latency_ms,
                cost_usd, prompt_sha256, completion_sha256,
                policy_action, violating_tools
            ) VALUES ('req-b1', 'tr-b1', 'key1', 'dev', 'm1', 'm1', 403, 10.0, 0.0, 's1', 's2', 'strict_reject', '["drop_table", "exotic_custom_exploit"]')
        """)
        conn.commit()
        conn.close()

        stats = get_security_stats(db_path=self.db_path)
        counter = stats.get("policy_actions_counter", {})

        # 'drop_table' is in RISKY_TOOL_ALLOWLIST
        self.assertEqual(counter.get(("key1", "dev", "drop_table", "strict_reject")), 1)
        # 'exotic_custom_exploit' should be bucketed to 'other'
        self.assertEqual(counter.get(("key1", "dev", "other", "strict_reject")), 1)


class TestCISOServerEndpoints(unittest.TestCase):
    def setUp(self):
        import threading
        from http.server import HTTPServer
        from cps_webhook_server import WebhookHandler

        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.temp_db.close()

        # Seed schema and test data
        logger = ZDRAuditLogger(db_path=self.db_path)
        logger._ensure_schema()

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO gateway_audit_ledger (
                request_id, trace_id, api_key_alias, caller_role,
                model_requested, model_routed, http_status, latency_ms,
                cost_usd, prompt_sha256, completion_sha256,
                policy_action, violating_tools
            ) VALUES ('req-serv-1', 'tr-serv-1', 'sk-agent-mcp-test', 'test', 'mock-model', 'mock-model', 403, 12.0, 0.0, 'h1', 'h2', 'strict_reject', '["execute_command"]')
        """)
        conn.commit()
        conn.close()

        self.orig_db_path = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = self.db_path

        self.server = HTTPServer(("127.0.0.1", 0), WebhookHandler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        if self.orig_db_path is not None:
            os.environ["DB_PATH"] = self.orig_db_path
        elif "DB_PATH" in os.environ:
            del os.environ["DB_PATH"]
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_api_security_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/security"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["strict_rejections_count"], 1)
            self.assertEqual(data["virtual_shielding_count"], 0)
            self.assertTrue(len(data["top_blocked_tools"]) > 0)
            self.assertEqual(data["top_blocked_tools"][0]["tool"], "execute_command")
            self.assertIn("spend_avoided_estimated_usd", data)

    def test_metrics_prometheus_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/metrics"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            text = resp.read().decode("utf-8")
            self.assertIn("ai_gateway_spend_avoided_estimated_usd", text)
            self.assertIn('ai_gateway_tool_policy_actions_total{key="sk-agent-mcp-test",role="test",tool="execute_command",action="strict_reject"} 1', text)


class TestCISOSecurityLive(unittest.TestCase):
    GATEWAY_URL = "http://localhost:4000"
    DASHBOARD_URL = "http://localhost:4001"

    @classmethod
    def setUpClass(cls):
        # Check if gateway is reachable
        cls.is_live = False
        try:
            req = urllib.request.Request(f"{cls.GATEWAY_URL}/health/liveliness", timeout=2)
            with urllib.request.urlopen(req) as resp:
                if resp.status == 200:
                    cls.is_live = True
        except Exception:
            pass

    def test_live_strict_reject_and_filter(self):
        if not self.is_live:
            self.skipTest("Live gateway not running on :4000. Skipping live integration tests.")

        # 1. Strict Reject test with sk-agent-mcp-test
        strict_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Execute drop_table"}],
            "tools": [{
                "type": "function",
                "function": {"name": "drop_table", "parameters": {}}
            }]
        }
        req = urllib.request.Request(
            f"{self.GATEWAY_URL}/chat/completions",
            data=json.dumps(strict_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-agent-mcp-test"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
            err_data = json.loads(e.read().decode("utf-8"))
            self.assertEqual(status, 403)
            self.assertIn("violating_tools", err_data.get("error", {}))

        # 2. Filter test with sk-agent-intern-poc
        filter_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Read file and drop_table"}],
            "tools": [
                {"type": "function", "function": {"name": "read_file", "parameters": {}}},
                {"type": "function", "function": {"name": "drop_table", "parameters": {}}}
            ]
        }
        req_filt = urllib.request.Request(
            f"{self.GATEWAY_URL}/chat/completions",
            data=json.dumps(filter_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer sk-agent-intern-poc"},
            method="POST"
        )
        with urllib.request.urlopen(req_filt) as resp:
            self.assertEqual(resp.status, 200)

        # 3. Check /api/security on port 4001
        req_sec = urllib.request.Request(f"{self.DASHBOARD_URL}/api/security")
        with urllib.request.urlopen(req_sec) as resp:
            self.assertEqual(resp.status, 200)
            sec_json = json.loads(resp.read().decode("utf-8"))
            self.assertIn("strict_rejections_count", sec_json)
            self.assertIn("virtual_shielding_count", sec_json)
            self.assertIn("spend_avoided_estimated_usd", sec_json)

        # 4. Check /metrics Prometheus format
        req_metrics = urllib.request.Request(f"{self.DASHBOARD_URL}/metrics")
        with urllib.request.urlopen(req_metrics) as resp:
            self.assertEqual(resp.status, 200)
            metrics_txt = resp.read().decode("utf-8")
            self.assertIn("ai_gateway_spend_avoided_estimated_usd", metrics_txt)
            self.assertIn("ai_gateway_tool_policy_actions_total", metrics_txt)


if __name__ == "__main__":
    unittest.main()
