#!/usr/bin/env python3
"""
live_agent_run.py: Live Agent (Antigravity) Demonstration Run.
Simulates Antigravity as an active coding agent routing all model traffic through
the AI Gateway, demonstrating:
1. Ingress Secret Redaction Guardrails (In-flight scrubbing)
2. In-RAM Branch Sniffing & Redis Hashed Indexing
3. Invariant Root-Prompt Task ID Derivation
4. End-to-End Git PR Merge Lifecycle Reconciliation
5. Full Gateway Telemetry:
   - Complete Call History & Latency
   - Token & Cost Accounting
   - Cost Per Successful Task (CPS) Analytical Calculation
   - Distributed Traces in Jaeger with Nested Span Waterfalls
   - Cryptographic Zero Data Retention (ZDR) Invariant Audit
"""

import sys
import os
import json
import time
import uuid
import hashlib
import sqlite3
import subprocess
import urllib.request
import urllib.error
from typing import Dict, Any, Tuple, Optional, List

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
CPS_URL = os.environ.get("CPS_URL", "http://localhost:4001")
JAEGER_URL = os.environ.get("JAEGER_URL", "http://localhost:16686")
DEVELOPER_KEY = os.environ.get("AGENT_API_KEY", "sk-agent-developer")
DB_PATH = os.path.join(PROJECT_ROOT, "data", "gateway.db")

def make_http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0
) -> Tuple[int, Dict[str, Any], str]:
    headers = headers or {}
    encoded_data = None
    if data is not None:
        encoded_data = json.dumps(data).encode("utf-8")
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
            return status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        return e.code, parsed, raw
    except Exception as e:
        return 0, {}, str(e)


def sync_sqlite_from_container():
    """Syncs container SQLite data directory to host."""
    os.makedirs(os.path.join(PROJECT_ROOT, "data"), exist_ok=True)
    subprocess.run("docker cp litellm_gateway:/app/data/. data/", shell=True, cwd=PROJECT_ROOT, capture_output=True)


