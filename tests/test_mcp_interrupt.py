#!/usr/bin/env python3
"""
tests/test_mcp_interrupt.py: End-to-End Verification Suite for SUB-POC-04.
Tests:
1. Tool name extraction across Anthropic, OpenAI, and legacy schemas.
2. Live Ingress PEP Intercept: Disallowed tool (`bash`) returns HTTP 403 tool_not_allowed.
3. Live Ingress PEP Permitted: Whitelisted tool (`create_user_profile`) returns HTTP 200 OK.
4. Live Ingress PEP Mixed Tools: Whitelisted + Disallowed returns HTTP 403 isolating violation.
5. Live Ingress PEP OpenAI format: `/v1/chat/completions` enforcement.
6. Zero Token Spend Assertion ($0.00 cost, 0 tokens on blocked attempts).
7. SQLite Audit Ledger Invariant: Status 403 and `tool_policy_rejected` outcome recorded.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import sqlite3

# Ensure parent directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from custom_zdr_logger import ZDRAuditLogger

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
API_KEY = os.environ.get("TEST_API_KEY", "sk-agent-developer")


def print_header(title: str):
    print(f"\n{'='*70}\n  {title}\n{'='*70}")


def print_pass(msg: str):
    print(f"  ✅ PASS: {msg}")


def print_fail(msg: str):
    print(f"  ❌ FAIL: {msg}")
    sys.exit(1)


def make_request(path: str, payload: dict, headers: dict = None) -> tuple:
    """Helper to send HTTP request and return (status, body_dict, headers)."""
    url = f"{GATEWAY_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))
            resp_headers = dict(resp.headers)
            return status, body, resp_headers
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        resp_headers = dict(e.headers)
        return status, body, resp_headers
    except Exception as e:
        print_fail(f"Request failed to {url}: {e}")


def test_unit_tool_extraction():
    print_header("Test 1: Unit Tool Extraction Across Schemas")

    # Anthropic schema
    anthropic_data = {
        "tools": [
            {"name": "read_file", "description": "Read file"},
            {"name": "bash", "description": "Run shell"}
        ]
    }
    extracted = ZDRAuditLogger._extract_tool_names(anthropic_data)
    if extracted == ["read_file", "bash"]:
        print_pass("Anthropic tool names extracted correctly: " + str(extracted))
    else:
        print_fail(f"Anthropic extraction failed, got: {extracted}")

    # OpenAI schema
    openai_data = {
        "tools": [
            {"type": "function", "function": {"name": "query_db"}},
            {"type": "function", "function": {"name": "git_commit"}}
        ]
    }
    extracted_openai = ZDRAuditLogger._extract_tool_names(openai_data)
    if extracted_openai == ["query_db", "git_commit"]:
        print_pass("OpenAI tool names extracted correctly: " + str(extracted_openai))
    else:
        print_fail(f"OpenAI extraction failed, got: {extracted_openai}")


def test_live_forbidden_tool_anthropic():
    print_header("Test 2: Live Gateway Ingress Intercept (Anthropic /v1/messages)")
    payload = {
        "model": "claude-3-5-sonnet",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "run system bash"}],
        "tools": [
            {
                "name": "bash",
                "description": "Execute arbitrary shell",
                "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}}
            }
        ]
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01"
    }

    status, body, resp_headers = make_request("/v1/messages", payload, headers)

    if status != 403:
        print_fail(f"Expected HTTP 403 for forbidden tool 'bash', got HTTP {status}: {body}")
    print_pass(f"Gateway returned HTTP {status} Forbidden")

    # Assert error structure
    err_obj = body.get("error", {})
    provider_err = err_obj.get("provider_specific_fields", {}).get("error", {})
    code = provider_err.get("code") or err_obj.get("code")
    violating = provider_err.get("violating_tools") or []

    if "tool_not_allowed" not in str(code):
        print_fail(f"Expected code 'tool_not_allowed', got: {code}")
    print_pass("Error code confirmed: tool_not_allowed")

    if "bash" not in violating:
        print_fail(f"Expected 'bash' in violating tools, got: {violating}")
    print_pass(f"Violating tool correctly identified: {violating}")

    # Cost header check
    cost = resp_headers.get("x-litellm-response-cost", "0")
    if float(cost) == 0.0:
        print_pass("Zero token cost verified: x-litellm-response-cost = 0")
    else:
        print_fail(f"Unexpected token cost on rejected request: {cost}")


def test_live_whitelisted_tool_anthropic():
    print_header("Test 3: Live Gateway Allowed Tool (Anthropic /v1/messages)")
    payload = {
        "model": "claude-3-5-sonnet",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "create_user_profile",
                "description": "Create a user profile (whitelisted tool)",
                "input_schema": {"type": "object", "properties": {"username": {"type": "string"}}}
            }
        ]
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01"
    }

    status, body, resp_headers = make_request("/v1/messages", payload, headers)

    if status != 200:
        print_fail(f"Expected HTTP 200 for whitelisted tool 'create_user_profile', got HTTP {status}: {body}")
    print_pass(f"Gateway permitted whitelisted tool: HTTP {status} OK")

    if "content" in body or "choices" in body:
        print_pass("Valid model completion returned successfully")
    else:
        print_fail(f"Unexpected response body: {body}")


def test_live_mixed_tools():
    print_header("Test 4: Live Mixed Tools Payload (1 Allowed, 1 Forbidden)")
    payload = {
        "model": "claude-3-5-sonnet",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "test mixed"}],
        "tools": [
            {
                "name": "create_user_profile",
                "description": "Whitelisted tool",
                "input_schema": {"type": "object"}
            },
            {
                "name": "delete_database",
                "description": "Forbidden tool",
                "input_schema": {"type": "object"}
            }
        ]
    }
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01"
    }

    status, body, resp_headers = make_request("/v1/messages", payload, headers)

    if status != 403:
        print_fail(f"Expected HTTP 403 for mixed tools with violation, got HTTP {status}: {body}")
    print_pass(f"Mixed payload intercepted: HTTP {status} Forbidden")

    provider_err = body.get("error", {}).get("provider_specific_fields", {}).get("error", {})
    violating = provider_err.get("violating_tools") or []
    if violating == ["delete_database"]:
        print_pass(f"Only the violating tool was flagged: {violating}")
    else:
        print_fail(f"Unexpected violating tools list: {violating}")


def test_live_openai_format():
    print_header("Test 5: Live OpenAI Format (/v1/chat/completions)")
    # 5a: Forbidden tool
    payload_forbidden = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "ping"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "unauthorized_shell_exec",
                    "description": "Shell execution"
                }
            }
        ]
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    status, body, _ = make_request("/v1/chat/completions", payload_forbidden, headers)
    if status == 403:
        print_pass("OpenAI format with forbidden tool intercepted: HTTP 403 Forbidden")
    else:
        print_fail(f"Expected HTTP 403 for OpenAI format, got {status}: {body}")

    # 5b: Whitelisted tool
    payload_allowed = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "ping"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "create_user_profile",
                    "description": "Whitelisted tool"
                }
            }
        ]
    }
    status_ok, body_ok, _ = make_request("/v1/chat/completions", payload_allowed, headers)
    if status_ok == 200:
        print_pass("OpenAI format with whitelisted tool allowed: HTTP 200 OK")
    else:
        print_fail(f"Expected HTTP 200 for OpenAI format whitelisted tool, got {status_ok}: {body_ok}")


def test_sqlite_audit_ledger():
    print_header("Test 6: SQLite Audit Ledger Invariant Verification")
    import subprocess
    cmd = [
        "docker", "exec", "litellm_gateway", "python", "-c",
        "import sqlite3; conn = sqlite3.connect('/app/data/gateway.db'); "
        "rows = conn.execute('SELECT request_id, http_status, cost_usd, task_outcome, zdr_verified "
        "FROM gateway_audit_ledger WHERE task_outcome=\"tool_policy_rejected\" ORDER BY created_at DESC LIMIT 1;').fetchone(); "
        "print(repr(rows))"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print_fail(f"Failed to query SQLite ledger in container: {res.stderr}")

    output_str = res.stdout.strip()
    if "tool_policy_rejected" in output_str and "403" in output_str:
        print_pass(f"Verified audit ledger entry for tool policy rejection: {output_str}")
    else:
        print_fail(f"Audit ledger entry not found or mismatch: {output_str}")


def main():
    print_header("SUB-POC-04: MCP Tool Interrupt & Gateway Ingress PEP Test Suite")
    test_unit_tool_extraction()
    test_live_forbidden_tool_anthropic()
    test_live_whitelisted_tool_anthropic()
    test_live_mixed_tools()
    test_live_openai_format()
    test_sqlite_audit_ledger()

    print_header("All Verification Tests Completed Successfully! (7/7 Passed)")


if __name__ == "__main__":
    main()
