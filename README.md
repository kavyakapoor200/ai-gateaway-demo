# Minimal Local AI Gateway Proof of Concept (PoC)

> **Specification Reference:** [`docs/SPEC_AI_GATEWAY_LOCAL_POC.md`](./docs/SPEC_AI_GATEWAY_LOCAL_POC.md)  
> **Sub-Specs:** [`SUB-POC-01 (RBAC & Redis)`](./docs/sub_specs/SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md) · [`SUB-POC-02 (SQLite & ZDR)`](./docs/sub_specs/SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md) · [`SUB-POC-03 (Configs & Mocks)`](./docs/sub_specs/SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md)

This Proof of Concept implements an ultra-lean, high-velocity Enterprise AI Gateway running **100% locally** on a developer workstation with zero cloud infrastructure dependencies (aside from optional outbound LLM API calls).

---

## 1. Key Capabilities

- **Zero-Touch Developer Experience**: Developers use standard AI coding agents (Cursor, Claude Code, Aider, custom OpenAI SDK clients) naturally with zero manual headers, custom metadata, or proprietary headers.
- **Gateway-Level RBAC & Model Access Control**: Enforces model whitelisting (`HTTP 403 model_not_allowed`), role restrictions, and budget ceilings at the Ingress PEP *before* any model dispatch occurs.
- **4-Role Redis 7 Engine**: Sub-millisecond sliding window rate limiting (RPM/TPM), atomic real-time spend metering (`INCRBYFLOAT`), virtual key caching, and ephemeral ZDR hashed branch indexing (`bhash:<sha256> -> task_id`).
- **Cryptographic Zero Data Retention (ZDR)**: Calculates deterministic in-memory SHA-256 digests (`prompt_sha256`, `completion_sha256`). Persists **strictly 0 bytes of cleartext messages** to disk.
- **Root-Prompt Invariance & Task ID Correlation**: Autonomously binds multi-turn conversational turns to a deterministic `task_id` based on the invariant root user prompt.
- **Automated Cost Per Success (CPS) Reconciliation**: Companion Webhook service (`:4001`) receives GitHub PR merge webhooks, hashes the branch name in RAM, resolves `task_id` from Redis, and updates the task outcome to calculate final CPS.
- **Full Observability & Distributed Tracing**: Exports OpenTelemetry spans to Jaeger All-in-One (`:16686`) and provides a Web Admin Console (`:4000/ui`).

---

## 2. Directory Layout

```
PoCs/AI_Gateway/
├── docs/                     # Specifications and technical architecture
│   ├── SPEC_AI_GATEWAY_LOCAL_POC.md
│   └── sub_specs/
│       ├── SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md
│       ├── SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md
│       └── SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md
├── docker-compose.yml        # 4-container stack: litellm, redis, jaeger, cps_webhook
├── litellm_config.yaml       # LiteLLM routing, fallbacks, OTel & native regex guardrails
├── sqlite_schema.sql         # Single-table SQLite audit ledger & analytical views
├── custom_zdr_logger.py      # In-RAM SHA-256 calculator, task_id deriver & branch sniffer
├── cps_webhook_server.py     # Standalone companion webhook listener on :4001
├── mock_local_pr.py          # Local Git PR lifecycle simulator & webhook dispatcher
├── mock_upstream_server.py   # Zero-cost offline OpenAI mock server on :8080
├── setup.sh                  # One-click bootstrap and provisioning script
├── .env.example              # Environment variables template
├── .env                      # Local environment configuration
└── README.md                 # This document
```

---

## 3. Port Allocations & Services

| Service | Port | Description |
| :--- | :--- | :--- |
| **LiteLLM Gateway Proxy** | `4000` | OpenAI reverse proxy (`/v1/chat/completions`) & Admin UI (`/ui`) |
| **CPS Webhook Companion** | `4001` | GitHub PR merge webhook receiver (`/webhooks/github`) |
| **Redis 7 State Engine** | `6379` | Sliding window counters, spend ledger & hashed branch registry |
| **Jaeger OTLP Receivers** | `4317` / `4318` | gRPC (`4317`) and HTTP (`4318`) trace ingestion |
| **Jaeger Trace Console** | `16686` | Distributed waterfall trace visualization UI |
| **Mock Upstream Server** | `8080` | Optional offline zero-cost model endpoint |

---

## 4. Quickstart

### Step 1: Initialize Database & Start Services
Run the automated setup script:
```bash
./setup.sh --all
```
Or run individual steps manually:
```bash
# 1. Initialize SQLite schema
sqlite3 gateway.db < sqlite_schema.sql

# 2. Start the 4 containers
docker compose up -d

# 3. Provision RBAC virtual keys
./setup.sh --provision-keys
```

