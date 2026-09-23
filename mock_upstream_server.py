#!/usr/bin/env python3
"""
mock_upstream_server.py: Minimal zero-cost OpenAI-compatible mock server.
Runs on localhost:8080 and returns synthetic responses instantly.
Supports both non-streaming and basic streaming completions.
"""
import sys
import json
import time
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler

class MockOpenAIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy", "service": "mock_upstream"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            length = int(self.headers.get("Content-Length", 0))
            req_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(req_body)
            except Exception:
                data = {}

            stream = data.get("stream", False)
            model = data.get("model", "mock-model")

            if stream:
                # Basic SSE streaming response
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                chunks = ["Mock ", "completion ", "response: ", "Operation ", "successful."]
                for i, chunk in enumerate(chunks):
                    payload = {
                        "id": f"chatcmpl-mock-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": chunk},
                            "finish_reason": None if i < len(chunks) - 1 else "stop"
                        }]
                    }
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.01)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                response = {
                    "id": f"chatcmpl-mock-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Mock completion response: Operation successful."
                        },
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": 15,
                        "completion_tokens": 8,
                        "total_tokens": 23
                    }
                }
                body = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        sys.stdout.write(f"[mock_upstream] {self.address_string()} - {format%args}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zero-Cost Mock Upstream LLM Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), MockOpenAIHandler)
    print(f"🚀 Mock Upstream LLM Server running on http://{args.host}:{args.port}...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping mock server.")
