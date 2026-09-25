# Minimal Local AI Gateway Proof of Concept (PoC)

> **Specification Reference:** [`docs/SPEC_AI_GATEWAY_LOCAL_POC.md`](./docs/SPEC_AI_GATEWAY_LOCAL_POC.md)  
> **Sub-Specs:** [`SUB-POC-01 (RBAC & Redis)`](./docs/sub_specs/SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md) · [`SUB-POC-02 (SQLite & ZDR)`](./docs/sub_specs/SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md) · [`SUB-POC-03 (Configs & Mocks)`](./docs/sub_specs/SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md)

An ultra-lean, high-velocity Enterprise AI Gateway running **100% locally** on a developer workstation with zero cloud infrastructure dependencies. Built for autonomous coding agents with zero-touch developer experience, gateway-level RBAC, native in-flight secret scrubbing, and automated **Cost Per Successful Task (CPS)** reconciliation.

---

## 1. Key Architectural Capabilities

- **Zero-Touch Developer Experience**: Developers use standard AI coding agents (Claude Code, OpenAI SDK clients, custom agents) naturally with zero manual headers, custom metadata, or proprietary headers.
- **Gateway-Level RBAC & Model Access Control**: Enforces model whitelisting (`HTTP 403 model_not_allowed`), role restrictions, and budget ceilings at the Ingress PEP *before* model dispatch occurs.
- **4-Role Redis 7 Engine**: Sub-millisecond sliding window rate limiting (RPM/TPM), atomic real-time spend metering (`INCRBYFLOAT`), virtual key caching, and ephemeral ZDR hashed branch indexing (`bhash:<sha256> -> task_id`).
- **Cryptographic Zero Data Retention (ZDR)**: Calculates deterministic in-memory SHA-256 digests (`prompt_sha256`, `completion_sha256`). Persists **strictly 0 bytes of cleartext messages** to disk.
- **Root-Prompt Invariance & Task ID Correlation**: Autonomously binds multi-turn conversational turns to a deterministic `task_id = "task_" + sha256(KeyAlias + "::" + root_prompt[:500])[:16]`.
- **Automated Cost Per Success (CPS) Reconciliation**: Companion Webhook service (`:4001`) receives GitHub PR merge webhooks, hashes the branch name in RAM, resolves `task_id` from Redis, and updates the task outcome to calculate final CPS.
- **Distributed Tracing & Searchable Observability**: Exports OpenTelemetry spans to Jaeger All-in-One (`:16686`), provides a dedicated Web Dashboard (`:4001`) with real-time Request ID search, and an Admin UI (`:4000/ui`).

---

## 2. Architecture & Service Topology

The system runs as an orchestrated 6-container Docker Compose stack:

```
[Agent: Claude Code / OpenAI SDK]
               │ (Standard OpenAI Wire: Bearer Token)
               ▼
   ┌────────────────────────────────────────────────────────┐
   │ LiteLLM AI Gateway Proxy (:4000)                       │
   │  ├─ Ingress PEP: RBAC Model Whitelisting & Keys        │
   │  ├─ Native Guardrail: Secret & PII Scrubbing [REDACTED]│
   │  ├─ Custom Logger: In-RAM SHA-256 & Task ID Derivation │
   │  └─ In-Flight Branch Sniffer                           │
   └───────┬────────────┬─────────────┬─────────────┬───────┘
           │            │             │             │
           ▼            ▼             ▼             ▼
   ┌──────────────┐┌───────────┐┌───────────┐┌────────────────┐
   │ PostgreSQL 16││  Redis 7  ││ Jaeger OTel││ Mock Upstream  │
   │ (:5433:5432) ││(:6380:6379││ (:16686)  ││   (:8088:8080) │
   │ Prisma Keys  ││ Rate Limits││ Spans &  ││ Zero-Cost Model│
   │  & Budgets   ││ Branch Reg ││ Waterfalls││  Completions  │
   └──────────────┘└─────┬─────┘└───────────┘└────────────────┘
                         │ (bhash:<sha256> -> task_id)
                         ▼
   ┌────────────────────────────────────────────────────────┐
   │ CPS Webhook Companion & Web Dashboard (:4001)          │
   │  ├─ POST /webhooks/github -> Reconciles SQLite Outcome │
   │  ├─ GET / -> Real-Time CPS & ZDR Observability Portal  │
   │  └─ GET /api/audit?q= -> Instant Request ID Search API │
   └─────────────────────┬──────────────────────────────────┘
                         ▼
   ┌────────────────────────────────────────────────────────┐
   │ SQLite Shared Volume: ./data/gateway.db (WAL Mode)     │
   │  ├─ Table: gateway_audit_ledger                        │
   │  ├─ View: v_coding_cps_summary (Cost Per Success)      │
   │  └─ View: v_zdr_compliance_check (Zero Cleartext Invar)│
   └────────────────────────────────────────────────────────┘
```

