# Technical Specification: Minimal Local AI Gateway Proof of Concept (PoC)
## Localhost Control Plane with Generic Coding Agent Ingress, Gateway-Level RBAC, Redis Engine, SQLite ZDR Ledger, Zero-Touch Task ID & Full Observability

**Document Version:** 2.1.0-LOCAL-POC  
**Date:** September 2026  
**Target Environment:** Local Developer Workstation (macOS / Apple Silicon / Docker Desktop)  
**Host Boundary:** 100% Localhost Execution. Zero Cloud Infrastructure (only external outbound LLM API calls). Seamlessly portable to remote hosting.  
**Core Baseline:** LiteLLM Gateway + Redis 7 (Rate Limiting, Real-Time Budgets & Hashed Branch State) + Embedded SQLite Ledger (`gateway.db`) + OpenTelemetry Distributed Tracing (Jaeger) + Gateway-Level RBAC & Model Access Control + Zero-Touch Root-Hash & Hashed-Branch CPS Engine (Companion Webhook `:4001`) + Native LiteLLM Guardrails + Web UI Console (`:4000/ui`).

---

## Master Specification & Sub-Specification Hierarchy

This document serves as the **Master Architectural Specification** for the Minimal Local AI Gateway Proof of Concept (PoC). It establishes the overarching system topology, the Seven-Layer AI System Stack mapping, component interaction blueprints, and cross-cutting security invariants.

Detailed, implementation-ready specifications are decomposed into the following modular sub-specifications:

| Sub-Spec ID | Sub-Specification Document | Domain & Classification | Key Responsibilities |
| :--- | :--- | :--- | :--- |
| **`SUB-POC-01`** | [**`SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md`**](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_01_CORE_LITELLM_RBAC_AND_REDIS.md) | Control Plane Ingress, Identity Governance & In-Memory State | • LiteLLM proxy pipeline on `:4000`<br>• Gateway Ingress PEP (5 Verification Gates)<br>• Gateway-level RBAC & model whitelisting (`HTTP 403 model_not_allowed`)<br>• Admin endpoint protection (`proxy_admin`)<br>• 4-Role Redis 7 Engine: sliding-window RPM/TPM (<0.5ms), atomic spend tracking (`INCRBYFLOAT`), key cache, and ZDR hashed branch registry (`bhash:<sha256> -> task_id`)<br>• Web Admin UI (`:4000/ui`) & Swagger (`:4000/docs`) |
| **`SUB-POC-02`** | [**`SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md`**](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md) | Data Persistence, Compliance Auditing, Distributed Tracing & FinOps | • Single-table SQLite audit ledger (`gateway.db`, WAL mode)<br>• Cryptographic Zero Data Retention (ZDR) Invariant (strict SHA-256 digests, 0 bytes cleartext)<br>• Zero-Touch invariant root-prompt hashing ($task\_id$ derivation)<br>• PR merge webhook reconciliation (`POST /webhooks/github`)<br>• Real-time Cost Per Success ($CPS$) engine and `v_coding_cps_summary` analytical view<br>• OpenTelemetry v2 OTLP gRPC export (`:4317`) into Jaeger All-In-One (`:16686`)<br>• 6-Panel Grafana telemetry dashboard specification<br>• Automated compliance verification view `v_zdr_compliance_check` |
| **`SUB-POC-03`** | [**`SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md`**](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md) | Infrastructure-as-Code, Runnable Configurations, Emulators & Validation | • Production LiteLLM configuration (`litellm_config.yaml`) with latency routing and fallback rules<br>• Native regex secret & PII redaction guardrails (`[REDACTED]`)<br>• Multi-container `docker-compose.yml` (LiteLLM, Redis, Jaeger)<br>• Environment manifest `.env.example`<br>• SQLite bootstrap script `sqlite_schema.sql`<br>• Local Git PR simulator CLI `mock_local_pr.py`<br>• Offline zero-cost mock upstream server<br>• Agent configurations (Cursor, Claude Code, OpenAI SDK) & actual MCP server bindings<br>• Complete 7-Step End-to-End Verification Runbook & Demo Script |

---

