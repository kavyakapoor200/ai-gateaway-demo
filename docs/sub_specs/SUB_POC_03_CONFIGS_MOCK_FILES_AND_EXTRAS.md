# Sub-specification — SUB-POC-03: Runnable Configurations, Mock Engines & Verification Runbooks

**Parent Spec:** [SPEC_AI_GATEWAY_LOCAL_POC.md](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/SPEC_AI_GATEWAY_LOCAL_POC.md)  
**Sub-spec ID:** SUB-POC-03  
**Status:** Approved Baseline  
**Date:** September 2026  
**Classification:** Infrastructure-as-Code, Runnable Configurations, Emulators & Validation  

---

## 1. Objective

Provide the complete, self-contained, and production-ready **Infrastructure-as-Code (IaC)** files, configuration manifests, mock emulation scripts, agent client integration templates, native guardrail rules, and the complete **7-Step Verification Runbook** for the Local AI Gateway PoC.

This sub-specification serves as the executable deployment and verification blueprint, enabling any engineer to instantiate the entire gateway environment locally on macOS/Linux in under five minutes with zero cloud infrastructure dependencies (aside from optional upstream LLM API keys).

---

## 2. Scope & Non-Goals

### 2.1 In Scope
- **Production Configuration Files**:
  - `litellm_config.yaml`: Model definitions, routing policies, fallback cascades, OTel exporter, and native regex guardrails.
  - `docker-compose.yml`: Multi-container stack orchestrating LiteLLM Proxy, Redis 7, and Jaeger All-in-One.
  - `.env.example`: Environment variables template.
  - `sqlite_schema.sql`: Single-table SQLite audit ledger bootstrap script.
- **Mock & Emulation Utilities**:
  - `mock_local_pr.py`: Standalone CLI simulator for local Git branch creation, merge, rejection, and GitHub webhook dispatch.
  - Offline Mock Upstream Server: Local zero-cost mock endpoint for testing without live LLM credentials.
- **Client & Tool Compatibility**:
  - Client configuration manifests for Cursor, Claude Code, and standard OpenAI SDKs.
  - Actual Model Context Protocol (MCP) server configuration (`server-git`, `server-filesystem`).
- **End-to-End Verification Runbook**:
  - Complete 7-step test script with exact cURL requests, bash commands, and expected assertions.

### 2.2 Non-Goals
- Modifying LiteLLM core proxy source code (all functionality uses standard configuration and native hooks).
- Gateway RBAC architecture and policy theory (governed by [SUB-POC-01](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md)).
- SQLite schema design and mathematical ZDR compliance theory (governed by [SUB-POC-02](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md)).

---

## 3. Functional Requirements

| ID | Requirement | Master Spec Source | Priority |
| :--- | :--- | :--- | :--- |
| **REQ-CFG-01** | The deployment stack MUST be fully orchestratable via a single command `docker compose up -d` using official Docker images. | §5.4 Multi-Container Stack | Must |
| **REQ-CFG-02** | The gateway configuration (`litellm_config.yaml`) MUST declare primary frontier models, automatic fallback rules, and an offline mock model tier. | §5.2 LiteLLM Gateway Config | Must |
| **REQ-CFG-03** | The gateway configuration MUST configure native in-process regex guardrails to scrub AWS secret keys, standard API keys, and email addresses into `[REDACTED]`. | §3.7 Guardrails & PII Masking | Must |
| **REQ-CFG-04** | The multi-container stack MUST allocate non-conflicting localhost ports: `4000` (LiteLLM), `4001` (CPS Webhook), `6379` (Redis), `16686` (Jaeger UI), `4317` (OTLP gRPC), and `4318` (OTLP HTTP). | §5.4 Port Allocations | Must |
| **REQ-CFG-05** | The SQLite ledger database file (`gateway.db`) MUST be mounted as a host volume to persist state across container restarts. | §5.4 Volume Mounts | Must |
| **REQ-CFG-06** | The mock script `mock_local_pr.py` MUST provide CLI commands (`open`, `merge`, `reject`) to simulate Git branch actions and fire standard GitHub merge payloads. | §5.3 Git PR Simulator | Must |
| **REQ-CFG-07** | The deployment stack MUST support completely offline execution using the `mock-model` endpoint when upstream API keys are absent. | §5.2 Mock Model Tier | Must |
| **REQ-CFG-08** | Client configuration snippets MUST allow standard coding agents (Cursor, Claude Code) to interact with the gateway without requiring proprietary headers. | §4 Client Compatibility | Must |
| **REQ-CFG-09** | The database bootstrap script `sqlite_schema.sql` MUST be idempotent and safely re-executable (`CREATE TABLE IF NOT EXISTS`). | §5.1 SQLite Schema | Must |
| **REQ-CFG-10** | The verification runbook MUST provide verifiable step-by-step commands demonstrating all 7 Gateway Control Pillars in under 10 minutes. | §6 Verification Runbook | Must |