### Step 2: Verify Gateway Health
```bash
curl http://localhost:4000/health
# Expected: {"status": "healthy"}
```

---

## 5. End-to-End Verification Runbook

### Test 1: Allowed Model Ingress (Developer Key)
```bash
curl -i -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "Explain binary search algorithm"}]
  }'
```
*Expected Result*: **HTTP 200 OK** and completion output.

### Test 2: Gateway-Level RBAC Rejection (Model Escalation Blocked)
Submit a prohibited model (`gpt-4o`) using the restricted `sk-agent-intern` key:
```bash
curl -i -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-intern" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Explain binary search algorithm"}]
  }'
```
*Expected Result*: **HTTP 403 Forbidden** (Blocked at Ingress PEP before contacting model provider):
```json
{
  "error": {
    "message": "Model 'gpt-4o' not allowed for key 'sk-agent-intern'. Allowed models: ['gpt-4o-mini', 'mock-model']",
    "type": "permission_error",
    "code": "model_not_allowed"
  }
}
```

### Test 3: Native Secret Redaction Guardrail
```bash
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-model",
    "messages": [
      {"role": "user", "content": "Here is my key AKIAIOSFODNN7EXAMPLE and email dev@example.com"}
    ]
  }'
```
*Expected Result*: The incoming prompt is scrubbed by LiteLLM regex guardrails into `[REDACTED]` in-memory.

### Test 4: Zero-Touch Task ID & Branch Sniffing
Simulate a multi-turn coding session where the agent executes a Git tool:
```bash
# Turn 1: Developer prompt
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-model",
    "messages": [{"role": "user", "content": "Fix database timeout in query.go"}]
  }'

# Turn 2: Follow-up turn containing git checkout tool call
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-model",
    "messages": [
      {"role": "user", "content": "Fix database timeout in query.go"},
      {"role": "assistant", "content": "Creating branch.", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "execute_command", "arguments": "{\"command\": \"git checkout -b feat/db-timeout\"}"}}]},
      {"role": "tool", "tool_call_id": "c1", "content": "Switched to branch feat/db-timeout"},
      {"role": "user", "content": "Add connection pool config"}
    ]
  }'
```

### Test 5: Reconcile PR Merge via Webhook
Simulate the PR merge event:
```bash
python3 mock_local_pr.py merge --branch feat/db-timeout --simulate
```
*Expected Result*: Webhook dispatches to `http://localhost:4001/webhooks/github`, hashes `feat/db-timeout`, resolves `task_id` from Redis, and updates SQLite `task_outcome = 'verified_success'`.

### Test 6: Verify Real-Time Cost Per Success (CPS) View
```bash
sqlite3 gateway.db "SELECT * FROM v_coding_cps_summary;"
```

### Test 7: Verify Zero Data Retention (ZDR) Compliance
```bash
sqlite3 gateway.db "SELECT * FROM v_zdr_compliance_check;"
# Expected: "100% COMPLIANT - ZERO PLAINTEXT DETECTED"
```

---

## 6. Client Compatibility & Setup

### Cursor IDE
In `.cursor/settings.json` or Global Settings:
```json
{
  "cursor.openaiBaseUrl": "http://localhost:4000/v1",
  "cursor.openaiApiKey": "sk-agent-developer",
  "cursor.model": "gpt-4o"
}
```

### Claude Code CLI
In `~/.claude/config.json`:
```json
{
  "apiBase": "http://localhost:4000/v1",
  "apiKey": "sk-agent-developer",
  "model": "claude-3-5-sonnet"
}
```

### Python OpenAI SDK
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-agent-developer"
)

response = client.chat.completions.create(
    model="mock-model",
    messages=[{"role": "user", "content": "Hello gateway!"}]
)
print(response.choices[0].message.content)
```

---

## 7. Performance Benchmarking & Stress Testing

You can evaluate the gateway directly using the pre-built benchmarking utilities:
```bash
# 1. Start offline mock model server (port 8080)
python3 mock_upstream_server.py --port 8080 &

# 2. Benchmark gateway overhead vs. direct upstream
python3 ../karthik-ag_gateway_/benchmark_gateway.py \
  --url http://localhost:4000/v1/chat/completions \
  --compare-direct-url http://localhost:8080/v1/chat/completions \
  --key sk-agent-developer \
  --model mock-model \
  --concurrency 5 --requests 20

# 3. Simulate burst load against Redis sliding-window rate limiters
python3 ../karthik-gateway-poc/src/simulator.py --requests 50 --concurrency 5
```
