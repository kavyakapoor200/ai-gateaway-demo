#!/usr/bin/env python3
"""
scripts/fastmcp_ops_server.py
FastMCP Server auto-generated from OpenAPI specification (engineering_ops_openapi.json).
Connects to an in-memory/local mock Engineering Ops backend, exposing all tools
over SSE on port 8005 so LiteLLM Gateway proxies them with centralized auth & audit.
"""

import os
import sys
import json
import threading
import httpx2
import uvicorn
from pathlib import Path
from fastmcp import FastMCP

# Import mock Engineering Ops ASGI application
sys.path.insert(0, str(Path(__file__).parent))
from mock_ops_service import app as mock_ops_app

SPEC_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "specs", "engineering_ops_openapi.json")

def start_mock_api(port=8089):
    """Run mock backend API on port 8089 in background for external callers."""
    config = uvicorn.Config(mock_ops_app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()

def create_server():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    # Use ASGITransport to route HTTP requests directly to the mock backend in-memory
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=mock_ops_app),
        base_url="https://ops.example.internal/api/v1"
    )

    server = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="FastMCP-EngineeringOps"
    )
    return server

if __name__ == "__main__":
    mcp_port = int(os.environ.get("FASTMCP_PORT", 8005))
    mock_port = int(os.environ.get("MOCK_OPS_PORT", 8089))

    # Start mock REST API on 8089 in background thread
    t = threading.Thread(target=start_mock_api, args=(mock_port,), daemon=True)
    t.start()
    print(f"[*] Started mock Engineering Ops REST backend on http://0.0.0.0:{mock_port}/api/v1")

    # Start FastMCP server on 8005
    server = create_server()
    print(f"[*] Starting FastMCP OpenAPI server on http://0.0.0.0:{mcp_port}/sse ...")
    server.run(transport="sse", host="0.0.0.0", port=mcp_port)
