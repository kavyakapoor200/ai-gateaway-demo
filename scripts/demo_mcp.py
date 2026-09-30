#!/usr/bin/env python3
"""
scripts/demo_mcp.py
Interactive CLI demo to test LiteLLM MCP Tools (GitHub & Resend) live against the local gateway.
Uses Python standard library only (no external pip dependencies needed).
"""

import sys
import os
import json
import urllib.request
import urllib.error

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-enterprise-master-secret-key-2026")


def rpc_call(endpoint: str, method: str, params: dict = None) -> dict:
    url = f"{GATEWAY_URL}/{endpoint}/mcp"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {MASTER_KEY}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            # Handle potential SSE event: message format
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            for line in lines:
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        return {"error": f"HTTP {e.code}: {err_msg}"}
    except Exception as e:
        return {"error": str(e)}


def list_tools(server_name: str):
    print(f"\n📡 Querying MCP Server: {server_name}...")
    res = rpc_call(server_name, "tools/list")
    if "error" in res:
        print(f"❌ Error: {res['error']}")
        return
    tools = res.get("result", {}).get("tools", [])
    print(f"✅ Found {len(tools)} tools exposed by Gateway:")
    for t in tools:
        print(f"   🔹 {t['name']}: {t.get('description', '')}")


def get_github_repo(owner="octocat", repo="Hello-World"):
    print(f"\n🐙 Calling GitHub Tool: github_mcp-repos_get ({owner}/{repo})...")
    res = rpc_call("github_mcp", "tools/call", {
        "name": "github_mcp-repos_get",
        "arguments": {"owner": owner, "repo": repo}
    })
    if "error" in res:
        print(f"❌ Error: {res['error']}")
        return
    content = res.get("result", {}).get("content", [])
    if content and content[0].get("text"):
        try:
            data = json.loads(content[0]["text"])
            print("✅ Successfully fetched from GitHub via Gateway!")
            print(f"   • Full Name:    {data.get('full_name')}")
            print(f"   • Description:  {data.get('description')}")
            print(f"   • Stars:        {data.get('stargazers_count')} ⭐")
            print(f"   • Open Issues:  {data.get('open_issues_count')}")
            print(f"   • Default Repo: {data.get('default_branch')}")
        except Exception:
            print("Response:", content[0]["text"][:300])
    else:
        print("Raw response:", res)


def get_github_issues(owner="octocat", repo="Hello-World"):
    print(f"\n📋 Calling GitHub Tool: github_mcp-issues_list_for_repo ({owner}/{repo})...")
    res = rpc_call("github_mcp", "tools/call", {
        "name": "github_mcp-issues_list_for_repo",
        "arguments": {"owner": owner, "repo": repo, "per_page": 3}
    })
    if "error" in res:
        print(f"❌ Error: {res['error']}")
        return
    content = res.get("result", {}).get("content", [])
    if content and content[0].get("text"):
        try:
            issues = json.loads(content[0]["text"])
            if isinstance(issues, list):
                print(f"✅ Found {len(issues)} recent issues:")
                for iss in issues:
                    print(f"   • #{iss.get('number')}: {iss.get('title')} [{iss.get('state')}]")
            else:
                print("Response:", issues)
        except Exception:
            print("Response:", content[0]["text"][:300])
    else:
        print("Raw response:", res)


def show_dashboards():
    print("\n🌐 Web Dashboards available on your local system:")
    print("   1. LiteLLM Admin & Playground UI:  http://localhost:4000/ui")
    print(f"      Key: {MASTER_KEY}")
    print("   2. CPS & Observability Dashboard:  http://localhost:4001")
    print("   3. Jaeger Distributed Traces:      http://localhost:16687")
    print("   4. Grafana Metrics Dashboard:      http://localhost:3001 (admin/admin)")


def interactive_menu():
    while True:
        print("\n" + "=" * 60)
        print("🚀 AI GATEWAY - MCP LIVE TEST CONSOLE")
        print("=" * 60)
        print("1. List All Exposed MCP Tools (GitHub & Resend)")
        print("2. Fetch Live GitHub Repository Details")
        print("3. Fetch Live GitHub Issues")
        print("4. Show Web Dashboard Links (Browser UIs)")
        print("5. Exit")
        choice = input("\nEnter choice [1-5]: ").strip()

        if choice == "1":
            list_tools("github_mcp")
            list_tools("resend_mcp")
        elif choice == "2":
            owner = input("Enter GitHub owner [default: octocat]: ").strip() or "octocat"
            repo = input("Enter GitHub repo [default: Hello-World]: ").strip() or "Hello-World"
            get_github_repo(owner, repo)
        elif choice == "3":
            owner = input("Enter GitHub owner [default: octocat]: ").strip() or "octocat"
            repo = input("Enter GitHub repo [default: Hello-World]: ").strip() or "Hello-World"
            get_github_issues(owner, repo)
        elif choice == "4":
            show_dashboards()
        elif choice == "5":
            print("\nExiting. Happy coding!\n")
            break
        else:
            print("Invalid option. Please choose 1-5.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        list_tools("github_mcp")
        list_tools("resend_mcp")
        get_github_repo()
        get_github_issues()
        show_dashboards()
    else:
        interactive_menu()
