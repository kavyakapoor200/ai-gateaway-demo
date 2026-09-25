#!/usr/bin/env python3
"""
mock_local_pr.py: Simulates GitHub PR lifecycle locally and fires webhook to AI Gateway.
Zero manual headers required: Matches via SHA-256 hashed branch name index in Redis.
"""
import sys
import subprocess
import argparse
import urllib.request
import os
import json

GATEWAY_WEBHOOK_URL = os.environ.get("GATEWAY_WEBHOOK_URL", "http://localhost:4001/webhooks/github")

def run_cmd(cmd):
    """Executes shell command with stdout capture."""
    return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout.strip()

def open_pr(branch_name, simulate_only=False):
    """Simulates or executes git checkout -b."""
    if not simulate_only:
        try:
            run_cmd(f"git checkout -b {branch_name}")
            print(f"✅ Created and checked out local PR branch: '{branch_name}'")
            return
        except Exception as e:
            print(f"ℹ️ Git branch checkout notice: {e} (Falling back to simulation mode)")
    print(f"✅ [Simulation] Simulated branch creation: '{branch_name}'")

def merge_pr(branch_name, simulate_only=False):
    """Simulates or executes git merge and sends GitHub merge webhook."""
    commit_sha = "d4e2f81a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e"
    if not simulate_only:
        try:
            run_cmd("git checkout main")
            run_cmd(f"git merge --no-ff {branch_name} -m 'Merge local PR branch: {branch_name}'")
            commit_sha = run_cmd("git rev-parse HEAD")
            print(f"✅ Merged '{branch_name}' into main (Commit: {commit_sha[:8]})")
        except Exception as e:
            print(f"ℹ️ Git merge notice: {e} (Proceeding with simulated webhook payload)")

    payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "head": {"ref": branch_name},
            "merge_commit_sha": commit_sha
        }
    }
    _send_webhook(payload)

def reject_pr(branch_name, simulate_only=False):
    """Simulates or executes git branch deletion and sends GitHub rejection webhook."""
    if not simulate_only:
        try:
            run_cmd("git checkout main")
            run_cmd(f"git branch -D {branch_name}")
            print(f"❌ Rejected local PR. Deleted branch: '{branch_name}'")
        except Exception as e:
            print(f"ℹ️ Git rejection notice: {e} (Proceeding with simulated webhook payload)")

    payload = {
        "action": "closed",
        "pull_request": {
            "merged": False,
            "head": {"ref": branch_name}
        }
    }
    _send_webhook(payload)

def _send_webhook(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY_WEBHOOK_URL, 
        data=data, 
        headers={"Content-Type": "application/json", "User-Agent": "GitHub-Hookshot/mock"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            print(f"🚀 Dispatched Webhook to CPS Service (HTTP {resp.status}) -> Response: {body}")
    except Exception as e:
        print(f"⚠️ Webhook dispatch error: {e} (Ensure CPS webhook service is running on port 4001)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock GitHub PR Lifecycle Locally")
    parser.add_argument("--simulate", action="store_true", help="Simulate webhook payload without modifying local git workspace")
    subparsers = parser.add_subparsers(dest="command")
    
    p_open = subparsers.add_parser("open", help="Open a local PR branch")
    p_open.add_argument("--branch", required=True, help="e.g. feat/db-timeout")
    p_open.add_argument("--simulate", action="store_true", help="Simulate without git command")
    
    p_merge = subparsers.add_parser("merge", help="Merge local PR branch and fire webhook")
    p_merge.add_argument("--branch", required=True)
    p_merge.add_argument("--simulate", action="store_true", help="Simulate without git command")
    
    p_reject = subparsers.add_parser("reject", help="Reject local PR branch and fire webhook")
    p_reject.add_argument("--branch", required=True)
    p_reject.add_argument("--simulate", action="store_true", help="Simulate without git command")
    
    args = parser.parse_args()
    sim = args.simulate if hasattr(args, "simulate") and args.simulate else False

    if args.command == "open":
        open_pr(args.branch, simulate_only=sim or args.simulate)
    elif args.command == "merge":
        merge_pr(args.branch, simulate_only=sim or args.simulate)
    elif args.command == "reject":
        reject_pr(args.branch, simulate_only=sim or args.simulate)
    else:
        parser.print_help()
