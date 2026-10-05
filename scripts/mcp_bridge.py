
#!/usr/bin/env python3
"""
scripts/mcp_bridge.py
Stdio-to-HTTP MCP Bridge for Claude Desktop.
Allows Claude Desktop to seamlessly talk to LiteLLM Gateway's OpenAPI MCP endpoints.
Zero external dependencies (pure Python standard library).
"""

import sys
import os
import json
import urllib.request
import urllib.error

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
API_KEY = os.environ.get("LITELLM_API_KEY") or os.environ.get("MCP_BRIDGE_API_KEY")

if not API_KEY:
    sys.stderr.write(
        "[mcp_bridge:error] Missing required API key! "
        "Please set LITELLM_API_KEY (or MCP_BRIDGE_API_KEY) in your environment.\n"
    )
    sys.exit(1)

SERVER_NAME = sys.argv[1] if len(sys.argv) > 1 else None
TARGET_URL = f"{GATEWAY_URL}/{SERVER_NAME}/mcp" if SERVER_NAME else f"{GATEWAY_URL}/mcp"


def log_debug(msg: str):
    sys.stderr.write(f"[mcp_bridge:{SERVER_NAME}] {msg}\n")
    sys.stderr.flush()


def forward_request(raw_json: str):
    try:
        parsed = json.loads(raw_json)
    except Exception as e:
        log_debug(f"JSON parse error: {e}")
        return

    req_id = parsed.get("id")

    req = urllib.request.Request(
        TARGET_URL,
        data=raw_json.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {API_KEY}"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
            if not content.strip():
                return

            lines = content.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("data:"):
                    json_str = line[5:].strip()
                    sys.stdout.write(json_str + "\n")
                    sys.stdout.flush()
                elif line.startswith("{") and line.endswith("}"):
                    sys.stdout.write(line + "\n")
                    sys.stdout.flush()

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        log_debug(f"HTTP Error {e.code}: {err_body}")
        if req_id is not None:
            err_resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": f"Gateway error HTTP {e.code}: {err_body}"
                }
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
    except Exception as e:
        log_debug(f"Connection error: {e}")
        if req_id is not None:
            err_resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": f"Bridge connection error: {str(e)}"
                }
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


def main():
    log_debug(f"Started bridge connecting Claude to {TARGET_URL}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        forward_request(line)


if __name__ == "__main__":
    main()