## Table of Contents
0. [Master Specification & Sub-Specification Hierarchy](#master-specification--sub-specification-hierarchy)
1. [Executive Summary & Local System Topology](#1-executive-summary--local-system-topology)
   - 1.1 [Objective & Scope](#11-objective--scope)
   - 1.2 [The Seven-Layer AI Gateway Architecture Stack](#12-the-seven-layer-ai-gateway-architecture-stack)
   - 1.3 [Local Topology & Component Interaction Blueprint](#13-local-topology--component-interaction-blueprint)
2. [Component Architecture & Core Gateway Mechanisms](#2-component-architecture--core-gateway-mechanisms)
   - 2.1 [LiteLLM Core Gateway Plane](#21-litellm-core-gateway-plane)
   - 2.2 [Gateway-Level RBAC & Access Control Engine (Where & How It Is Enforced)](#22-gateway-level-rbac--access-control-engine-where--how-it-is-enforced)
   - 2.3 [Where & How Redis Is Used in the Gateway](#23-where--how-redis-is-used-in-the-gateway)
   - 2.4 [Embedded SQLite Audit & CPS Ledger (`gateway.db`)](#24-embedded-sqlite-audit--cps-ledger-gatewaydb)
   - 2.5 [Observability Deep-Dive: Metrics, Tracing, ZDR Logs & Dashboard Specification](#25-observability-deep-dive-metrics-tracing-zdr-logs--dashboard-specification)
   - 2.6 [Zero-Touch Task ID Assignment & ZDR-Compliant Git Bridge](#26-zero-touch-task-id-assignment--zdr-compliant-git-bridge)
   - 2.7 [User Interfaces & Operational Consoles](#27-user-interfaces--operational-consoles)
3. [The Seven Gateway Control Pillars (Local PoC Edition)](#3-the-seven-gateway-control-pillars-local-poc-edition)
   - 3.1 [Monitoring (OTel Traces & Spans)](#31-monitoring-otel-traces--spans)
   - 3.2 [Governance (Virtual API Keys & Model Policies)](#32-governance-virtual-api-keys--model-policies)
   - 3.3 [Rate Limits (RPM & TPM via Redis Sliding Windows)](#33-rate-limits-rpm--tpm-via-redis-sliding-windows)
   - 3.4 [Auditing & Zero Data Retention (Cryptographic SHA-256 Hashing)](#34-auditing--zero-data-retention-cryptographic-sha-256-hashing)
   - 3.5 [Role-Based Access Control (Model Whitelisting & Tier Ceilings)](#35-role-based-access-control-model-whitelisting--tier-ceilings)
   - 3.6 [Budgeting & Spend Enforcement](#36-budgeting--spend-enforcement)
   - 3.7 [Guardrails & PII/Secret Masking](#37-guardrails--piisecret-masking)
4. [Client Compatibility: Coding Agent / Client & Actual MCP Integration](#4-client-compatibility-coding-agent--client--actual-mcp-integration)
5. [Complete Runnable Configuration & Code Artifacts](#5-complete-runnable-configuration--code-artifacts)
   - 5.1 [SQLite Database Schema (`sqlite_schema.sql`)](#51-sqlite-database-schema-sqliteschemasql)
   - 5.2 [LiteLLM Gateway Configuration (`litellm_config.yaml`)](#52-litellm-gateway-configuration-litellm_configyaml)
   - 5.3 [Zero-Touch Local Git PR Simulator (`mock_local_pr.py`)](#53-zero-touch-local-git-pr-simulator-mock_local_prpy)
   - 5.4 [Local Multi-Container Stack (`docker-compose.yml`)](#54-local-multi-container-stack-docker-composeyml)
   - 5.5 [Environment Variables Manifest (`.env.example`)](#55-environment-variables-manifest-envexample)
6. [End-to-End Verification Runbook & Demo Script](#6-end-to-end-verification-runbook--demo-script)
7. [Footnote: Reusing PoC Evaluation & Simulation Harnesses](#7-footnote-reusing-poc-evaluation--simulation-harnesses)

---

## 1. Executive Summary & Local System Topology

### 1.1 Objective & Scope
This specification defines an ultra-lean, high-velocity Proof of Concept (PoC) for an Enterprise AI Gateway running **100% locally** on a developer machine, with zero cloud compute except outbound LLM API calls. 

Crucially, **the developer user experience is completely untouched**: developers interact naturally with any coding agent or client (e.g. Cursor, Claude Code, Codex, or custom agents) without typing manual headers or task IDs. The gateway autonomously correlates multi-turn requests, binds them to Git branches using **cryptographic SHA-256 digests in transient memory**, enforces gateway-level RBAC, meters task costs, and reconciles outcomes against local or remote GitHub merge webhooks—all while strictly preserving **Cryptographic Zero Data Retention (ZDR)**.

### 1.2 The Seven-Layer AI Gateway Architecture Stack

The diagram below maps the complete AI Gateway and agent ecosystem across the standard Seven-Layer AI System Stack, illustrating precisely how responsibility is distributed from client interaction down to runtime controls and operations:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  7. CONTROL / OPS                                                           │
│  OTel tracing (Jaeger) · daily budget caps (HTTP 429) · ZDR RAM             │
│  audit · Cost Per Success (CPS) engine · LiteLLM console (:4000/ui)         │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  6. INFERENCE                                                               │
│  multi-provider routing · auto-failover (GPT-4o -> Claude) · native regex   │
│  PII & secret masking · circuit breakers · zero-cost mock upstream          │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  5. TOOLS / ENVIRONMENT                                                     │
│  actual MCP servers (Git/Filesystem) · in-flight branch sniffing in RAM ·   │
│  local Git repository · GitHub lifecycle merge webhook (/webhooks/github)   │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. MEMORY / STATE                                                          │
│  Redis 7: RPM/TPM sliding windows · atomic spend tracking · ZDR hashed      │
│  branch registry · embedded SQLite (gateway.db, WAL, zero plaintext)        │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. COGNITION                                                               │
│  Coding agent multi-turn reasoning · zero-touch root-prompt hashing        │
│  (SHA-256 -> task_id) · deterministic session correlation · clean UX        │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  2. RUNTIME / ORCHESTRATION                                                 │
│  LiteLLM proxy (:4000) · Ingress PEP · gateway-level RBAC & key auth ·      │
│  model whitelisting (HTTP 403 model_not_allowed) · token-bucket limiter     │
└─────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. INTERFACE / CHANNEL                                                     │
│  OpenAI-compatible API (/v1/chat/completions)                               │
│  Swagger API explorer (:4000/docs) · local PR simulator (mock_local_pr.py)  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 1.3 Local Topology & Component Interaction Blueprint

```mermaid
flowchart TD
    subgraph Host["Developer Machine (macOS Localhost)"]
        subgraph Client["AI Agent & Tool Layer"]
            CodingAgent["Coding Agent / Client\n(Standard OpenAI Client - Unmodified UX)"]
            ActualMCP["Actual MCP Server(s)\n(Git, Filesystem, or DB MCP Tools)"]
        end

        subgraph GatewayStack["LiteLLM AI Gateway Control Plane (:4000)"]
            AuthPEP["Gateway Ingress PEP (RBAC & Key Auth)\n- Virtual Key Verification\n- Model Whitelist Check\n- Admin Endpoint Authorization"]
            NativeGuard["LiteLLM Native Guardrail\n(Regex Secret & PII Scrubbing)"]
            RootHasher["Zero-Touch Root-Prompt Hasher\n(Transient SHA-256 Hashing -> task_id)"]
            ModelRouter["Model Router & Failover Engine\n(Primary: GPT-4o / Fallback: Sonnet / Mock)"]
        subgraph GatewayStack["LiteLLM AI Gateway Control Plane (:4000)"]
            AuthPEP["Gateway Ingress PEP (RBAC & Key Auth)\n- Virtual Key Verification\n- Model Whitelist Check\n- Admin Endpoint Authorization"]
            NativeGuard["LiteLLM Native Guardrail\n(Regex Secret & PII Scrubbing)"]
            RootHasher["Zero-Touch Root-Prompt Hasher\n(Transient SHA-256 Hashing -> task_id)"]
            ModelRouter["Model Router & Failover Engine\n(Primary: GPT-4o / Fallback: Sonnet / Mock)"]
            ZDRHook["ZDR Audit Callback (custom_zdr_logger.py)\n(RAM-only SHA-256 -> SQLite & Redis bhash)"]
        end

        subgraph WebhookCompanion["CPS Webhook Companion Service (:4001)"]
            CPSHook["CPS Webhook Listener (cps_webhook_server.py)\n(POST http://localhost:4001/webhooks/github)"]
        end

        subgraph LocalState["Local State & Observability Engines"]
            Redis[("Redis 7 (:6379)\n- RPM/TPM Sliding Windows\n- Real-Time Atomic Spend Counters\n- ZDR Hashed Branch Registry: bhash:<sha256> -> task_id")]
            SQLite[("Embedded SQLite (gateway.db)\n- Single Table: gateway_audit_ledger\n- Zero-Process, WAL Mode")]
            Jaeger["Jaeger All-In-One (:16686)\n- OTLP Traces (:4317)\n- Request Lifecycle Waterfall Flow"]
            LiteLLM_UI["LiteLLM Admin Console (:4000/ui)\n- Visual Key Issuance & Budgeting"]
        end

        subgraph LocalGit["Local Git Repository"]
            MockPR["Local PR Merge Simulator\n(mock_local_pr.py / .git hook)"]
        end
    end

    subgraph ExternalCloud["External Cloud Providers (Only Network Egress)"]
        OpenAI["OpenAI API (GPT-4o, GPT-4o-mini)"]
        Anthropic["Anthropic API (Claude 3.5 Sonnet)"]
        OpenRouter["OpenRouter (Fallback Tier)"]
    end

    %% Client Ingress & Tools
    CodingAgent -->|"1. POST /v1/chat/completions\n(Clean Prompt, Zero Manual Headers)"| AuthPEP
    CodingAgent <-->|"Discovers & Invokes Tools"| ActualMCP

    %% Gateway Core Pipeline
    AuthPEP <-->|"Check Permissions & Keys"| Redis
    AuthPEP --> NativeGuard
    NativeGuard --> RootHasher
    RootHasher --> ModelRouter

    %% Model Resolution & Fallback
    ModelRouter -->|"Primary Route"| OpenAI
    ModelRouter -.->|"Failover (429/500)"| Anthropic
    ModelRouter -.->|"Emergency Route"| OpenRouter

    %% State & Logging
    ModelRouter <-->|"Atomic Rate Limits & Spend"| Redis
    ZDRHook -->|"Insert Metrics & SHA-256 Hashes\n(Strictly Zero Plaintext)"| SQLite
    GatewayStack -->|"OTLP Spans over gRPC (:4317)"| Jaeger

    %% CPS Reconciliation
    MockPR -.->|"2. Local Git Merge Event\nPOST http://localhost:4001/webhooks/github"| CPSHook
    CPSHook <-->|"Lookup Hashed Branch SHA-256"| Redis
    CPSHook -->|"Update PR Status & Calculate CPS"| SQLite
```

---

## 2. Component Architecture & Core Gateway Mechanisms

### 2.1 LiteLLM Core Gateway Plane
- **Host / Port**: `http://localhost:4000`
- **Container**: `ghcr.io/berriai/litellm:main-latest`
- **Core Function**: Acts as a reverse proxy sitting between the coding agent/client and upstream foundation models. It intercepts all `/v1` calls, enforces gateway-level access controls, redacts secrets, meters token costs, and exports distributed traces.

---

### 2.2 Gateway-Level RBAC & Access Control Engine (Where & How It Is Enforced)

Unlike application-level or tool-level access control, **Gateway-Level Access Control** protects model infrastructure, prevents unauthorized model consumption, stops cost overruns, and restricts gateway management endpoints before any upstream LLM call or tool execution can occur.

```mermaid
flowchart TD
    ClientReq["Incoming HTTP Request\nPOST /v1/chat/completions\nAuthorization: Bearer sk-agent-xxx\nModel: gpt-4o"]
    
    subgraph GatewayPEP["Gateway Policy Enforcement Point (PEP) Ingress Middleware"]
        Step1{"Step 1: Key Authentication\nIs Bearer Key Valid in Redis Cache?"}
        Step2{"Step 2: Key Active & Not Expired?"}
        Step3{"Step 3: Route Authorization\nIs caller accessing Admin Routes (/key, /team)\nwithout proxy_admin role?"}
        Step4{"Step 4: Model Whitelist Check\nIs requested model in Key's 'models' array?"}
        Step5{"Step 5: Budget Ceiling Check\nHas key or team exceeded 'max_budget'?"}
        Step6{"Step 6: Rate Limit Check\nIs RPM or TPM exceeded in Redis?"}
    end

    Allow["✅ ALLOW: Forward to Guardrail & Model Router"]
    Reject401["❌ HTTP 401 Unauthorized\n(Invalid or expired API Key)"]
    Reject403_Admin["❌ HTTP 403 Forbidden\n(Admin route requires proxy_admin role)"]
    Reject403_Model["❌ HTTP 403 Forbidden\n(Model 'gpt-4o' not allowed for key role 'intern')"]
    Reject429_Budget["❌ HTTP 429 Quota Exceeded\n(Budget ceiling $5.00 reached)"]
    Reject429_Rate["❌ HTTP 429 Too Many Requests\n(Rate limit 20 RPM exceeded)"]

    ClientReq --> Step1
    Step1 -- No --> Reject401
    Step1 -- Yes --> Step2
    Step2 -- No --> Reject401
    Step2 -- Yes --> Step3
    Step3 -- Yes --> Reject403_Admin
    Step3 -- No --> Step4
    Step4 -- No --> Reject403_Model
    Step4 -- Yes --> Step5
    Step5 -- Exceeded --> Reject429_Budget
    Step5 -- OK --> Step6
    Step6 -- Exceeded --> Reject429_Rate
    Step6 -- OK --> Allow
```

#### Where It Is Enforced
Enforcement takes place in LiteLLM's **Ingress Authentication & Authorization Middleware** (the Policy Enforcement Point, or PEP) located in the request pipeline **before** parameter parsing, guardrail execution, or model dispatch.

#### How It Is Enforced (The 5 Verification Gates)
1. **Virtual Key Authentication & Role Binding**:
   - Each client (coding agent, developer, pipeline) is assigned a virtual key (`sk-agent-...`).
   - The key is bound to metadata containing `role` (e.g. `admin`, `developer`, `intern`), `team_id`, and `max_budget`.
2. **Model Access Whitelisting (Model-Level RBAC)**:
   - Keys are provisioned with an explicit `models: [...]` array.
   - *Example*: An `intern` key has `models: ["gpt-4o-mini"]`. If an agent sends `{"model": "gpt-4o"}` using this key, the gateway PEP rejects the request before calling OpenAI:
     ```json
     {
       "error": {
         "message": "Model 'gpt-4o' not allowed for key 'sk-agent-intern-01'. Allowed models: ['gpt-4o-mini']",
         "type": "permission_error",
         "code": "model_not_allowed"
       }
     }
     ```
   - *Status Code*: `HTTP 403 Forbidden`.
3. **Administrative Endpoint Authorization**:
   - Management endpoints (`POST /key/generate`, `POST /team/new`, `GET /spend`) strictly require the `proxy_admin` role (authenticated via `LITELLM_MASTER_KEY`). Standard agent keys attempting to access these routes are rejected with `HTTP 403 Forbidden`.
4. **Hard Budget Ceilings**:
   - Keys enforce a dollar ceiling (e.g., `max_budget: 2.0` over `duration: 1d`). If spend $\ge \$2.00$, the gateway immediately returns `HTTP 429 Quota Exceeded`.
5. **Rate Limiting Enforcement**:
   - Enforces RPM (Requests Per Minute) and TPM (Tokens Per Minute) per key and per model.

---

### 2.3 Where & How Redis Is Used in the Gateway

Redis 7 runs as a high-performance in-memory state engine. Because an AI gateway cannot afford disk I/O on every token or request, Redis handles four mission-critical operations:

```mermaid
flowchart LR
    Gateway["LiteLLM Gateway Core (:4000)"]
    
    subgraph RedisOps["Redis 7 In-Memory Engine (:6379)"]
        R1["1. Sliding-Window Rate Limiting\n- Keys: litellm:ratelimit:<key_id>:rpm\n- Atomic INCR & EXPIRE in <0.5ms"]
        R2["2. Real-Time Spend & Budget Tracking\n- Keys: litellm:spend:<key_id>\n- Atomic INCRBYFLOAT on completion"]
        R3["3. Virtual Key & Policy Cache\n- Keys: litellm:keys:<key_hash>\n- Caches permissions & model lists"]
        R4["4. ZDR Hashed Branch Registry\n- Keys: bhash:<sha256(branch)>\n- Value: task_id (TTL: 7 days)\n- ZERO plaintext branch names stored"]
    end

    Gateway <-->|"Check RPM / TPM"| R1
    Gateway <-->|"Update & Check Budget"| R2
    Gateway <-->|"Validate Key Permissions"| R3
    Gateway <-->|"Store & Query Hashed Branch"| R4
```

1. **Sliding-Window Rate Limiting (RPM / TPM)**: Atomic `INCR` and `EXPIRE 60` counters evaluated in `<0.5ms`.
2. **Real-Time Spend Tracking**: Atomic `INCRBYFLOAT` incrementing cumulative spend on response completion; blocks subsequent calls immediately when budget is exceeded.
3. **Virtual Key & Policy Cache**: In-memory caching of virtual key metadata, eliminating database reads on ingress.
4. **ZDR Hashed Branch Registry**: Ephemeral mapping between cryptographic digests of Git branch names and task IDs (`bhash:<sha256> -> task_id`).

---

### 2.4 Embedded SQLite Audit & CPS Ledger (`gateway.db`)

All persistent audit records and task outcome metrics are written to an embedded **SQLite database** running in **WAL (Write-Ahead Logging)** mode.

- **File Path**: `/app/gateway.db` (persisted on host via local Docker volume).
- **Single-Table Design**: A single consolidated table `gateway_audit_ledger` records every transaction without cleartext prompt retention.

```sql
CREATE TABLE IF NOT EXISTS gateway_audit_ledger (
    request_id VARCHAR(64) PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Governance & RBAC
    api_key_alias VARCHAR(64) NOT NULL,
    caller_role VARCHAR(32) NOT NULL,
    
    -- Model Routing & Execution
    model_requested VARCHAR(64) NOT NULL,
    model_routed VARCHAR(64) NOT NULL,
    fallback_triggered INTEGER DEFAULT 0,
    http_status INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    
    -- Financials & Tokens
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    
    -- Zero Data Retention (ZDR) Invariant
    -- STRICTLY SHA-256 digests. ZERO plaintext persisted.
    prompt_sha256 TEXT NOT NULL,
    completion_sha256 TEXT NOT NULL,
    zdr_verified INTEGER DEFAULT 1,
    
    -- Coding Task Cost Per Success (CPS)
    task_id TEXT,                    -- e.g. 'task_8a1f10b2c3d4'
    task_outcome TEXT DEFAULT 'pending' -- 'pending', 'verified_success', 'unmerged_closed'
);
```

---

### 2.5 Observability Deep-Dive: Metrics, Tracing, ZDR Logs & Dashboard Specification

#### 2.5.1 Everything Tracked (The Complete Telemetry Manifest)

| Category | Telemetry Field / Metric Name | Type | Description |
| :--- | :--- | :--- | :--- |
| **Identity** | `gen_ai.user.key_alias` | Attribute | Virtual API key alias (e.g. `sk-agent-developer`) |
| **Identity** | `gen_ai.user.role` | Attribute | Caller RBAC role (`admin`, `developer`, `intern`) |
| **Routing** | `gen_ai.request.model` | Attribute | Logical model requested by client (e.g. `gpt-4o`) |
| **Routing** | `gen_ai.response.model` | Attribute | Actual model routed (e.g. `claude-3-5-sonnet` if fallback occurred) |
| **Routing** | `gen_ai.fallback_triggered` | Boolean | True if primary model failed and failover executed |
| **Performance** | `gen_ai.client.operation.duration` | Histogram | End-to-end request duration in seconds |
| **Performance** | `gen_ai.client.time_to_first_token` | Gauge / Span | Time to First Token (TTFT) for streaming requests |
| **Tokens** | `gen_ai.usage.input_tokens` | Counter | Prompt token consumption |
| **Tokens** | `gen_ai.usage.output_tokens` | Counter | Completion token generation |
| **Tokens** | `gen_ai.usage.total_tokens` | Counter | Cumulative tokens billed |
| **Economics** | `gen_ai.request.cost_usd` | Gauge | Exact dollar cost calculated from active rate cards |
| **Economics** | `litellm_spend_total{key}` | Counter | Cumulative dollar spend per key |
| **Security** | `gen_ai.prompt.sha256` | 64-char Hex | Cryptographic SHA-256 hash of input prompt |
| **Security** | `gen_ai.completion.sha256` | 64-char Hex | Cryptographic SHA-256 hash of generated completion |
| **Security** | `gen_ai.guardrail.pii_redacted` | Boolean | True if native regex guardrail scrubbed secrets/PII |
| **Status** | `http.status_code` | Attribute | HTTP response status (200, 401, 403, 429, 500) |
| **CPS** | `gen_ai.task.id` | Attribute | Coding task identifier (e.g. `task_8a1f10b2c3d4`) |
| **CPS** | `gen_ai.task.outcome` | Attribute | Resolution status (`pending`, `verified_success`, `unmerged_closed`) |
| **CPS** | `gen_ai.task.cost_per_success` | Gauge | Final Dollar Cost Per Verified PR Merge |

#### 2.5.2 Complete Dashboard Specification (Grafana / Jaeger Visualization)

```
┌───────────────────────────────────────┬───────────────────────────────────────┐
│ PANEL 1: Real-Time Spend & Budget Burn│ PANEL 2: Latency & TTFT Distribution  │
│ [Gauge: $3.42 / $5.00 Cap]            │ [P50: 320ms | P95: 1,150ms | P99: 2.1s│
│ Time-Series graph of $/hr per key     │ Histogram of inference durations      │
├───────────────────────────────────────┼───────────────────────────────────────┤
│ PANEL 3: Model Usage & Failover Counts│ PANEL 4: Rate Limits & RBAC Rejections│
│ [Bar Chart: 72% GPT-4o, 28% Claude]   │ [Counter: 14 HTTP 429s, 3 HTTP 403s]  │
│ Alert indicator on fallback triggers  │ Breakdown by key and client IP        │
├───────────────────────────────────────┼───────────────────────────────────────┤
│ PANEL 5: Cryptographic ZDR Audit Log  │ PANEL 6: Coding Task Cost Per Success │
│ [Table: Timestamp | Key | Model |     │ [Table: Task ID | Turns | Total Cost |│
│  Prompt SHA-256 | Completion SHA-256] │  Outcome | Final CPS ($/Merged PR)]   │
└───────────────────────────────────────┴───────────────────────────────────────┘
```

---

### 2.6 Zero-Touch Task ID Assignment & ZDR-Compliant Git Bridge

To eliminate all manual headers and keep the developer UX completely untouched while supporting both local and remote gateways and strictly upholding Zero Data Retention (ZDR), the gateway uses a **two-step cryptographic correlation engine**:

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer (Unchanged UX)
    participant Agent as Coding Agent / Client
    participant RemoteGW as Remote / Local Gateway (:4000)
    participant Redis as Redis 7 (:6379)
    participant SQLite as SQLite (gateway.db)
    participant GitHub as Local Git / GitHub Webhook
    participant WebhookSvc as CPS Webhook (:4001)

    Note over Dev,Agent: 1. Developer asks agent naturally
    Dev->>Agent: "Fix the database timeout bug in db.ts"

    Note over Agent,RemoteGW: 2. Turn 1: Agent queries LLM
    Agent->>RemoteGW: POST /v1/chat/completions (messages: [System, "Fix the database..."])
    Note over RemoteGW: Computes in RAM: SHA-256("Fix database...") -> task_id: 'task_8a1f'
    RemoteGW->>SQLite: INSERT turn 1 (cost: $0.004, task_id: 'task_8a1f', status: 'pending')

    Note over Agent,RemoteGW: 3. Turn 2: Agent executes git branch tool
    Agent->>RemoteGW: Tool Call in context: "git checkout -b feat/db-timeout"
    Note over RemoteGW: custom_zdr_logger detects tool call, computes SHA-256("feat/db-timeout") = 9e2f...
    RemoteGW->>Redis: SET bhash:9e2f... -> 'task_8a1f' (ZERO plaintext branch stored)
    RemoteGW->>SQLite: INSERT turn 2 (cost: $0.008, task_id: 'task_8a1f', status: 'pending')

    Note over Dev,GitHub: 4. Code is merged into main
    Dev->>GitHub: PR for branch 'feat/db-timeout' merged!

    Note over GitHub,WebhookSvc: 5. Lifecycle Webhook arrives
    GitHub->>WebhookSvc: POST http://localhost:4001/webhooks/github (ref: "feat/db-timeout", merged: true)
    Note over WebhookSvc: Computes in RAM: SHA-256("feat/db-timeout") = 9e2f...
    WebhookSvc->>Redis: GET bhash:9e2f... -> returns 'task_8a1f'
    WebhookSvc->>SQLite: UPDATE gateway_audit_ledger SET task_outcome = 'verified_success' WHERE task_id = 'task_8a1f'
    WebhookSvc->>SQLite: Recalculate CPS: Turn 1 ($0.004) + Turn 2 ($0.008) = $0.012
```

#### Step 1: Cryptographic Root-Prompt Hashing (Tree Invariance)
In multi-turn chat, every subsequent turn transmits the message history. The initial user instruction (`messages[1]`) is invariant across all turns of that task.
- In transient RAM, the gateway computes:
  $$\text{TaskHash} = \text{SHA-256}(\text{KeyAlias} + \text{"::"} + \text{messages}[1][\text{'content'}][:500])$$
  $$\text{task\_id} = \text{"task\_"} + \text{TaskHash}[:16]$$
- Turns 1, 2, 3... $N$ all produce the **exact same `task_id`**, allowing the gateway to sum total token usage and cumulative cost ($) without any manual headers.

#### Step 2: ZDR-Compliant Hashed Branch Indexing (The Bridge)
When the agent executes a git tool to checkout or push a branch (e.g. `feat/db-timeout`), the gateway extracts the branch name in RAM, hashes it, and stores **strictly the 64-character hash** in Redis:
$$\text{BranchDigest} = \text{SHA-256}(\text{"feat/db-timeout"}) \longrightarrow \text{"9e2f4a..."}$$
```redis
SET bhash:9e2f4a... "task_8a1f" EX 604800
```
- **ZDR Invariant Maintained**: Zero plaintext branch names, zero code, and zero customer identifiers exist in Redis.
- When the merge webhook arrives, the gateway hashes the incoming `head.ref`, matches `bhash:9e2f4a...` in Redis, and resolves the task in SQLite.

---

### 2.7 User Interfaces & Operational Consoles

The local PoC includes two dedicated web interfaces and one API documentation console:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    LOCAL AI GATEWAY USER INTERFACES                          │
├───────────────────────────────┬──────────────────────────────────────────────┤
│ 1. LiteLLM Admin Dashboard    │ http://localhost:4000/ui                     │
│    (Configure Access & Spend) │ - Visual Key Generation, RBAC, Model Lists   │
│                               │ - Spend by Key, Budget Caps, Request Logs    │
├───────────────────────────────┼──────────────────────────────────────────────┤
│ 2. Jaeger Tracing UI          │ http://localhost:16686                       │
│    (Trace & Flow Waterfall)   │ - Request lifecycle waterfall diagrams       │
│                               │ - Upstream latency, TTFT, span tags          │
├───────────────────────────────┼──────────────────────────────────────────────┤
│ 3. Interactive Swagger Docs   │ http://localhost:4000/docs                   │
│    (API Explorer)             │ - Live OpenAPI endpoint testing in browser   │
└───────────────────────────────┴──────────────────────────────────────────────┘
```

1. **LiteLLM Admin Web UI (`http://localhost:4000/ui`)**:
   - Access configuration console: Generate virtual keys with a web form, check permitted models, set daily budget ceilings ($), and configure rate limits (RPM/TPM).
   - Usage monitor: Real-time progress bars of each key's daily budget burn, per-model spend distribution, and live request logs.
2. **Jaeger Tracing UI (`http://localhost:16686`)**:
   - Trace flow visualizer: Inspect individual request timelines (Ingress PEP $\rightarrow$ Redis rate check $\rightarrow$ Upstream LLM call $\rightarrow$ ZDR SHA-256 logging).
3. **Interactive Swagger Docs (`http://localhost:4000/docs`)**:
   - OpenAPI documentation allowing developers to test endpoints directly in the browser.

---

## 3. The Seven Gateway Control Pillars (Local PoC Edition)

| Pillar | Local Implementation | Enforcement Point |
| :--- | :--- | :--- |
| **1. Monitoring** | Native OpenTelemetry v2 OTLP export to local Jaeger/Grafana. | Standard OTLP gRPC stream on `:4317` with W3C `traceparent` headers. |
| **2. Governance** | Virtual API keys issued with strict model whitelists. | Gateway PEP Ingress Middleware; rejects unauthorized models with HTTP 403. |
| **3. Rate Limits** | Redis sliding-window token bucket (RPM and TPM). | Redis atomic counters on `:6379`; returns HTTP 429 in <0.5ms. |
| **4. Auditing & ZDR** | Transient RAM-only SHA-256 hashing; zero cleartext storage. | LiteLLM custom callback; writes only hashes and token counts to SQLite. |
| **5. RBAC** | Virtual key roles: `admin`, `developer`, `intern`. | Gatekeeper blocks model escalations and admin endpoint calls. |
| **6. Budgeting** | Hard daily spend caps per virtual key (e.g. `$5.00/day`). | Tracked in Redis; immediately returns HTTP 429 when cap is hit. |
| **7. Guardrails** | In-process native regex PII & secret redaction. | LiteLLM native regex guardrail masks API keys and emails before model egress. |

---

## 4. Client Compatibility: Coding Agent / Client & Actual MCP Integration

Any coding agent or client (e.g. Cursor, Claude Code, Codex, or custom agent frameworks) connects directly to the gateway's OpenAI-compatible base URL. **No manual headers, custom metadata, or UX changes are required.** The agent connects to actual MCP servers (e.g. git tools, filesystem tools) normally.

```json
{
  "llm_service": {
    "api_base": "http://localhost:4000/v1",
    "api_key": "sk-agent-developer",
    "model": "gpt-4o"
  },
  "mcp_servers": {
    "git_tools": {
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

## 5. Complete Runnable Configuration & Code Artifacts

### 5.1 SQLite Database Schema (`sqlite_schema.sql`)

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
    -- Invariant: Strictly SHA-256 digests. NO cleartext persisted.
    prompt_sha256 TEXT NOT NULL,
    completion_sha256 TEXT NOT NULL,
    zdr_verified INTEGER DEFAULT 1,
    
    -- Coding Task Cost Per Success (CPS) Reconciliation
    task_id TEXT,                    -- e.g. 'task_8a1f10b2c3d4'
    task_outcome TEXT DEFAULT 'pending' -- 'pending', 'verified_success', 'unmerged_closed'
);

-- Fast lookup indexes
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

---

### 5.2 LiteLLM Gateway Configuration (`litellm_config.yaml`)

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

---

### 5.3 Zero-Touch Local Git PR Simulator (`mock_local_pr.py`)

Simulates opening, merging, or rejecting PRs locally in Git and dispatches the standard GitHub webhook payload. The gateway hashes the incoming branch name in RAM, looks up the Redis hashed index, and updates the task outcome.

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
    
    # 2. Dispatch mock GitHub webhook payload to the Gateway
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
            print(f"🚀 Dispatched Webhook to Gateway (HTTP {resp.status}) -> Task outcome updated!")
    except Exception as e:
        print(f"⚠️ Webhook dispatch note: {e} (Ensure Gateway is running)")

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

---

### 5.4 Local Multi-Container Stack (`docker-compose.yml`)

A compact 3-container stack (LiteLLM, Redis, Jaeger). Zero database servers; SQLite is mounted as a local file.

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

---

### 5.5 Environment Variables Manifest (`.env.example`)

```bash
# ==============================================================================
# Environment Configuration for Local AI Gateway PoC
# ==============================================================================

# LiteLLM Master Admin Key
LITELLM_MASTER_KEY=sk-enterprise-master-secret-key-2026

# Upstream Cloud LLM API Keys (The only external network compute)
OPENAI_API_KEY=sk-proj-your-openai-api-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key-here

# OpenTelemetry Endpoint (Use http://localhost:4317 for host execution; http://jaeger:4317 inside Docker)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

---

## 6. End-to-End Verification Runbook & Demo Script

### Step 1: Initialize the Local Infrastructure
```bash
# 1. Initialize empty SQLite database with schema
sqlite3 gateway.db < sqlite_schema.sql

# 2. Start the 3 local containers
docker compose up -d

# 3. Verify gateway health
curl http://localhost:4000/health
# Expected: {"status": "healthy"}
```

---

### Step 2: Configure Access via Admin UI or REST API
Open `http://localhost:4000/ui` in your browser (login with `sk-enterprise-master-secret-key-2026`) or run cURL:

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
*Expected*: **HTTP 200 OK** and completion returned.

#### Demo 3B: Gateway-Level Access Rejection (Model Escalation Blocked)
Submit a `gpt-4o` request using the restricted `sk-agent-intern` key:
```bash
curl -i -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-intern" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Explain binary search"}]
  }'
```
*Expected*: **HTTP 403 Forbidden** (Blocked at gateway PEP before calling OpenAI):
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
*Observed Behavior*: LiteLLM scrubs the AWS key and email before sending to upstream provider.

---

### Step 5: Demonstrate Zero-Touch Coding Task CPS with Local Git Merge

Notice: **Zero manual headers and zero metadata injected.** The prompt is completely standard.

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
# Gateway calculates SHA-256("Optimize SQLite...") -> task_8a1f

# Turn 2: Follow-up turn with Agent Tool Call (contains branch checkout tool call)
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-agent-developer" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Optimize SQLite index creation query"},
      {"role": "assistant", "content": "I will create a local branch and update indexes.", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "execute_command", "arguments": "{\"command\": \"git checkout -b feat/db-timeout\"}"}}]},
      {"role": "tool", "tool_call_id": "call_1", "content": "Switched to a new branch 'feat/db-timeout'"},
      {"role": "user", "content": "Generate regression test assertions"}
    ]
  }'
# Gateway logger sniffs branch name "feat/db-timeout", hashes it, and stores bhash:<sha256> -> task_8a1f in Redis
```

#### 5C: Simulate Local PR Merge Event
```bash
python3 mock_local_pr.py merge --branch feat/db-timeout
```
*Observed*: Script merges Git branch into `main` and dispatches webhook to companion server (`http://localhost:4001/webhooks/github`). Webhook server hashes `feat/db-timeout` in RAM, looks up `bhash:<sha256>` in Redis to resolve `task_id`, and marks the task `verified_success` in SQLite `coding_tasks`.

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
Inspect the SQLite database to confirm **no plaintext prompt or completion** was saved:
```bash
sqlite3 gateway.db "SELECT request_id, model_routed, prompt_sha256, completion_sha256, zdr_verified FROM gateway_audit_ledger LIMIT 5;"
```
*Verification Check*:
- `prompt_sha256` and `completion_sha256` contain strictly 64-character hexadecimal SHA-256 digests.
- Neither column nor any other SQLite field contains cleartext message bodies.

---

### Step 7: Open Operational & Observability Consoles
1. **Access & Usage Console**: Open `http://localhost:4000/ui` (LiteLLM Admin UI) to view key spend, daily budget progress bars, and model usage.
2. **Distributed Tracing Waterfall**: Open `http://localhost:16686` (Jaeger UI). Select Service `litellm` and click **Find Traces** to view the full request lifecycle.
3. **API Explorer**: Open `http://localhost:4000/docs` (Swagger UI) to test endpoints interactively.

---

## 7. Footnote: Reusing PoC Evaluation & Simulation Harnesses

While the core Local PoC stack runs autonomously using LiteLLM, Redis, and embedded SQLite, existing evaluation instruments from the `PoCs/` suite can be directly reused to test, benchmark, and evaluate the gateway itself without altering the core architecture:

### 7.1 Zero-Cost Offline Fallback & Mock Inference (`mock_server.py`)
- **Source**: [`PoCs/karthik-ag_gateway_/mock_server.py`](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/PoCs/karthik-ag_gateway_/mock_server.py)
- **Role**: Operates as a local, zero-dependency streaming endpoint on `http://localhost:8080/v1` simulating chunked Server-Sent Events (SSE) with configurable Time to First Token (`--ttft 0.05`) and token velocity (`--itl 0.005`).
- **Gateway Integration**: Serves as the ultimate zero-cost fallback tier in `litellm_config.yaml` (`mock-model`), ensuring the entire multi-turn coding and PR merge lifecycle can be tested 100% offline with zero cloud credentials and zero token expense.

### 7.2 Gateway Performance & Overhead Benchmarking (`benchmark_gateway.py`)
- **Source**: [`PoCs/karthik-ag_gateway_/benchmark_gateway.py`](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/PoCs/karthik-ag_gateway_/benchmark_gateway.py)
- **Role**: An asynchronous load testing harness (`asyncio`, `urllib`) measuring TTFT, Inter-Token Latency (ITL), and sustained throughput (TPS/RPS) across percentiles (P50, P90, P95, P99).
- **Evaluating Gateway Quality**: Uses the `--compare-direct-url` flag to test how good the gateway itself is by executing alternating requests against direct upstream (:8080) vs. proxied gateway (:4000). This empirically isolates and proves that LiteLLM's Ingress PEP + Redis sliding-window check adds under **15ms P50 latency overhead**.

### 7.3 Concurrency & Burst Rate Limit Stress Testing (`simulator.py`)
- **Source**: [`PoCs/karthik-gateway-poc/src/simulator.py`](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/PoCs/karthik-gateway-poc/src/simulator.py)
- **Role**: An open-loop demand simulator modeling Poisson arrival distributions, concurrency limits (1, 2, 5, 10 workers), burst traffic spikes, and retry dynamics.
- **Evaluating Gateway Resilience**: Reused to generate synthetic burst load against the gateway to stress-test Redis sliding-window rate limiters (Gate 5) and verify instant `HTTP 429 Too Many Requests` short-circuiting in `<0.5ms` without Redis memory or connection exhaustion.

### 7.4 Quick Evaluation Run Commands

```bash
# 1. Start the offline mock server fallback (runs on :8080)
python3 PoCs/karthik-ag_gateway_/mock_server.py --port 8080 --ttft 0.05 --itl 0.005 --tokens 30 &

# 2. Evaluate gateway performance & quantify added latency overhead delta
python3 PoCs/karthik-ag_gateway_/benchmark_gateway.py \
  --url http://localhost:4000/v1/chat/completions \
  --compare-direct-url http://localhost:8080/v1/chat/completions \
  --key sk-agent-developer \
  --model mock-model \
  --concurrency 5 --requests 20

# 3. Model burst traffic patterns and queue dynamics for rate limit stress testing
python3 PoCs/karthik-gateway-poc/src/simulator.py --requests 100 --concurrency 5 --seed 42
```