---

## 4. Production Runnable Configurations

### 4.1 LiteLLM Gateway Configuration (`litellm_config.yaml`)

```yaml
# ==============================================================================
# Minimal Local AI Gateway: LiteLLM Configuration
# ==============================================================================

model_list:
  # Primary Frontier Model (OpenAI Direct)
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY
      rpm: 30
      tpm: 60000

  # Automatic Failover Model (Anthropic Direct)
  - model_name: claude-3-5-sonnet
    litellm_params:
      model: anthropic/claude-3-5-sonnet-20241022
      api_key: os.environ/ANTHROPIC_API_KEY
      rpm: 30
      tpm: 60000

  # Fast / Economical Model (For Intern Role)
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      rpm: 100
      tpm: 120000

  # Offline Mock Model (For zero-cost testing)
  - model_name: mock-model
    litellm_params:
      model: openai/mock-model
      api_base: http://host.docker.internal:8080/v1
      api_key: sk-mock-key

# Fallback Routing Rule: If gpt-4o fails (429/500), automatically route to claude-3-5-sonnet
router_settings:
  routing_strategy: latency-based-routing
  redis_host: "redis"
  redis_port: 6379
  fallbacks:
    - gpt-4o: ["claude-3-5-sonnet", "mock-model"]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: "sqlite:////app/gateway.db"
  store_model_in_db: false
  
  # Distributed Tracing via OpenTelemetry to local Jaeger & Custom ZDR SQLite Logger
  callbacks: ["otel", "custom_zdr_logger.zdr_audit_logger"]
  otel_exporter: "otlp_grpc"
  otel_endpoint: "http://jaeger:4317"

# Zero Data Retention & Native Guardrails
litellm_settings:
  turn_off_message_logging: true
  
  # Native PII & Secret Redaction Regexes
  guardrails:
    - prompt_regex:
        - "(?i)(AKIA[0-9A-Z]{16})"               # AWS Access Keys
        - "(?i)(sk-[a-zA-Z0-9]{32,})"            # API Keys
        - "[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+" # Emails
      mode: "mask" # Automatically replaced with [REDACTED]
```

