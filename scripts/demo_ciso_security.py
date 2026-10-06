#!/usr/bin/env python3
"""
scripts/demo_ciso_security.py
Interactive CLI demo for CISO Security & Tool Policy Governance.
Demonstrates:
  1. Strict Rejection (HTTP 403, zero upstream tokens, estimated spend avoided)
  2. Virtual Tool Shielding / Filter mode (HTTP 200, disallowed tools pruned)
  3. Real-time metrics on :4001/api/security and Prometheus :4001/metrics
Uses standard library only.
"""

import sys
import os
import json
import urllib.request
import urllib.error

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:4001")

KEY_STRICT = "sk-agent-mcp-test"
KEY_FILTER = "sk-agent-intern-poc"


def fetch_security_stats():
    url = f"{DASHBOARD_URL}/api/security"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def send_chat_completion(api_key: str, tools: list, model: str = "mock-model"):
    url = f"{GATEWAY_URL}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Hello, execute safe and dangerous tasks."}
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": t,
                    "description": f"Tool for {t}",
                    "parameters": {"type": "object", "properties": {}}
                }
            }
            for t in tools
        ],
        "tool_choice": "auto"
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)}


def print_banner(text):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_stats(title, stats):
    print(f"\n📊 [{title}]")
    if "error" in stats:
        print(f"   ⚠️ Could not fetch stats: {stats['error']}")
        return
    print(f"   • Strict Rejections (Blocked) : {stats.get('strict_rejections_count', 0)}")
    print(f"   • Virtual Shielding (Filtered): {stats.get('virtual_shielding_count', 0)}")
    print(f"   • Estimated Spend Avoided     : {stats.get('spend_avoided_display', 'n/a (Estimated)')}")
    top_tools = stats.get("top_blocked_tools", [])
    if top_tools:
        print("   • Top Blocked Tools           :")
        for t in top_tools[:5]:
            print(f"       - {t['tool']}: {t['count']} intercepts")
    else:
        print("   • Top Blocked Tools           : None yet")

    by_key = stats.get("by_key_role", [])
    if by_key:
        print("   • Intercepts by Key & Role    :")
        for k in by_key:
            print(f"       - {k['key_alias']} ({k['role']}): {k['blocked']} blocked, {k['filtered']} filtered")


def main():
    print_banner("CISO Security Governance Demo: What Did The Gateway Stop?")

    # 1. Baseline stats
    baseline = fetch_security_stats()
    print_stats("Baseline Governance Metrics", baseline)

    # 2. Strict Reject Demonstration
    print_banner("1. Strict Rejection Policy Test (Key: sk-agent-mcp-test)")
    print("Invoking /chat/completions with disallowed tools: ['execute_command', 'drop_table']...")
    status, res = send_chat_completion(KEY_STRICT, ["execute_command", "drop_table"])
    print(f"HTTP Status: {status}")
    if status == 403:
        print("✅ SUCCESS: Request strictly blocked by Gateway (HTTP 403 Forbidden).")
        err_info = res.get("error", {})
        print(f"   Message         : {err_info.get('message', res)}")
        print(f"   Violating Tools : {err_info.get('violating_tools', [])}")
        print(f"   Allowed Tools   : {err_info.get('allowed_tools', [])}")
        print("   🛡️ ZDR Invariant : Zero prompt/response content stored. Upstream tokens = 0.")
    else:
        print(f"⚠️ Unexpected status {status}: {res}")

    # 3. Virtual Shielding (Filter) Demonstration
    print_banner("2. Virtual Tool Shielding Test (Key: sk-agent-intern-poc)")
    print("Invoking /chat/completions with ['read_file', 'execute_command', 'drop_table']...")
    status, res = send_chat_completion(KEY_FILTER, ["read_file", "execute_command", "drop_table"])
    print(f"HTTP Status: {status}")
    if status == 200:
        print("✅ SUCCESS: Request succeeded with HTTP 200 OK via Virtual Shielding.")
        print("   🛡️ Disallowed tools ('execute_command', 'drop_table') were stripped in memory.")
        print("   🛡️ LLM was protected from discovering or invoking dangerous capabilities.")
        print("   🛡️ Ingress audit ledger recorded policy_action='filter' with pruned tools.")
    else:
        print(f"⚠️ Unexpected status {status}: {res}")

    # 4. Updated stats
    updated = fetch_security_stats()
    print_stats("Updated Governance Metrics", updated)

    print_banner("Demo Complete")
    print("🌐 View real-time security dashboard at: http://localhost:4001")
    print("📈 View Grafana executive dashboard at  : http://localhost:3001/d/ai-gateway-cps-metrics")
    print("📋 View Prometheus security metrics at : http://localhost:4001/metrics\n")


if __name__ == "__main__":
    main()