---

## 3. Directory Layout

```
PoCs/AI_Gateway/
├── config/                      # Configuration files & declarative schemas
│   ├── litellm_config.yaml      # LiteLLM routing, fallbacks, OTel & metrics callbacks
│   ├── prometheus.yml           # Prometheus metrics scraping configuration
│   ├── sqlite_schema.sql        # Single-table SQLite audit ledger bootstrap script
│   └── grafana/                 # Grafana datasources & dashboard provisioning
│       └── provisioning/
├── docker/                      # Dedicated container build manifests
│   ├── Dockerfile.litellm       # LiteLLM gateway proxy image
│   ├── Dockerfile.webhook       # CPS companion webhook service image
│   ├── Dockerfile.mock          # Zero-cost offline mock server image
│   ├── Dockerfile.prometheus   # Prometheus timeseries scraper image
│   └── Dockerfile.grafana      # Pre-provisioned Grafana observability image
├── src/                         # Core gateway components & extensions
│   ├── custom_zdr_logger.py     # In-RAM SHA-256 calculator, task_id deriver & Ingress PEP
│   ├── cps_webhook_server.py    # Companion PR webhook listener, web dashboard & /metrics
│   └── mock_upstream_server.py  # Zero-cost offline OpenAI mock server on :8080
├── scripts/                     # Developer operations, CLI tools & runners
│   ├── setup.sh                 # Environment bootstrap and key provisioning script
│   ├── verify.sh                # Automated test runner script
│   ├── mock_local_pr.py         # Local Git PR lifecycle simulator CLI
│   └── live_agent_run.py        # Autonomous agent demonstration script
├── client_templates/            # Production client integration manifests
│   ├── claude_code.json         # Claude Code CLI configuration (~/.claude/config.json)
│   ├── claude_env.sh            # Claude Code environment exports
│   ├── openai_sdk_example.py    # Runnable OpenAI Python SDK client example
│   ├── mcp_servers.json         # Model Context Protocol (MCP) server bindings
│   ├── generic_agent_env.sh     # OpenAI-compatible generic agent environment variables
│   └── README.md                # Client integration guide
├── tests/                       # Automated test suites
│   ├── test_phase1.py           # Phase 1 test suite (Schema, Ledger, ZDR)
│   ├── test_phase2.py           # Phase 2 test suite (CPS Webhook, PR Reconciliation)
│   ├── test_phase3.py           # Phase 3 test suite (RBAC, Rate Limits, Fallbacks)
│   ├── test_mcp_interrupt.py    # SUB-POC-04 MCP Tool Interrupt Ingress PEP suite
│   └── test_verification_runbook.py # Comprehensive 7-Step Verification Suite
├── docs/                        # Architectural specifications
│   ├── SPEC_AI_GATEWAY_LOCAL_POC.md
│   └── sub_specs/
│       ├── SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md
│       ├── SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md
│       ├── SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md
│       └── SUB_POC_04_MCP_INTERRUPT_INGRESS_PEP.md
├── data/                        # Host-mounted SQLite database directory
│   └── gateway.db               # Primary audit ledger database
├── docker-compose.yml           # 8-container production orchestration stack
├── Makefile                     # Standard developer commands (make up, make test, etc.)
├── setup.sh                     # Quickstart root bootstrap wrapper
├── verify.sh                    # Quickstart root verification wrapper
├── .env.example                 # Environment variables template
└── README.md                    # This document
```

---

## 4. Port Allocations & Services