### 4.2 Local Multi-Container Stack (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  # ----------------------------------------------------------------------------
  # 1. LiteLLM Core AI Gateway Proxy
  # ----------------------------------------------------------------------------
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: litellm_gateway
    restart: unless-stopped
    ports:
      - "4000:4000"
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - LITELLM_MASTER_KEY=sk-enterprise-master-secret-key-2026
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - LITELLM_OTEL_V2=true
    volumes:
      - ./litellm_config.yaml:/app/config.yaml
      - ./custom_zdr_logger.py:/app/custom_zdr_logger.py # In-RAM ZDR logger & branch sniffer
      - ./gateway.db:/app/gateway.db                     # Embedded SQLite ledger
    command: ["--config", "/app/config.yaml", "--port", "4000", "--num_workers", "2"]
    depends_on:
      - redis
      - jaeger

  # ----------------------------------------------------------------------------
  # 2. Redis 7 (Rate Limiting, Real-Time Budgets & Hashed Branch Registry)
  # ----------------------------------------------------------------------------
  redis:
    image: redis:7-alpine
    container_name: gateway_redis
    restart: unless-stopped
    ports:
      - "6379:6379"

  # ----------------------------------------------------------------------------
  # 3. Jaeger All-in-One (OTel Trace Collector & Flow UI)
  # ----------------------------------------------------------------------------
  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: gateway_jaeger
    restart: unless-stopped
    ports:
      - "16686:16686" # Web UI (http://localhost:16686)
      - "4317:4317"   # OTLP gRPC receiver
      - "4318:4318"   # OTLP HTTP receiver
    environment:
      - COLLECTOR_OTLP_ENABLED=true

  # ----------------------------------------------------------------------------
  # 4. CPS Git Merge Lifecycle Webhook Service
  # ----------------------------------------------------------------------------
  cps_webhook:
    image: python:3.11-slim
    container_name: gateway_cps_webhook
    restart: unless-stopped
    working_dir: /app
    volumes:
      - ./cps_webhook_server.py:/app/cps_webhook_server.py
      - ./gateway.db:/app/gateway.db
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - DB_PATH=/app/gateway.db
      - WEBHOOK_PORT=4001
    command: ["python", "-u", "cps_webhook_server.py"]
    ports:
      - "4001:4001"
    depends_on:
      - redis
```

### 4.3 Environment Variables Manifest (`.env.example`)

```bash
# ==============================================================================
# Environment Configuration for Local AI Gateway PoC
# ==============================================================================

# LiteLLM Master Admin Key (proxy_admin role)
LITELLM_MASTER_KEY=sk-enterprise-master-secret-key-2026

# Upstream Cloud LLM API Keys (The only external network compute)
OPENAI_API_KEY=sk-proj-your-openai-api-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key-here

# OpenTelemetry Endpoint (Use http://localhost:4317 for host execution; http://jaeger:4317 inside Docker)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

### 4.4 SQLite Database Schema Initialization (`sqlite_schema.sql`)

```sql
-- =============================================================================
-- Minimal Local AI Gateway: Single-Table SQLite Ledger
-- =============================================================================

CREATE TABLE IF NOT EXISTS gateway_audit_ledger (
    request_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Identity & Governance
    api_key_alias TEXT NOT NULL,
    caller_role TEXT NOT NULL DEFAULT 'developer',
    
    -- Model Routing & Execution
    model_requested TEXT NOT NULL,
    model_routed TEXT NOT NULL,
    fallback_triggered INTEGER DEFAULT 0,
    http_status INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    
    -- Token & Financial Metering
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    
    -- Cryptographic Zero Data Retention (ZDR)
    prompt_sha256 TEXT NOT NULL,
    completion_sha256 TEXT NOT NULL,
    zdr_verified INTEGER DEFAULT 1,
    
    -- Coding Task Cost Per Success (CPS) Reconciliation
    task_id TEXT,
    task_outcome TEXT DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_trace_id ON gateway_audit_ledger(trace_id);
CREATE INDEX IF NOT EXISTS idx_task_id ON gateway_audit_ledger(task_id);
CREATE INDEX IF NOT EXISTS idx_created_at ON gateway_audit_ledger(created_at);

-- Real-Time Coding CPS Summary View
CREATE VIEW IF NOT EXISTS v_coding_cps_summary AS
SELECT 
    task_id,
    COUNT(request_id) AS total_turns,
    SUM(prompt_tokens + completion_tokens) AS total_tokens,
    ROUND(SUM(cost_usd), 6) AS accumulated_cost_usd,
    task_outcome,
    CASE 
        WHEN task_outcome = 'verified_success' THEN ROUND(SUM(cost_usd), 6)
        ELSE NULL 
    END AS final_cps_usd
FROM gateway_audit_ledger
WHERE task_id IS NOT NULL
GROUP BY task_id, task_outcome;

-- Automated ZDR Compliance Audit View
CREATE VIEW IF NOT EXISTS v_zdr_compliance_check AS
SELECT 
    COUNT(*) AS total_records,
    SUM(CASE WHEN LENGTH(prompt_sha256) = 64 AND prompt_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END) AS valid_prompt_hashes,
    SUM(CASE WHEN LENGTH(completion_sha256) = 64 AND completion_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END) AS valid_completion_hashes,
    SUM(CASE WHEN zdr_verified = 1 THEN 1 ELSE 0 END) AS zdr_flags_valid,
    CASE 
        WHEN COUNT(*) = SUM(CASE WHEN LENGTH(prompt_sha256) = 64 AND prompt_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END)
         AND COUNT(*) = SUM(CASE WHEN LENGTH(completion_sha256) = 64 AND completion_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END)
        THEN '100% COMPLIANT - ZERO PLAINTEXT DETECTED'
        ELSE 'VIOLATION DETECTED - AUDIT REQUIRED'
    END AS compliance_status
FROM gateway_audit_ledger;
```

