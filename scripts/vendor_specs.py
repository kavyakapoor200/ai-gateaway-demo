#!/usr/bin/env python3
"""
Reproducible script to vendor and sanitize OpenAPI specs for LiteLLM MCP:
1. Slices GitHub API spec down to repos and issues endpoints, renaming operationIds with underscores.
2. Downloads Resend API spec and sanitizes operationIds (slash-to-underscore).
Saves output to config/specs/
"""

import json
import os
import sys
import httpx

CONFIG_SPECS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "specs"))
os.makedirs(CONFIG_SPECS_DIR, exist_ok=True)

GITHUB_SPEC_URL = "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json"
RESEND_SPEC_URL = "https://raw.githubusercontent.com/resend/resend-openapi/main/resend.json"


def sanitize_id(op_id: str) -> str:
    return op_id.replace("/", "_").replace("-", "_")


def vendor_github():
    print("Fetching GitHub OpenAPI spec...")
    resp = httpx.get(GITHUB_SPEC_URL, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    target_paths = {
        "/repos/{owner}/{repo}": ["get"],
        "/repos/{owner}/{repo}/issues": ["get", "post"],
        "/repos/{owner}/{repo}/issues/{issue_number}": ["get"]
    }

    trimmed_paths = {}
    for path, methods in target_paths.items():
        if path in raw.get("paths", {}):
            trimmed_paths[path] = {}
            for method in methods:
                if method in raw["paths"][path]:
                    op_defn = raw["paths"][path][method]
                    original_op_id = op_defn.get("operationId", "")
                    if original_op_id:
                        op_defn["operationId"] = sanitize_id(original_op_id)
                    trimmed_paths[path][method] = op_defn

    clean_spec = {
        "openapi": raw.get("openapi", "3.0.3"),
        "info": {
            "title": "GitHub REST API (Curated for MCP)",
            "version": raw.get("info", {}).get("version", "1.1.4"),
            "description": "Curated subset of GitHub REST API for issues and repo operations with sanitized operationIds."
        },
        "servers": raw.get("servers", [{"url": "https://api.github.com"}]),
        "paths": trimmed_paths,
        "components": raw.get("components", {})
    }

    out_file = os.path.join(CONFIG_SPECS_DIR, "github_openapi.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(clean_spec, f, indent=2)

    print(f"Vendored GitHub spec to {out_file} (size: {os.path.getsize(out_file)} bytes)")


def vendor_resend():
    print("Fetching Resend OpenAPI spec...")
    resp = httpx.get(RESEND_SPEC_URL, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    # Sanitize operationId across all paths
    for path, methods in raw.get("paths", {}).items():
        if isinstance(methods, dict):
            for method, op in methods.items():
                if isinstance(op, dict) and "operationId" in op:
                    op["operationId"] = sanitize_id(op["operationId"])

    out_file = os.path.join(CONFIG_SPECS_DIR, "resend_openapi.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)

    print(f"Vendored Resend spec to {out_file} (size: {os.path.getsize(out_file)} bytes)")


if __name__ == "__main__":
    vendor_github()
    vendor_resend()
    print("Vendoring complete.")
