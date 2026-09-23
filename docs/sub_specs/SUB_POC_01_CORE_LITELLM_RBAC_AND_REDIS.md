# Sub-specification — SUB-POC-01: Core LiteLLM Gateway Control Plane, RBAC & Redis Engine

**Parent Spec:** [SPEC_AI_GATEWAY_LOCAL_POC.md](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/SPEC_AI_GATEWAY_LOCAL_POC.md)  
**Sub-spec ID:** SUB-POC-01  
**Status:** Approved Baseline  
**Date:** September 2026  
**Classification:** Control Plane Ingress, Identity Governance & In-Memory State  

---

## 1. Objective

Define the architecture, request lifecycle, authentication pipeline, and in-memory state mechanics for the **LiteLLM Core Gateway Plane** and **Redis 7 Engine** within the Local AI Gateway PoC. 

This sub-specification establishes:
1. The **Gateway Policy Enforcement Point (PEP)** operating as an ingress middleware on `http://localhost:4000`.
2. **Gateway-Level Role-Based Access Control (RBAC)**, which strictly enforces model whitelisting, administrative route protection, and budget ceilings *before* any upstream model dispatch occurs.
3. The **4-Role Redis 7 In-Memory State Engine** operating on `:6379`, providing sub-millisecond rate limiting, atomic financial spend tracking, virtual key caching, and ephemeral ZDR branch hash index mapping.
4. Administrative key management interfaces via the native LiteLLM Admin Web UI (`:4000/ui`) and REST API.

---

## 2. Scope & Non-Goals

### 2.1 In Scope
- **Reverse Proxy Ingress Engine**: Interception and standard OpenAI schema mediation on `POST /v1/chat/completions`.
- **Gateway Policy Enforcement Point (PEP)**: 5-gate pipeline evaluating key validity, expiration, route authorization, model whitelisting, and financial budget caps.
- **Model-Level RBAC**: Cryptographic binding of virtual bearer keys (`sk-agent-...`) to specific model allowances (e.g. `gpt-4o` vs `gpt-4o-mini`).
- **Administrative Endpoint Authorization**: Restricting `/key/*`, `/team/*`, and `/spend/*` to callers holding the `proxy_admin` role (`LITELLM_MASTER_KEY`).
- **Redis 7 State Engine Operations**:
  - Sliding-window rate limiting (RPM/TPM) executed in `<0.5ms` via atomic Redis counters.
  - Atomic real-time spend accumulation and budget cap triggers via `INCRBYFLOAT`.
  - In-memory virtual key and policy caching to avoid persistent storage overhead on ingress.
  - Ephemeral ZDR Hashed Branch Registry storing strictly cryptographic hashes (`bhash:<sha256> -> task_id`).
- **LiteLLM Admin UI**: Configuration and operational monitoring on `http://localhost:4000/ui`.