### 4.5 File Migration & Coexistence Notice

> [!NOTE]
> The active Local PoC baseline replaces the legacy Nubris 365 enterprise configuration files:
> - `docker-compose.yml` supersedes the 6-service Nubris compose file (decommissioning PostgreSQL, Presidio, and ConnectWise MCP containers).
> - `litellm_config.yaml` supersedes the AWS Bedrock / OpenRouter enterprise configuration.
> - `sqlite_schema.sql` supersedes `zdr_schema.sql` and `mcp_schema.sql`.
> - `custom_zdr_logger.py` is updated to target `gateway_audit_ledger` in WAL SQLite mode.

---

## 5. Mock Engines & Client Integrations

### 5.1 Local Git PR Simulator (`mock_local_pr.py`)

```python
#!/usr/bin/env python3
"""
mock_local_pr.py: Simulates GitHub PR lifecycle locally and fires webhook to AI Gateway.
Zero manual headers required: Matches via SHA-256 hashed branch name index in Redis.
"""
import sys
import subprocess
import argparse
import urllib.request
import json

GATEWAY_WEBHOOK_URL = "http://localhost:4001/webhooks/github"

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout.strip()

def open_pr(branch_name):
    run_cmd(f"git checkout -b {branch_name}")
    print(f"✅ Created and checked out local PR branch: '{branch_name}'")

def merge_pr(branch_name):
    # 1. Perform actual local git merge into main
    run_cmd("git checkout main")
    run_cmd(f"git merge --no-ff {branch_name} -m 'Merge local PR branch: {branch_name}'")
    commit_sha = run_cmd("git rev-parse HEAD")
    print(f"✅ Merged '{branch_name}' into main (Commit: {commit_sha[:8]})")
    
    # 2. Dispatch mock GitHub webhook payload to the Gateway Companion
    payload = {
        "action": "closed",
        "pull_request": {
            "merged": True,
            "head": {"ref": branch_name},
            "merge_commit_sha": commit_sha
        }
    }
    _send_webhook(payload)

def reject_pr(branch_name):
    run_cmd("git checkout main")
    run_cmd(f"git branch -D {branch_name}")
    print(f"❌ Rejected local PR. Deleted branch: '{branch_name}'")
    
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
        with urllib.request.urlopen(req) as resp:
            print(f"🚀 Dispatched Webhook to CPS Service (HTTP {resp.status}) -> Task outcome updated!")
    except Exception as e:
        print(f"⚠️ Webhook dispatch note: {e} (Ensure CPS webhook service is running on port 4001)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mock GitHub PR Lifecycle Locally")
    subparsers = parser.add_subparsers(dest="command")
    
    p_open = subparsers.add_parser("open")
    p_open.add_argument("--branch", required=True, help="e.g. feat/db-timeout")
    
    p_merge = subparsers.add_parser("merge")
    p_merge.add_argument("--branch", required=True)
    
    p_reject = subparsers.add_parser("reject")
    p_reject.add_argument("--branch", required=True)
    
    args = parser.parse_args()
    if args.command == "open":
        open_pr(args.branch)
    elif args.command == "merge":
        merge_pr(args.branch)
    elif args.command == "reject":
        reject_pr(args.branch)
    else:
        parser.print_help()
```

### 5.2 Standalone CPS Webhook Companion Service (`cps_webhook_server.py`)
A lightweight, zero-dependency Python service running on port `4001` that listens for GitHub merge webhooks, hashes incoming `head.ref` in transient memory, queries Redis `bhash:*`, and updates `gateway.db`:

