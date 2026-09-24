#!/usr/bin/env python3
"""
tests/test_phase1.py: Verification suite for Phase 1 of Minimal Local AI Gateway PoC.
Tests:
1. SQLite Schema, WAL mode, Indexes, and Views.
2. Direct CRUD operations on gateway_audit_ledger.
3. ZDRAuditLogger in-RAM SHA-256 calculation & zero plaintext retention.
4. Deterministic Zero-Touch Task ID Derivation.
5. In-flight Git branch sniffing & Redis bhash:<sha256> indexing.
6. Synchronous & Asynchronous LiteLLM callback event logging.
7. Verification of v_coding_cps_summary and v_zdr_compliance_check views.
"""

import os
import sys
import time
import uuid
import hashlib
import sqlite3
import socket
import asyncio
from typing import Dict, Any

# Ensure parent directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from custom_zdr_logger import ZDRAuditLogger

# Test Database path
TEST_DB_PATH = os.path.join(PROJECT_ROOT, "data", "test_gateway.db")


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
# 1. Schema & WAL Mode Verification
# ==============================================================================
def test_schema_and_wal():
    print_header("Step 1: SQLite Schema, WAL Mode & Views Verification")
    
    # Remove existing test DB if present
    for ext in ["", "-wal", "-shm"]:
        p = TEST_DB_PATH + ext
        if os.path.exists(p):
            os.remove(p)

    schema_file = os.path.join(PROJECT_ROOT, "sqlite_schema.sql")
    conn = sqlite3.connect(TEST_DB_PATH)
    with open(schema_file, "r") as f:
        conn.executescript(f.read())

    # Check WAL Mode
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    if mode.lower() == "wal":
        print_pass(f"Journal mode is WAL: '{mode}'")
    else:
        print_fail(f"Expected WAL mode, got '{mode}'")

    # Check Tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gateway_audit_ledger';")
    if cur.fetchone():
        print_pass("Table 'gateway_audit_ledger' exists")
    else:
        print_fail("Table 'gateway_audit_ledger' missing")

    # Check Views
    cur.execute("SELECT name FROM sqlite_master WHERE type='view';")
    views = [r[0] for r in cur.fetchall()]
    assert "v_coding_cps_summary" in views, "v_coding_cps_summary missing"
    assert "v_zdr_compliance_check" in views, "v_zdr_compliance_check missing"
    print_pass(f"Analytical views exist: {views}")

    # Check Indexes
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%';")
    indexes = [r[0] for r in cur.fetchall()]
    expected_indexes = ["idx_trace_id", "idx_task_id", "idx_created_at"]
    for idx in expected_indexes:
        assert idx in indexes, f"Index {idx} missing"
    print_pass(f"Fast lookup indexes verified: {indexes}")

    conn.close()


# ==============================================================================
# 2. Direct CRUD Operations on Schema
# ==============================================================================
def test_crud_operations():
    print_header("Step 2: Direct CRUD Operations on Schema")
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()

    req_id = f"test-req-{uuid.uuid4().hex[:8]}"
    trace_id = f"trace-{uuid.uuid4().hex[:16]}"
    p_hash = hashlib.sha256(b"User test prompt").hexdigest()
    c_hash = hashlib.sha256(b"Assistant completion").hexdigest()
    task_id = "task_test_crud_001"

    # CREATE
    cur.execute("""
        INSERT INTO gateway_audit_ledger (
            request_id, trace_id, api_key_alias, caller_role,
            model_requested, model_routed, fallback_triggered,
            http_status, latency_ms, prompt_tokens, completion_tokens,
            cost_usd, prompt_sha256, completion_sha256, zdr_verified,
            task_id, task_outcome
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'pending')
    """, (
        req_id, trace_id, "sk-agent-developer", "developer",
        "mock-model", "mock-model", 0,
        200, 45.2, 100, 50, 0.000375,
        p_hash, c_hash, task_id
    ))
    conn.commit()
    print_pass(f"CREATE: Inserted audit record {req_id}")

    # READ
    cur.execute("SELECT request_id, model_routed, latency_ms, task_outcome FROM gateway_audit_ledger WHERE request_id = ?", (req_id,))
    row = cur.fetchone()
    assert row is not None, "Failed to read back inserted record"
    assert row[0] == req_id and row[1] == "mock-model" and row[3] == "pending"
    print_pass(f"READ: Successfully fetched record (model={row[1]}, outcome={row[3]})")

    # UPDATE (Simulate PR Merge reconciliation)
    cur.execute("UPDATE gateway_audit_ledger SET task_outcome = 'verified_success' WHERE task_id = ?", (task_id,))
    conn.commit()
    cur.execute("SELECT task_outcome FROM gateway_audit_ledger WHERE request_id = ?", (req_id,))
    updated_outcome = cur.fetchone()[0]
    assert updated_outcome == "verified_success", f"Expected 'verified_success', got '{updated_outcome}'"
    print_pass(f"UPDATE: Updated task_outcome to '{updated_outcome}'")

    # DELETE
    del_req_id = f"del-req-{uuid.uuid4().hex[:8]}"
    cur.execute("""
        INSERT INTO gateway_audit_ledger (
            request_id, trace_id, api_key_alias, caller_role,
            model_requested, model_routed, fallback_triggered,
            http_status, latency_ms, prompt_tokens, completion_tokens,
            cost_usd, prompt_sha256, completion_sha256, zdr_verified,
            task_id, task_outcome
        ) VALUES (?, ?, 'temp-key', 'intern', 'mock-model', 'mock-model', 0, 200, 10, 10, 10, 0.0, ?, ?, 1, 'task_del', 'pending')
    """, (del_req_id, trace_id, p_hash, c_hash))
    conn.commit()

    cur.execute("DELETE FROM gateway_audit_ledger WHERE request_id = ?", (del_req_id,))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM gateway_audit_ledger WHERE request_id = ?", (del_req_id,))
    assert cur.fetchone()[0] == 0
    print_pass(f"DELETE: Successfully removed temporary test record {del_req_id}")

    conn.close()