### 2.2 Non-Goals
- Persistent audit ledger storage or disk I/O (delegated to SQLite in [SUB-POC-02](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md)).
- OpenTelemetry span collection, Jaeger tracing, and Grafana dashboarding (delegated to [SUB-POC-02](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_02_SQLITE_OBSERVABILITY_AND_ZDR.md)).
- Docker Compose multi-container deployment orchestration and mock servers (delegated to [SUB-POC-03](file:///Users/mako/Mukesh_Workspace/Projects/Extras:Test/LLM%20Gateway/docs/sub_specs/SUB_POC_03_CONFIGS_MOCK_FILES_AND_EXTRAS.md)).
- Client-side application modifications (coding agents connect via standard OpenAI client libraries with zero custom headers).

---

## 3. Functional Requirements

| ID | Requirement | Master Spec Source | Priority |
| :--- | :--- | :--- | :--- |
| **REQ-CORE-01** | The gateway MUST expose an OpenAI-compatible reverse proxy endpoint at `POST /v1/chat/completions` on port `4000`. | §2.1 LiteLLM Core Gateway Plane | Must |
| **REQ-CORE-02** | The Gateway Ingress PEP MUST execute authentication and authorization verification gates in memory *before* payload parameter parsing or model routing. | §2.2 Gateway-Level RBAC | Must |
| **REQ-CORE-03** | The gateway MUST enforce model whitelisting per virtual API key. If a caller requests a model not explicitly listed in their key's `models` array, the gateway MUST return `HTTP 403 Forbidden` with error code `model_not_allowed`. | §2.2 Gate 2 (Model Whitelisting) | Must |
| **REQ-CORE-04** | Administrative endpoints (`/key/generate`, `/key/delete`, `/team/new`, `/spend`) MUST strictly require authentication via `LITELLM_MASTER_KEY` (`proxy_admin` role). Unauthorized callers MUST receive `HTTP 403 Forbidden`. | §2.2 Gate 3 (Admin Route Auth) | Must |
| **REQ-CORE-05** | The gateway MUST track key expenditure against `max_budget` in real-time. If cumulative spend reaches or exceeds the threshold, subsequent requests MUST be immediately rejected with `HTTP 429 Quota Exceeded`. | §2.2 Gate 4 (Budget Ceilings) | Must |
| **REQ-CORE-06** | The gateway MUST utilize Redis 7 sliding windows to meter RPM (Requests Per Minute) and TPM (Tokens Per Minute) per key and per model with `<0.5ms` evaluation latency. | §2.3 Redis Op 1 (Sliding Windows) | Must |
| **REQ-CORE-07** | The gateway MUST execute atomic `INCRBYFLOAT` operations in Redis upon completion of every inference turn to maintain cumulative spend across concurrent requests. | §2.3 Redis Op 2 (Spend Tracking) | Must |
| **REQ-CORE-08** | Virtual key definitions, model lists, and budget caps MUST be cached in Redis (`litellm:keys:<key_hash>`) with instant invalidation upon administrative mutation. | §2.3 Redis Op 3 (Policy Cache) | Must |
| **REQ-CORE-09** | The gateway MUST provide a ZDR-compliant ephemeral branch registry in Redis (`bhash:<sha256> -> task_id`) with a 7-day TTL, storing strictly 64-character SHA-256 digests and zero plaintext strings. | §2.3 Redis Op 4 (Branch Registry) | Must |
| **REQ-CORE-10** | The gateway MUST host an interactive Web Admin Console on `http://localhost:4000/ui` protected by `LITELLM_MASTER_KEY` for visual key generation, model policy assignments, and live budget monitoring. | §2.7 User Interfaces | Must |

---

## 4. Architecture & Enforcement Mechanics

### 4.1 The 5 Ingress Policy Enforcement Gates

Every incoming request to `POST /v1/chat/completions` or administrative endpoints must pass through the Ingress PEP middleware. If any gate fails, execution is halted immediately and an HTTP error is returned without consuming downstream model tokens or triggering database writes:

```mermaid
flowchart TD
    ClientReq["Incoming HTTP Request\nPOST /v1/chat/completions\nAuthorization: Bearer sk-agent-xxx\nModel: gpt-4o"]
    
    subgraph GatewayPEP["Gateway Policy Enforcement Point (PEP) Ingress Middleware"]
        Gate1{"Gate 1: Key Authentication\nIs Bearer token present and active in Redis cache?"}
        Gate2{"Gate 2: Route Authorization\nIs caller accessing Admin Routes (/key, /team)\nwithout proxy_admin role?"}
        Gate3{"Gate 3: Model Whitelist Check\nIs requested model in Key's 'models' array?"}
        Gate4{"Gate 4: Budget Ceiling Check\nHas key exceeded 'max_budget'?"}
        Gate5{"Gate 5: Rate Limit Check\nIs RPM or TPM exceeded in Redis sliding window?"}
    end

    Allow["✅ ALLOW: Forward to Native Guardrail & Model Router"]
    Reject401["❌ HTTP 401 Unauthorized\n(Invalid or expired API Key)"]
    Reject403_Admin["❌ HTTP 403 Forbidden\n(Admin route requires proxy_admin role)"]
    Reject403_Model["❌ HTTP 403 Forbidden\n(Model 'gpt-4o' not allowed for key role 'intern')"]
    Reject429_Budget["❌ HTTP 429 Quota Exceeded\n(Budget ceiling $5.00 reached)"]
    Reject429_Rate["❌ HTTP 429 Too Many Requests\n(Rate limit exceeded in sliding window)"]

    ClientReq --> Gate1
    Gate1 -- No --> Reject401
    Gate1 -- Yes --> Gate2
    Gate2 -- Yes (Unauthorized Admin) --> Reject403_Admin
    Gate2 -- No (Authorized) --> Gate3
    Gate3 -- No --> Reject403_Model
    Gate3 -- Yes --> Gate4
    Gate4 -- Exceeded --> Reject429_Budget
    Gate4 -- OK --> Gate5
    Gate5 -- Exceeded --> Reject429_Rate
    Gate5 -- OK --> Allow
```

### 4.2 Role-Based Access Control (RBAC) Matrix

Virtual API keys represent distinct actor roles. Model routing, spend limits, and administrative privileges are defined strictly by role:

| Caller Role | Key Alias Pattern | Permitted Models (`models: [...]`) | Admin Route Access (`/key/*`, `/team/*`) | Default Daily Budget | Default RPM / TPM |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`proxy_admin`** | Master Key (`LITELLM_MASTER_KEY`) | All registered models (`*`) | Full Read/Write | Unlimited | Unlimited |
| **`developer`** | `sk-agent-developer-*` | `["gpt-4o", "claude-3-5-sonnet", "mock-model"]` | Blocked (`HTTP 403`) | `$5.00 / day` | 30 RPM / 60,000 TPM |
| **`intern`** | `sk-agent-intern-*` | `["gpt-4o-mini", "mock-model"]` | Blocked (`HTTP 403`) | `$1.00 / day` | 100 RPM / 120,000 TPM |
| **`ci_pipeline`** | `sk-agent-ci-*` | `["gpt-4o-mini", "mock-model"]` | Blocked (`HTTP 403`) | `$2.00 / day` | 60 RPM / 80,000 TPM |

---

## 5. Where & How Redis Is Used in the Gateway

Redis 7 runs as a high-performance in-memory state engine on port `6379`. To guarantee sub-millisecond overhead on every inference request, Redis serves four dedicated architectural roles:

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

### 5.1 Operation 1: Sliding-Window Rate Limiting (RPM / TPM)
- **Key Namespace**: `litellm:ratelimit:<key_hash>:<window_timestamp>`
- **Data Structure**: Redis String / Hash with TTL
- **Mechanics**:
  1. Gateway computes current 60-second window identifier: `window = floor(current_unix_time / 60)`.
  2. Executes atomic multi-command:
     ```redis
     INCR litellm:ratelimit:sk_dev_123:rpm:1727092800
     EXPIRE litellm:ratelimit:sk_dev_123:rpm:1727092800 120
     ```
  3. If counter exceeds configured limit (e.g. 30), gateway short-circuits request with `HTTP 429`. Total evaluation time: `<0.4ms`.

### 5.2 Operation 2: Real-Time Spend Tracking & Budget Ceilings
- **Key Namespace**: `litellm:spend:<key_hash>`
- **Data Structure**: Redis Float String
- **Mechanics**:
  1. On ingress Gate 4, gateway issues `GET litellm:spend:<key_hash>`.
  2. If `spend >= max_budget`, request is rejected with `HTTP 429 Quota Exceeded`.
  3. When an upstream model response completes, LiteLLM calculates cost using the active token rate card and executes:
     ```redis
     INCRBYFLOAT litellm:spend:<key_hash> 0.004250
     ```
  4. Keys configured with `duration: 1d` automatically have daily expiry TTL or reset triggers applied.

### 5.3 Operation 3: Virtual Key & Policy Caching
- **Key Namespace**: `litellm:keys:<key_hash>`
- **Data Structure**: Redis Hash
- **Mechanics**:
  - Stores serialised key metadata: `{"role": "developer", "models": ["gpt-4o", "claude-3-5-sonnet"], "max_budget": 5.0}`.
  - Eliminates persistent database reads on ingress.
  - Cache is proactively updated or invalidated upon `POST /key/update` or `POST /key/delete`.

### 5.4 Operation 4: ZDR Hashed Branch Registry
- **Key Namespace**: `bhash:<sha256_digest>`
- **Data Structure**: Redis String (Key: 64-character hex, Value: string `task_id`)
- **TTL**: 604,800 seconds (7 days)
- **Mechanics**:
  1. When an agent creates or references a Git branch (e.g. `feat/db-timeout`), the gateway's custom callback hook (`custom_zdr_logger.py`) inspects incoming `messages` and outbound `tool_calls` for Git branch operations:
     - Regex patterns: `(?i)git\s+(?:checkout\s+-b|branch|switch\s+-c)\s+([a-zA-Z0-9_\-\.\/]+)` and `(?i)git\s+push\s+[^\s]+\s+([a-zA-Z0-9_\-\.\/]+)`.
  2. Upon detecting a branch name, the hook computes the cryptographic digest in transient memory:
     $$\text{BranchDigest} = \text{SHA-256}(\text{"feat/db-timeout"}) = \text{"9e2f4a..."}$$
  3. The hook associates this digest with the active multi-turn `task_id` (derived via root-prompt hashing) and executes in Redis:
     ```redis
     SET bhash:9e2f4a... "task_8a1f10b2c3d4" EX 604800
     ```
  4. **Zero Plaintext Invariant**: The branch name `feat/db-timeout` is never stored in Redis. Only the one-way SHA-256 digest is maintained.

---

## 6. API Contracts & Error Responses

### 6.1 Key Provisioning Contract (`POST /key/generate`)
Requires `Authorization: Bearer <LITELLM_MASTER_KEY>`. Passing explicit `"key"` guarantees the virtual key string matches the alias for developer client configuration.

```http
POST /key/generate HTTP/1.1
Host: localhost:4000
Authorization: Bearer sk-enterprise-master-secret-key-2026
Content-Type: application/json

{
  "key": "sk-agent-developer",
  "key_alias": "sk-agent-developer",
  "models": ["gpt-4o", "claude-3-5-sonnet", "mock-model"],
  "max_budget": 5.0,
  "duration": "1d",
  "metadata": {
    "role": "developer",
    "team": "core-backend"
  }
}
```

**Success Response (HTTP 200 OK):**
```json
{
  "key": "sk-agent-developer",
  "key_alias": "sk-agent-developer",
  "max_budget": 5.0,
  "models": ["gpt-4o", "claude-3-5-sonnet", "mock-model"],
  "expires": "2026-09-24T17:00:00Z"
}
```

### 6.2 Error Payloads

#### Gate 1 Failure: HTTP 401 Unauthorized
```json
{
  "error": {
    "message": "Invalid or missing Bearer API key in Authorization header.",
    "type": "authentication_error",
    "code": "invalid_api_key"
  }
}
```

#### Gate 2 Failure: HTTP 403 Forbidden (Admin Route Protection)
```json
{
  "error": {
    "message": "Access to administrative route '/key/generate' requires proxy_admin privileges.",
    "type": "permission_error",
    "code": "admin_required"
  }
}
```

#### Gate 3 Failure: HTTP 403 Forbidden (Model Whitelist Rejection)
```json
{
  "error": {
    "message": "Model 'gpt-4o' not allowed for key 'sk-agent-intern'. Allowed models: ['gpt-4o-mini', 'mock-model']",
    "type": "permission_error",
    "code": "model_not_allowed"
  }
}
```

#### Gate 4 Failure: HTTP 429 Quota Exceeded (Daily Budget Cap Reached)
```json
{
  "error": {
    "message": "Key 'sk-agent-developer' has exceeded its budget ceiling of $5.00 (Current spend: $5.0042).",
    "type": "budget_exceeded_error",
    "code": "budget_exceeded"
  }
}
```

#### Gate 5 Failure: HTTP 429 Too Many Requests (Rate Limit Exceeded)
```json
{
  "error": {
    "message": "Rate limit exceeded for model 'gpt-4o'. Key limit: 30 RPM.",
    "type": "rate_limit_error",
    "code": "rate_limit_exceeded"
  }
}
```

---

## 7. Acceptance Criteria & Verification Plan

| AC ID | Target Requirement | Verification Method | Expected Status | Assertion Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **AC-CORE-01** | **REQ-CORE-01** | `curl http://localhost:4000/health` | `HTTP 200 OK` | Body contains `{"status": "healthy"}` |
| **AC-CORE-02** | **REQ-CORE-02** | `curl -X POST http://localhost:4000/v1/chat/completions` (no key) | `HTTP 401` | Error code `invalid_api_key`; short-circuited before routing |
| **AC-CORE-03** | **REQ-CORE-03** | `curl -X POST ... -H "Authorization: Bearer sk-agent-developer" -d '{"model": "gpt-4o", ...}'` | `HTTP 200 OK` | Valid OpenAI chat completion returned for allowed model |
| **AC-CORE-04** | **REQ-CORE-03** | `curl -X POST ... -H "Authorization: Bearer sk-agent-intern" -d '{"model": "gpt-4o", ...}'` | `HTTP 403` | Error code `model_not_allowed`; upstream LLM never called |
| **AC-CORE-05** | **REQ-CORE-04** | `curl -X POST http://localhost:4000/key/generate -H "Authorization: Bearer sk-agent-developer" -d '{}'` | `HTTP 403` | Non-admin key rejected with `admin_required` error |
| **AC-CORE-06** | **REQ-CORE-06** | Flood 35 requests within 10 seconds using a 30 RPM key | `HTTP 429` | Requests 1–30 succeed; requests 31+ receive `rate_limit_exceeded` in <0.5ms |
| **AC-CORE-07** | **REQ-CORE-07** | Query `redis-cli GET litellm:spend:<key>` after inference completion | N/A | Spend counter increases atomically by exact calculated cost |
| **AC-CORE-08** | **REQ-CORE-08** | Mutate key model list via admin API and query immediately | `HTTP 403` | Redis cache `litellm:keys:<hash>` immediately invalidates; changed permissions take effect on next turn |
| **AC-CORE-09** | **REQ-CORE-09** | Run agent turn with `git checkout -b feat/test`; check Redis | N/A | Key `bhash:<sha256("feat/test")>` created in Redis with 7-day TTL; zero plaintext branch name |
| **AC-CORE-10** | **REQ-CORE-10** | Authenticate to `http://localhost:4000/ui` with `LITELLM_MASTER_KEY` | `HTTP 200 OK` | LiteLLM Admin UI dashboard loads, displaying active keys, models, and spend meters |

---

## 8. Master Spec Traceability Matrix

| Master Specification Section | Traceability & Scope Alignment in SUB-POC-01 |
| :--- | :--- |
| **§1.2 Architecture Stack (Layer 2 & 4)** | LiteLLM Runtime/Orchestration plane and Redis Memory/State engine. |
| **§1.3 Local Topology Blueprint** | Ingress PEP, AuthPEP, ModelRouter, and Redis component interactions. |
| **§2.1 LiteLLM Core Gateway Plane** | Port allocations, reverse proxy mechanics, and container setup. |
| **§2.2 Gateway-Level RBAC Engine** | 5 Verification Gates, model whitelisting (`model_not_allowed`), and admin route controls. |
| **§2.3 Where & How Redis Is Used** | Sliding-window RPM/TPM, atomic spend tracking, key caching, and hashed branch registry. |
| **§2.7 Operational Consoles** | LiteLLM Admin UI (`:4000/ui`) and Swagger Docs (`:4000/docs`). |
| **§3.2 Governance & §3.5 RBAC** | Virtual key issuance, model whitelist policy matrix, and role hierarchy. |
| **§3.3 Rate Limits & §3.6 Budgeting** | Sliding-window token buckets and real-time dollar caps. |