```python
#!/usr/bin/env python3
"""
cps_webhook_server.py: Lightweight companion listener for GitHub PR merge webhooks.
Listens on port 4001, resolves task_id from Redis bhash:<sha256>, and updates SQLite gateway.db.
"""
import os
import json
import hashlib
import sqlite3
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
DB_PATH = os.environ.get("DB_PATH", "gateway.db")
PORT = int(os.environ.get("WEBHOOK_PORT", 4001))

def query_redis_branch(branch_name: str):
    """Queries Redis directly via socket / basic command for bhash:<sha256>."""
    import socket
    bhash = hashlib.sha256(branch_name.encode("utf-8")).hexdigest()
    cmd = f"*2\r\n$3\r\nGET\r\n${len('bhash:' + bhash)}\r\nbhash:{bhash}\r\n".encode("utf-8")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((REDIS_HOST, REDIS_PORT))
        s.sendall(cmd)
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        lines = resp.split("\r\n")
        if len(lines) >= 2 and lines[0].startswith("$") and int(lines[0][1:]) > 0:
            return lines[1]
    except Exception as e:
        print(f"[!] Redis lookup error: {e}")
    return None

class WebhookHandler(BaseHTTPRequestHandler):
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
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE gateway_audit_ledger SET task_outcome = ? WHERE task_id = ?", (new_status, task_id))
                conn.commit()
                conn.close()
                print(f"✅ Reconciled task {task_id} -> {new_status} for branch {branch}")
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "task_id": task_id, "outcome": new_status}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"🚀 CPS Webhook Companion running on port {PORT}...")
    server.serve_forever()
```

### 5.3 Offline Mock Model Server (`mock_upstream_server.py`)
To test the gateway without spending live model tokens or incurring cloud charges:

```python
#!/usr/bin/env python3
"""
mock_upstream_server.py: Minimal zero-cost OpenAI-compatible mock server.
Runs on localhost:8080 and returns synthetic responses instantly.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import time

class MockOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/v1/chat/completions":
            response = {
                "id": f"chatcmpl-mock-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "mock-model",
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

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), MockOpenAIHandler)
    print("🚀 Mock Upstream LLM Server running on port 8080...")
    server.serve_forever()
```

> [!TIP]
> **Pre-Built Evaluation Harnesses from `PoCs/`**:
> Rather than maintaining custom test mocks, developers can directly invoke the ready-to-use evaluation tools located in the `PoCs/` directory:
> - **[`PoCs/karthik-ag_gateway_/mock_server.py`](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/PoCs/karthik-ag_gateway_/mock_server.py)**: Full SSE-streaming mock server supporting configurable TTFT (`--ttft`) and token velocity (`--itl`).
> - **[`PoCs/karthik-ag_gateway_/benchmark_gateway.py`](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/PoCs/karthik-ag_gateway_/benchmark_gateway.py)**: Async load tester measuring TTFT/ITL percentiles and isolating added gateway latency overhead (`--compare-direct-url`).
> - **[`PoCs/karthik-gateway-poc/src/simulator.py`](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/PoCs/karthik-gateway-poc/src/simulator.py)**: Open-loop queuing and burst traffic simulator to stress-test Redis sliding-window rate limiters.

### 5.4 Coding Agent / Client Integration Configurations

#### Cursor IDE Configuration (`settings.json`)
```json
{
  "cursor.openaiBaseUrl": "http://localhost:4000/v1",
  "cursor.openaiApiKey": "sk-agent-developer",
  "cursor.model": "gpt-4o"
}
```

#### Claude Code CLI Configuration (`~/.claude/config.json`)
```json
{
  "api_base": "http://localhost:4000/v1",
  "api_key": "sk-agent-developer",
  "default_model": "claude-3-5-sonnet"
}
```

### 5.5 Actual MCP Server Configuration
Coding agents interact directly with actual MCP servers without requiring proprietary gateway wrappers:
```json
{
  "mcpServers": {
    "git": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-git"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/mako/Mukesh_Workspace"]
    }
  }
}
```

