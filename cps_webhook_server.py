#!/usr/bin/env python3
"""
cps_webhook_server.py: Lightweight companion listener for GitHub PR merge webhooks.
Listens on port 4001, resolves task_id from Redis bhash:<sha256>, and updates SQLite gateway.db.
"""
import os
import sys
import json
import hashlib
import sqlite3
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
DB_PATH = os.environ.get("DB_PATH", "gateway.db")
PORT = int(os.environ.get("WEBHOOK_PORT", 4001))

def query_redis_branch(branch_name: str) -> str:
    """Queries Redis directly via socket / RESP protocol for bhash:<sha256>."""
    bhash = hashlib.sha256(branch_name.encode("utf-8")).hexdigest()
    key = f"bhash:{bhash}"
    cmd = f"*2\r\n$3\r\nGET\r\n${len(key)}\r\n{key}\r\n".encode("utf-8")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((REDIS_HOST, REDIS_PORT))
        s.sendall(cmd)
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        lines = resp.split("\r\n")
        if len(lines) >= 2 and lines[0].startswith("$") and int(lines[0][1:]) > 0:
            return lines[1]
    except Exception as e:
        print(f"[!] Redis lookup error: {e}", file=sys.stderr)
    return None

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy", "service": "cps_webhook"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/webhooks/github":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            pr = payload.get("pull_request", {})
            branch = pr.get("head", {}).get("ref", "")
            merged = pr.get("merged", False)
            
            task_id = query_redis_branch(branch) if branch else None
            new_status = "verified_success" if merged else "unmerged_closed"
            
            if task_id:
                try:
                    conn = sqlite3.connect(DB_PATH, timeout=10.0)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("UPDATE gateway_audit_ledger SET task_outcome = ? WHERE task_id = ?", (new_status, task_id))
                    conn.commit()
                    conn.close()
                    print(f"✅ Reconciled task {task_id} -> {new_status} for branch '{branch}'")
                except Exception as e:
                    print(f"[!] SQLite update error: {e}", file=sys.stderr)
            else:
                print(f"⚠️ No active task found in Redis for branch '{branch}'")
            
            response_data = {"status": "ok", "task_id": task_id, "branch": branch, "outcome": new_status}
            body = json.dumps(response_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Clean console output
        sys.stdout.write(f"[cps_webhook] {self.address_string()} - {format%args}\n")

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"🚀 CPS Webhook Companion running on port {PORT}...")
    server.serve_forever()