# ==============================================================================
# 3. ZDRAuditLogger Invariant & Zero-Touch Task ID Derivation
# ==============================================================================
def test_zdr_logger_unit_methods():
    print_header("Step 3: ZDRAuditLogger In-RAM Hashing & Task Derivation")
    logger = ZDRAuditLogger(db_path=TEST_DB_PATH)

    # In-RAM SHA-256
    raw_prompt = "Super confidential proprietary prompt"
    digest = logger._hash_payload(raw_prompt)
    assert len(digest) == 64, f"Hash length {len(digest)} != 64"
    assert digest == hashlib.sha256(raw_prompt.encode("utf-8")).hexdigest()
    print_pass(f"In-RAM SHA-256 digest format verified: {digest[:16]}...")

    # Root-Prompt Invariance (Multi-turn session must derive IDENTICAL task_id)
    key_alias = "sk-agent-developer"
    
    # Turn 1
    messages_turn_1 = [
        {"role": "system", "content": "You are a coding assistant."},
        {"role": "user", "content": "Fix database timeout in backend pool."}
    ]
    task_id_1 = logger._derive_task_id(key_alias, messages_turn_1)

    # Turn 2 (Follow-up question with history appended)
    messages_turn_2 = [
        {"role": "system", "content": "You are a coding assistant."},
        {"role": "user", "content": "Fix database timeout in backend pool."},
        {"role": "assistant", "content": "I will examine connection pool configuration."},
        {"role": "user", "content": "Add connection timeout parameter of 30 seconds."}
    ]
    task_id_2 = logger._derive_task_id(key_alias, messages_turn_2)

    assert task_id_1 is not None and task_id_1.startswith("task_")
    assert task_id_1 == task_id_2, f"Task IDs diverged across turns: {task_id_1} vs {task_id_2}"
    print_pass(f"Zero-Touch Task ID Invariance holds across turns: '{task_id_1}'")


# ==============================================================================
# 4. In-Flight Branch Sniffing & Redis bhash:<sha256>
# ==============================================================================
def test_branch_sniffing():
    print_header("Step 4: In-Flight Branch Sniffing & Redis Indexing")
    redis_up = check_redis_available("localhost", 6379)
    logger = ZDRAuditLogger(db_path=TEST_DB_PATH, redis_host="localhost", redis_port=6379)

    branch_name = "feat/pool-timeout-p1"
    task_id = "task_phase1_branch_test"

    tool_calls = [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "execute_command",
                "arguments": f'{{"command": "git checkout -b {branch_name}"}}'
            }
        }
    ]

    # Test branch sniffing
    logger._sniff_and_index_branch(messages=[], tool_calls=tool_calls, task_id=task_id)

    if redis_up:
        expected_bhash = hashlib.sha256(branch_name.encode("utf-8")).hexdigest()
        redis_val = query_redis_key(f"bhash:{expected_bhash}")
        assert redis_val == task_id, f"Expected Redis task_id '{task_id}', got '{redis_val}'"
        print_pass(f"Branch '{branch_name}' sniffed -> Redis bhash:{expected_bhash[:16]}... = '{redis_val}'")
    else:
        print_pass(f"Branch sniffing executed (Redis offline notice gracefully handled)")