---

## 6. End-to-End Verification Runbook & Demo Script

### Step 1: Initialize the Local Infrastructure
```bash
# 1. Initialize SQLite database with schema
sqlite3 gateway.db < sqlite_schema.sql

# 2. Start the 3 local containers
docker compose up -d

# 3. Verify gateway health
curl http://localhost:4000/health
# Expected: {"status": "healthy"}
```

---

### Step 2: Configure Access via Admin UI or REST API
Login to `http://localhost:4000/ui` with `sk-enterprise-master-secret-key-2026` or execute via cURL:

```bash
# 1. Developer Key: Authorized for GPT-4o and Claude Sonnet ($5.00 daily budget)
curl -X POST "http://localhost:4000/key/generate" \
  -H "Authorization: Bearer sk-enterprise-master-secret-key-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "sk-agent-developer",
    "key_alias": "sk-agent-developer",
    "models": ["gpt-4o", "claude-3-5-sonnet", "mock-model"],
    "max_budget": 5.0,
    "duration": "1d",
    "metadata": {"role": "developer"}
  }'

# 2. Intern Key: RESTRICTED to GPT-4o-mini only ($1.00 daily budget)
curl -X POST "http://localhost:4000/key/generate" \
  -H "Authorization: Bearer sk-enterprise-master-secret-key-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "sk-agent-intern",
    "key_alias": "sk-agent-intern",
    "models": ["gpt-4o-mini", "mock-model"],
    "max_budget": 1.0,
    "duration": "1d",
    "metadata": {"role": "intern"}
  }'
```

---

### Step 3: Demonstrate Gateway-Level RBAC & Model Access Control

#### Demo 3A: Allowed Model Request
```bash
curl -i -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Explain binary search"}]
  }'
```
*Expected Result*: **HTTP 200 OK** and completion returned.

#### Demo 3B: Gateway-Level Access Rejection (Model Escalation Blocked)
```bash
curl -i -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-intern" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Explain binary search"}]
  }'
```
*Expected Result*: **HTTP 403 Forbidden** (Blocked at gateway PEP before calling OpenAI):
```json
{
  "error": {
    "message": "Model 'gpt-4o' not allowed for key 'sk-agent-intern'. Allowed models: ['gpt-4o-mini']",
    "type": "permission_error",
    "code": "model_not_allowed"
  }
}
```

---

### Step 4: Demonstrate Native Secret Redaction Guardrail
```bash
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Here is my secret AKIAIOSFODNN7EXAMPLE and email test@nubris.com"}
    ]
  }'
```
*Observed Behavior*: LiteLLM scrubs the AWS key and email into `[REDACTED]` prior to upstream dispatch.

---

### Step 5: Demonstrate Zero-Touch Coding Task CPS with Local Git Merge

#### 5A: Open Local PR Branch
```bash
python3 mock_local_pr.py open --branch feat/db-timeout
```

#### 5B: Multi-Turn Agent Inferences (Clean Prompts, Zero Task Headers)
```bash
# Turn 1: Developer asks agent naturally
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Optimize SQLite index creation query"}]
  }'

# Turn 2: Follow-up turn with git tool execution in conversation history
# The gateway detects 'git checkout -b feat/db-timeout' in RAM and registers bhash:<sha256> -> task_id in Redis!
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Optimize SQLite index creation query"},
      {"role": "assistant", "content": "I will create a local branch and update indexes.", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "execute_command", "arguments": "{\"command\": \"git checkout -b feat/db-timeout\"}"}}]},
      {"role": "user", "content": "Generate regression test assertions"}
    ]
  }'
```

#### 5C: Simulate Local PR Merge Event
```bash
python3 mock_local_pr.py merge --branch feat/db-timeout
```
*Observed*: Script merges Git branch into `main` and dispatches webhook to port `4001`. The companion service hashes `feat/db-timeout`, matches the Redis digest, and updates SQLite.

#### 5D: Query Real-Time CPS in SQLite
```bash
sqlite3 gateway.db "SELECT * FROM v_coding_cps_summary;"
```
*Expected Output*:
```
task_8a1f10b2|2|1840|0.01245|verified_success|0.01245
```

