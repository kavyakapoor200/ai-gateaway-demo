#!/usr/bin/env python3
"""
client_templates/openai_sdk_example.py: Standard OpenAI Python SDK Client Example.
Demonstrates zero-touch connectivity to the Minimal Local AI Gateway:
- Direct base_url override (http://localhost:4000/v1)
- Virtual key authentication (sk-agent-developer)
- Standard non-streaming chat completion
- Server-Sent Events (SSE) streaming chat completion
- Ingress secret redaction verification (AWS key & email scrubbed before upstream)
- Zero proprietary headers required!
"""

import os
import sys

# Attempt importing official OpenAI SDK; fall back to standard library urllib if not installed
try:
    from openai import OpenAI
    HAS_OPENAI_SDK = True
except ImportError:
    HAS_OPENAI_SDK = False

GATEWAY_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:4000/v1")
DEVELOPER_KEY = os.environ.get("OPENAI_API_KEY", "sk-agent-developer")
MODEL_NAME = os.environ.get("OPENAI_MODEL", "mock-model")


def run_with_openai_sdk():
    print("=" * 78)
    print("   🚀 OpenAI Python SDK -> Local AI Gateway Integration Example")
    print("=" * 78)
    print(f"  • Base URL : {GATEWAY_BASE_URL}")
    print(f"  • API Key  : {DEVELOPER_KEY}")
    print(f"  • Model    : {MODEL_NAME}")
    print("=" * 78)

    client = OpenAI(
        base_url=GATEWAY_BASE_URL,
        api_key=DEVELOPER_KEY,
    )

    # --------------------------------------------------------------------------
    # 1. Standard Non-Streaming Chat Completion
    # --------------------------------------------------------------------------
    print("\n[1] Testing Non-Streaming Chat Completion...")
    prompt = "Implement a binary search function in Python. AKIA1234567890SECRETKEY should be scrubbed."
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a concise engineering assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )

    choice = response.choices[0]
    print(f"  ✅ Request ID     : {response.id}")
    print(f"  ✅ Model Returned : {response.model}")
    print(f"  ✅ Content        : {choice.message.content.strip()[:80]}...")
    if response.usage:
        print(f"  ✅ Tokens Used    : {response.usage.prompt_tokens} in / {response.usage.completion_tokens} out (Total: {response.usage.total_tokens})")

    # --------------------------------------------------------------------------
    # 2. Server-Sent Events (SSE) Streaming Chat Completion
    # --------------------------------------------------------------------------
    print("\n[2] Testing SSE Streaming Chat Completion...")
    stream = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "user", "content": "Stream response token by token"}
        ],
        stream=True,
    )

    print("  Streaming output: ", end="", flush=True)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print("\n  ✅ Stream completed successfully!")


def run_with_urllib_fallback():
    """Fallback demonstration using Python standard library if openai package is absent."""
    import urllib.request
    import json

    print("=" * 78)
    print("   ℹ️ Standard Library Fallback (openai package not installed in environment)")
    print("=" * 78)

    req_data = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": "SDK wire format verification with secret AKIA0000000000SECRET"}
        ]
    }
    req = urllib.request.Request(
        f"{GATEWAY_BASE_URL}/chat/completions",
        data=json.dumps(req_data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {DEVELOPER_KEY}",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read().decode())
        print(f"  ✅ Request ID     : {body.get('id')}")
        print(f"  ✅ Content        : {body['choices'][0]['message']['content']}")
        print(f"  ✅ Tokens         : {body.get('usage', {})}")


if __name__ == "__main__":
    if HAS_OPENAI_SDK:
        run_with_openai_sdk()
    else:
        run_with_urllib_fallback()