| Service | Port | Description |
| :--- | :--- | :--- |
| **LiteLLM Gateway Proxy** | `4000` | OpenAI reverse proxy (`/v1/chat/completions`) & Admin UI (`/ui`) |
| **CPS Webhook & Dashboard**| `4001` | GitHub PR merge receiver (`/webhooks/github`) & Live UI (`/`) |
| **PostgreSQL 16** | `5433` (`5432`) | Prisma key database, team budgets, and role assignments |
| **Redis 7 State Engine** | `6380` (`6379`) | Sliding window counters, spend ledger & hashed branch registry |
| **Jaeger Trace Console** | `16686` | Distributed waterfall trace visualization UI |
| **Jaeger OTLP Receivers** | `4317` / `4318` | gRPC (`4317`) and HTTP (`4318`) trace ingestion |
| **Mock Upstream Server** | `8088` (`8080`) | Offline zero-cost model endpoint for testing |

---

## 5. Quickstart

### Step 1: Bootstrap the Environment
Execute the unified bootstrap script to start containers, prepare the database, and provision virtual keys:
```bash
./setup.sh --all
```

### Step 2: Run Automated Verification Runbook
Validate all 7 gateway pillars (31 assertions) with a single command:
```bash
./verify.sh
```

### Step 3: Run the Autonomous Live Agent Simulation
Simulate a multi-turn coding agent session routing through the gateway with Git PR merge reconciliation:
```bash
python3 live_agent_run.py
```

---

## 6. Observability & Dashboards

The stack provides three complementary operational consoles:

### 1. AI Gateway CPS & Audit Dashboard (`http://localhost:4001`)
- **Real-Time Cost Per Success (CPS)**: Track turns, tokens, spend, and final CPS dollar values per task.
- **Interactive Request ID Search**: Search by full or partial Request ID (e.g. `chatcmpl-...`) with real-time debounced substring highlighting.
- **Cryptographic ZDR Invariant Audit**: Confirm 100% compliance with zero cleartext persisted.
- **1-Click Trace Links**: Direct **"View Waterfall ↗"** buttons that jump to the exact span trace in Jaeger.

### 2. Jaeger Distributed Tracing Console (`http://localhost:16686`)
- **12–13 Span Waterfalls**: Inspect microsecond latency decomposition across FastAPI ingress, PostgreSQL key checks, Redis rate-limiting, upstream LLM execution, and spend logging.

### 3. LiteLLM Proxy Admin UI (`http://localhost:4000/ui`)
- Manage virtual keys (`sk-agent-developer`, `sk-agent-intern-poc`), inspect token budgets, and view raw PostgreSQL spend logs.

---

## 7. Client Integration Guides

Clients connect without custom headers or plugins. All metadata is inferred transiently in gateway memory:

### A. Claude Code CLI
Add to `~/.claude/config.json`:
```json
{
  "api_base": "http://localhost:4000/v1",
  "api_key": "sk-agent-developer",
  "default_model": "claude-3-5-sonnet"
}
```
Or source the environment helper:
```bash
source client_templates/claude_env.sh
```

### B. Standard OpenAI Python SDK
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-agent-developer",
)

response = client.chat.completions.create(
    model="mock-model", # or "gpt-4o", "claude-3-5-sonnet"
    messages=[{"role": "user", "content": "Explain binary search."}],
)
print(response.choices[0].message.content)
```

### C. Model Context Protocol (MCP) Servers
Configure your MCP clients (`mcp_servers.json`) normally:
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

### D. Generic AI Agent Frameworks (Aider, AutoGen, CrewAI, LangChain)
```bash
source client_templates/generic_agent_env.sh
```

---

## 8. Analytical Auditing via SQLite

Inspect the audit ledger and compliance views directly on the host:

```bash
# View recent transaction records with trace IDs:
sqlite3 data/gateway.db "SELECT request_id, trace_id, model_routed, latency_ms, cost_usd, task_id, task_outcome FROM gateway_audit_ledger ORDER BY created_at DESC LIMIT 5;"

# Inspect Cost Per Successful Task (CPS) analytical view:
sqlite3 -header -column data/gateway.db "SELECT * FROM v_coding_cps_summary LIMIT 10;"

# Run the Cryptographic Zero Data Retention compliance check:
sqlite3 -header -column data/gateway.db "SELECT * FROM v_zdr_compliance_check;"
```