# ==============================================================================
# 5. Full Success & Failure Event Callbacks (Sync & Async)
# ==============================================================================
async def test_logger_events():
    print_header("Step 5: Full Success & Failure Event Callbacks (Sync & Async)")
    logger = ZDRAuditLogger(db_path=TEST_DB_PATH, redis_host="localhost", redis_port=6379)

    # 1. Success Event (Sync)
    req_kwargs_sync = {
        "model": "mock-model",
        "litellm_params": {"model": "mock-model"},
        "metadata": {"user_api_key_alias": "sk-agent-developer", "role": "developer", "trace_id": "trace-sync-001"},
        "messages": [
            {"role": "user", "content": "Implement binary search algorithm"}
        ]
    }
    class MockChoice:
        class Message:
            content = "Binary search implementation code..."
            tool_calls = None
        message = Message()
    class MockResponse:
        id = f"chatcmpl-sync-{uuid.uuid4().hex[:8]}"
        choices = [MockChoice()]
        class Usage:
            prompt_tokens = 25
            completion_tokens = 15
            total_tokens = 40
        usage = Usage()

    t_start = time.time()
    t_end = t_start + 0.045 # 45ms
    success_ok = logger.log_success_event(req_kwargs_sync, MockResponse(), t_start, t_end)
    assert success_ok is True
    print_pass(f"Synchronous log_success_event recorded {MockResponse.id}")

    # 2. Async Success Event (with tool call and branch creation)
    branch_name = "feat/binary-search-async"
    req_kwargs_async = {
        "model": "mock-model",
        "litellm_params": {"model": "mock-model"},
        "metadata": {"user_api_key_alias": "sk-agent-developer", "role": "developer", "trace_id": "trace-async-002"},
        "messages": [
            {"role": "user", "content": "Implement binary search algorithm"},
            {"role": "assistant", "content": "Creating branch", "tool_calls": [{"id": "c1", "type": "function", "function": {"arguments": f'{{"command": "git checkout -b {branch_name}"}}'}}]}
        ]
    }
    async_resp = MockResponse()
    async_resp.id = f"chatcmpl-async-{uuid.uuid4().hex[:8]}"
    async_ok = await logger.async_log_success_event(req_kwargs_async, async_resp, t_start, t_end)
    assert async_ok is True
    print_pass(f"Asynchronous async_log_success_event recorded {async_resp.id}")

    # 3. Failure Event (Model not allowed / rejection)
    fail_kwargs = {
        "model": "gpt-4o",
        "litellm_params": {"model": "gpt-4o"},
        "metadata": {"user_api_key_alias": "sk-agent-intern", "role": "intern", "trace_id": "trace-fail-003"},
        "messages": [{"role": "user", "content": "Unauthorized model call"}]
    }
    class MockError(Exception):
        status_code = 403
    fail_ok = logger.log_failure_event(fail_kwargs, MockError(), t_start, t_end, http_status=403)
    assert fail_ok is True
    print_pass("Failure event recorded with HTTP 403")


# ==============================================================================
# 6. Analytical Views & Compliance Verification
# ==============================================================================
def test_analytical_views():
    print_header("Step 6: Analytical Views & Compliance Check Verification")
    conn = sqlite3.connect(TEST_DB_PATH)
    cur = conn.cursor()

    # Query v_coding_cps_summary
    print("\n--- [v_coding_cps_summary] ---")
    cur.execute("SELECT task_id, total_turns, total_tokens, accumulated_cost_usd, task_outcome, final_cps_usd FROM v_coding_cps_summary;")
    rows = cur.fetchall()
    for r in rows:
        print(f"  Task: {r[0]} | Turns: {r[1]} | Tokens: {r[2]} | Cost: ${r[3]} | Outcome: {r[4]} | Final CPS: ${r[5]}")
    assert len(rows) > 0, "No records aggregated in v_coding_cps_summary"
    print_pass("v_coding_cps_summary aggregated correctly")

    # Query v_zdr_compliance_check
    print("\n--- [v_zdr_compliance_check] ---")
    cur.execute("SELECT total_records, valid_prompt_hashes, valid_completion_hashes, zdr_flags_valid, compliance_status FROM v_zdr_compliance_check;")
    comp_row = cur.fetchone()
    print(f"  Total Records: {comp_row[0]}")
    print(f"  Valid Prompt Hashes: {comp_row[1]}")
    print(f"  Valid Completion Hashes: {comp_row[2]}")
    print(f"  ZDR Flags Valid: {comp_row[3]}")
    print(f"  Status: {comp_row[4]}")

    assert comp_row[0] > 0, "Expected records in audit ledger"
    assert comp_row[0] == comp_row[1], "Invalid prompt hash detected!"
    assert comp_row[0] == comp_row[2], "Invalid completion hash detected!"
    assert comp_row[4] == "100% COMPLIANT - ZERO PLAINTEXT DETECTED", f"Compliance status: {comp_row[4]}"
    print_pass("100% Cryptographic Zero Data Retention (ZDR) Verified!")

    conn.close()


def main():
    print_header("Minimal Local AI Gateway: Phase 1 Test & Verification Suite")
    test_schema_and_wal()
    test_crud_operations()
    test_zdr_logger_unit_methods()
    test_branch_sniffing()
    asyncio.run(test_logger_events())
    test_analytical_views()
    print_header("🎉 ALL PHASE 1 CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