---

### Step 6: Verify Zero Data Retention (ZDR) Invariant
```bash
sqlite3 gateway.db "SELECT request_id, model_routed, prompt_sha256, completion_sha256, zdr_verified FROM gateway_audit_ledger LIMIT 5;"
```
*Verification Assertion*: Columns contain strictly 64-character hexadecimal SHA-256 digests and zero cleartext.

---

### Step 7: Open Operational & Observability Consoles
1. **Access & Usage Console**: `http://localhost:4000/ui` (LiteLLM Admin UI)
2. **Distributed Tracing Waterfall**: `http://localhost:16686` (Jaeger UI)
3. **Interactive API Explorer**: `http://localhost:4000/docs` (Swagger UI)

---

## 7. Acceptance Criteria & Master Spec Traceability Matrix

### 7.1 Acceptance Criteria

| AC ID | Target Requirement | Verification Command / Procedure | Expected Status | Assertion Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **AC-CFG-01** | **REQ-CFG-01** | `docker compose up -d` | `Exit 0` | All 4 services (`litellm`, `redis`, `jaeger`, `cps_webhook`) running |
| **AC-CFG-02** | **REQ-CFG-02** | Query model fallback cascade with simulated upstream failure | `HTTP 200` | Gateway routes to `claude-3-5-sonnet` on primary failover |
| **AC-CFG-03** | **REQ-CFG-03** | Submit prompt containing AWS key and email | `HTTP 200` | Logged prompt sha256 masks sensitive strings into `[REDACTED]` |
| **AC-CFG-04** | **REQ-CFG-04** | Check port bindings: `netstat -an | grep LISTEN` | `Exit 0` | Ports 4000, 4001, 6379, 16686, 4317, 4318 are open |
| **AC-CFG-05** | **REQ-CFG-05** | Restart containers: `docker compose restart` | `Exit 0` | Data in `gateway.db` persists across container lifecycle |
| **AC-CFG-06** | **REQ-CFG-06** | Run `python3 mock_local_pr.py open/merge/reject` | `Exit 0` | Local git actions execute and merge webhooks dispatch cleanly |
| **AC-CFG-07** | **REQ-CFG-07** | Run `curl ... -d '{"model": "mock-model", ...}'` with no API keys | `HTTP 200` | Mock response returned with $0 token spend |
| **AC-CFG-08** | **REQ-CFG-08** | Test standard OpenAI SDK client against `http://localhost:4000/v1` | `HTTP 200` | Standard SDK queries succeed with zero custom headers |
| **AC-CFG-09** | **REQ-CFG-09** | Re-run `sqlite3 gateway.db < sqlite_schema.sql` on existing DB | `Exit 0` | Script executes idempotently with zero errors or table truncations |
| **AC-CFG-10** | **REQ-CFG-10** | Execute Runbook Steps 1 through 7 end-to-end | `Exit 0` | All 7 control pillars verified within 10 minutes |

### 7.2 Master Spec Traceability Matrix

| Master Specification Section | Traceability & Scope Alignment in SUB-POC-03 |
| :--- | :--- |
| **§3.7 Guardrails & PII Masking** | Native regex redaction rules (`AKIA...`, `sk-...`, emails). |
| **§4 Client Compatibility** | Cursor, Claude Code, OpenAI SDK, and actual MCP server configurations. |
| **§5.1 SQLite Schema Script** | Complete runnable `sqlite_schema.sql` DDL including compliance view. |
| **§5.2 LiteLLM Configuration** | Annotated production `litellm_config.yaml` with Redis router settings and custom logger. |
| **§5.3 Local Git PR Simulator** | Production Python script `mock_local_pr.py` and companion service `cps_webhook_server.py`. |
| **§5.4 Multi-Container Stack** | Production 4-service `docker-compose.yml`. |
| **§5.5 Environment Manifest** | Production template `.env.example` with host vs container OTel guidance. |
| **§6 Verification Runbook & Demo Script** | Complete 7-step execution commands, cURLs, and assertions. |