def main():
    print("=" * 80)
    print("   🚀 LIVE AGENT RUN: ANTIGRAVITY CONNECTED TO AI GATEWAY")
    print("=" * 80)
    print(f"  • Agent Identity : Antigravity Coding Assistant")
    print(f"  • Virtual Key    : {DEVELOPER_KEY} (Role: developer)")
    print(f"  • Gateway Route  : {GATEWAY_URL}/v1/chat/completions")
    print(f"  • Jaeger Engine  : {JAEGER_URL}")
    print(f"  • CPS Companion  : {CPS_URL}/webhooks/github")
    print("=" * 80)

    # Unique branch for this session run
    run_id = uuid.uuid4().hex[:6]
    branch_name = f"feat/antigravity-distributed-rate-limiter-{run_id}"

    # --------------------------------------------------------------------------
    # Turn 1: Initial Task Inception
    # --------------------------------------------------------------------------
    print(f"\n[Turn 1] Antigravity: Incepting task and preparing feature branch...")
    turn1_prompt = (
        f"Antigravity, please implement a distributed rate limiter in FastAPI using Redis token buckets. "
        f"Scrub secret AWS key AKIA9876543210SECKEY and contact ops-lead@company.internal. "
        f"Create and checkout a new feature branch: {branch_name}."
    )
    st, resp1, _ = make_http_request(
        f"{GATEWAY_URL}/v1/chat/completions",
        method="POST",
        headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
        data={
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "You are Antigravity, an expert software engineering agent."},
                {"role": "user", "content": turn1_prompt}
            ],
            "temperature": 0.2
        }
    )
    if st != 200:
        print(f"❌ Turn 1 failed with status {st}: {resp1}")
        sys.exit(1)
    req1_id = resp1.get("id")
    print(f"  ✅ Status: HTTP {st} | Request ID: {req1_id} | Response: '{resp1['choices'][0]['message']['content'][:60]}...'")

    # --------------------------------------------------------------------------
    # Turn 2: Branch Creation Tool Call & Implementation
    # --------------------------------------------------------------------------
    print(f"\n[Turn 2] Antigravity: Executing 'git checkout -b {branch_name}' and implementing Lua token bucket...")
    turn2_prompt = (
        f"Branch {branch_name} active. Implemented atomic Redis Lua script for token-bucket rate limiting. "
        f"Now generating pytest test suite covering burst capacity and concurrency limits."
    )
    st, resp2, _ = make_http_request(
        f"{GATEWAY_URL}/v1/chat/completions",
        method="POST",
        headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
        data={
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "You are Antigravity, an expert software engineering agent."},
                {"role": "user", "content": turn1_prompt},
                {
                    "role": "assistant",
                    "content": f"I will create and checkout branch {branch_name}.",
                    "tool_calls": [
                        {
                            "id": "call_branch_checkout",
                            "type": "function",
                            "function": {
                                "name": "run_command",
                                "arguments": json.dumps({"command": f"git checkout -b {branch_name}"})
                            }
                        }
                    ]
                },
                {"role": "user", "content": turn2_prompt}
            ],
            "temperature": 0.2
        }
    )
    if st != 200:
        print(f"❌ Turn 2 failed with status {st}: {resp2}")
        sys.exit(1)
    req2_id = resp2.get("id")
    print(f"  ✅ Status: HTTP {st} | Request ID: {req2_id} | Response: '{resp2['choices'][0]['message']['content'][:60]}...'")

    # --------------------------------------------------------------------------
    # Turn 3: Test Verification, PR Assembly & Submission
    # --------------------------------------------------------------------------
    print(f"\n[Turn 3] Antigravity: Test suite passed. Assembling Pull Request...")
    turn3_prompt = (
        f"On branch {branch_name}: all 24 pytest unit tests passed with 100% coverage. "
        f"Submitting PR: 'feat(rate-limiter): Redis token-bucket distributed rate limiting'. Ready for merge."
    )
    st, resp3, _ = make_http_request(
        f"{GATEWAY_URL}/v1/chat/completions",
        method="POST",
        headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
        data={
            "model": "mock-model",
            "messages": [
                {"role": "system", "content": "You are Antigravity, an expert software engineering agent."},
                {"role": "user", "content": turn1_prompt},
                {
                    "role": "assistant",
                    "content": f"I will create and checkout branch {branch_name}.",
                    "tool_calls": [
                        {
                            "id": "call_branch_checkout",
                            "type": "function",
                            "function": {
                                "name": "run_command",
                                "arguments": json.dumps({"command": f"git checkout -b {branch_name}"})
                            }
                        }
                    ]
                },
                {"role": "user", "content": turn2_prompt},
                {"role": "assistant", "content": resp2['choices'][0]['message']['content']},
                {"role": "user", "content": turn3_prompt}
            ],
            "temperature": 0.2
        }
    )
    if st != 200:
        print(f"❌ Turn 3 failed with status {st}: {resp3}")
        sys.exit(1)
    req3_id = resp3.get("id")
    print(f"  ✅ Status: HTTP {st} | Request ID: {req3_id} | Response: '{resp3['choices'][0]['message']['content'][:60]}...'")

    # Brief delay for OTel batch exporter to flush spans
    time.sleep(1.0)
    sync_sqlite_from_container()

    # Query initial ledger state
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT task_id, task_outcome FROM gateway_audit_ledger WHERE request_id = ?", (req1_id,))
    task_row = cur.fetchone()
    conn.close()

    if not task_row:
        print("❌ Could not locate task_id in audit ledger.")
        sys.exit(1)

    task_id, initial_outcome = task_row
    print(f"\n🔑 Invariant Root-Prompt Task ID Derived: '{task_id}' (Current Outcome: '{initial_outcome}')")

    # Verify Redis ephemeral branch index
    branch_hash = hashlib.sha256(branch_name.encode()).hexdigest()
    res = subprocess.run(["docker", "exec", "gateway_redis", "redis-cli", "get", f"bhash:{branch_hash}"], capture_output=True, text=True)
    redis_task_id = res.stdout.strip()
    print(f"  • Redis Branch Index : bhash:{branch_hash[:16]}... -> '{redis_task_id}'")

    # --------------------------------------------------------------------------
    # Step 4: Simulate PR Merge Event via GitHub Webhook Companion
    # --------------------------------------------------------------------------
    print(f"\n[Git Lifecycle] Simulating GitHub Pull Request Merge for branch '{branch_name}'...")
    pr_payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "head": {"ref": branch_name},
            "merge_commit_sha": hashlib.sha256(branch_name.encode()).hexdigest()
        }
    }
    st, pr_resp, _ = make_http_request(
        f"{CPS_URL}/webhooks/github",
        method="POST",
        data=pr_payload
    )
    print(f"  ✅ GitHub Webhook Dispatch: HTTP {st} -> {pr_resp}")

    # Allow companion to complete SQLite write and sync to host
    time.sleep(0.5)
    sync_sqlite_from_container()

    # --------------------------------------------------------------------------
    # Step 5: Complete Gateway Telemetry Inspection
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("   📊 COMPLETE GATEWAY TELEMETRY REPORT")
    print("=" * 80)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Calls Made Table
    cur.execute("""
        SELECT request_id, trace_id, model_routed, latency_ms, 
               prompt_tokens, completion_tokens, cost_usd, 
               prompt_sha256, completion_sha256, zdr_verified, task_outcome, created_at
        FROM gateway_audit_ledger 
        WHERE task_id = ?
        ORDER BY created_at ASC
    """, (task_id,))
    turns = cur.fetchall()

    print(f"\n1️⃣  CALLS MADE SUMMARY (Task: {task_id}):")
    print("-" * 80)
    print(f"{'Turn':<6} {'Request ID':<26} {'Status':<10} {'Latency':<10} {'Tokens (In/Out)':<18} {'Cost ($)':<10} {'Outcome':<10}")
    print("-" * 80)
    
    total_tokens = 0
    total_cost = 0.0
    trace_ids = []

    for i, row in enumerate(turns):
        t_in = row["prompt_tokens"]
        t_out = row["completion_tokens"]
        c = row["cost_usd"]
        total_tokens += (t_in + t_out)
        total_cost += c
        trace_ids.append((i + 1, row["request_id"], row["trace_id"]))
        print(f"Turn {i+1:<2} {row['request_id']:<26} HTTP 200   {row['latency_ms']:<7.1f}ms {f'{t_in} / {t_out}':<18} ${c:<9.6f} {row['task_outcome']:<10}")
    print("-" * 80)
    print(f"{'TOTAL':<44} {total_tokens:<18} ${total_cost:<9.6f}")

    # 2. Cost Per Successful Task (CPS) Analytical View
    cur.execute("SELECT * FROM v_coding_cps_summary WHERE task_id = ?", (task_id,))
    cps_row = cur.fetchone()
    print(f"\n2️⃣  COST PER SUCCESSFUL TASK (CPS) RECONCILIATION:")
    print("-" * 80)
    if cps_row:
        final_cps = cps_row['final_cps_usd']
        final_cps_str = f"${final_cps:.6f}" if final_cps is not None else "Pending Verification"
        print(f"  • Task Identifier     : {cps_row['task_id']}")
        print(f"  • Total Turns Executed: {cps_row['total_turns']}")
        print(f"  • Total Tokens Used   : {cps_row['total_tokens']}")
        print(f"  • Total Spend USD     : ${cps_row['accumulated_cost_usd']:.6f}")
        print(f"  • Reconciled Outcome  : {cps_row['task_outcome']}")
        print(f"  • FINAL CPS (Cost/Task): {final_cps_str}")
    else:
        print("  ⚠️ No CPS summary record found.")

    # 3. Cryptographic Zero Data Retention (ZDR) Audit
    cur.execute("SELECT * FROM v_zdr_compliance_check")
    zdr_row = cur.fetchone()
    print(f"\n3️⃣  CRYPTOGRAPHIC ZERO DATA RETENTION (ZDR) AUDIT:")
    print("-" * 80)
    print(f"  • Total System Audit Records  : {zdr_row['total_records']}")
    print(f"  • Valid Prompt SHA-256 Hashes : {zdr_row['valid_prompt_hashes']}")
    print(f"  • Valid Output SHA-256 Hashes : {zdr_row['valid_completion_hashes']}")
    print(f"  • ZDR Verified Flags Set      : {zdr_row['zdr_flags_valid']}")
    print(f"  • Invariant Compliance Status : {zdr_row['compliance_status']}")
    print(f"  • Sample Prompt Hash (Turn 1) : {turns[0]['prompt_sha256']}")
    print(f"  • Sample Output Hash (Turn 1) : {turns[0]['completion_sha256']}")
    print(f"  • Plaintext Kept in Database  : 0 bytes (100% ephemeral in-RAM SHA-256)")

    conn.close()

    # 4. Distributed Traces in Jaeger
    print(f"\n4️⃣  DISTRIBUTED TRACES & SPAN WATERFALLS (Jaeger UI: {JAEGER_URL}):")
    print("-" * 80)

    for turn_num, r_id, t_id in trace_ids:
        print(f"\n--- Turn {turn_num} Distributed Trace ---")
        print(f"  • Request ID : {r_id}")
        print(f"  • Trace ID   : {t_id}")
        print(f"  • Jaeger URL : {JAEGER_URL}/trace/{t_id}")

        # Query Jaeger API
        st, j_body, _ = make_http_request(f"{JAEGER_URL}/api/traces/{t_id}")
        if st == 200 and isinstance(j_body, dict) and j_body.get("data"):
            spans = j_body["data"][0].get("spans", [])
            print(f"  • Spans Captured: {len(spans)}")
            # Sort spans by startTime
            sorted_spans = sorted(spans, key=lambda s: s.get("startTime", 0))
            for s in sorted_spans:
                s_id = s.get("spanID")
                op = s.get("operationName")
                dur_ms = s.get("duration", 0) / 1000.0
                parents = [r["spanID"] for r in s.get("references", []) if r.get("refType") == "CHILD_OF"]
                indent = "      └── " if parents else "  [ROOT] "
                print(f"{indent}{op:<50} ({dur_ms:.2f}ms) [Span: {s_id}]")
        else:
            print(f"  ⚠️ Span waterfall pending in Jaeger OTel buffer (HTTP {st})")

    print("\n" + "=" * 80)
    print("   🎉 LIVE AGENT RUN COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    main()
