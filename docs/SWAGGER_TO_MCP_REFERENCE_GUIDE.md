# Engineering Reference Guide: Converting Swagger / OpenAPI to MCP Servers

> **Document Type:** Operational Ready-Reference & Decision Framework  
> **Target Audience:** Engineering Leads, Platform Teams, and AI Engineers  
> **Scope:** Converting Swagger / OpenAPI specifications into Model Context Protocol (MCP) servers using **LiteLLM** (Gateway / Config-Driven) and **FastMCP** (Code-First / Framework)  

---

## 1. Executive Summary

When product or backend engineering teams provide an existing Swagger UI / OpenAPI documentation and request MCP enablement, the goal is to expose backend endpoints as structured tools that LLM agents (e.g., Claude Desktop, Cursor, internal agents) can safely discover and invoke.

Converting an API spec to an MCP server is **not one-size-fits-all**. Depending on authentication complexity, data transformation needs, and timeline, teams must select between:

1. **LiteLLM Native Track (Config-Driven):** Direct OpenAPI-to-MCP synthesis inside the AI Gateway. Ideal for standard REST APIs with header-based auth and zero custom middleware requirements.
2. **FastMCP Track (Code-First):** Dedicated Python MCP server using the FastMCP framework. Ideal when requests need payload sanitation, dynamic token refresh (OAuth/OIDC), complex response filtering, or multi-step tool logic before reaching upstream services.

---

## 2. High-Level Architectural Flow

```
                      ┌──────────────────────────────────────────────┐
                      │   Client Layer (Claude, Cursor, AI Agents)   │
                      └──────────────────────┬───────────────────────┘
                                             │ JSON-RPC / SSE
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │        Enterprise AI Gateway (:4000)         │
                      │  • RBAC & Virtual API Keys                   │
                      │  • Zero Data Retention (ZDR)                 │
                      │  • Audit Logging & Tool Whitelisting         │
                      └──────────────┬───────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 │                                       │
                 ▼ Track A (Config)                      ▼ Track B (Code)
       ┌───────────────────┐                   ┌───────────────────┐
       │      LiteLLM      │                   │      FastMCP      │
       │  In-Memory MCP    │                   │ Standalone Server │
       │  Auto-synthesizer │                   │ (Port 8005 / SSE) │
       └─────────┬─────────┘                   └─────────┬─────────┘
                 │ Direct HTTP                           │ Programmatic HTTP
                 │                                       │ (Auth, Transform)
                 └───────────────────┬───────────────────┘
                                     ▼
                      ┌──────────────────────────────┐
                      │   Upstream REST / Microservice│
                      └──────────────────────────────┘
```

---

## 3. Decision Matrix: LiteLLM vs. FastMCP

| Decision Factor | Track A: LiteLLM (Config-Driven) | Track B: FastMCP (Code-First) |
| :--- | :--- | :--- |
| **Primary Paradigm** | Declarative configuration (`yaml`) | Procedural Python code (`FastMCP` SDK) |
| **Implementation Effort** | **Minimal** (15–30 minutes) | **Moderate** (1–4 hours) |
| **Authentication Support** | Static API keys, static Bearer tokens, environment variables | Complex auth: OAuth2 flows, AWS SigV4, per-user JWT delegation, rotating tokens |
| **Payload Filtering** | Pass-through (full upstream response forwarded to LLM) | Custom pruning (extract only relevant fields to conserve token budget) |
| **Tool Customization** | 1:1 mapping of endpoint `operationId` to MCP tool | Ability to combine 3 REST calls into 1 atomic MCP tool, or add input guards |
| **Deployment Footprint** | Embedded directly in LiteLLM container | Independent container / microservice running SSE or stdio |
| **Governance & Policies** | Managed natively via Gateway RBAC rules | Governed either at Gateway ingress or inside FastMCP handler logic |
| **Maintenance Overhead** | Nearly zero code to maintain | Python dependency updates, server health monitoring |

### Quick Rule of Thumb:
- **Choose LiteLLM if:** The API is standard REST, uses simple API keys, responses are relatively compact, and you want zero code maintenance.
- **Choose FastMCP if:** You must redact sensitive PII fields, shrink massive JSON responses before the LLM sees them, or authenticate using dynamic user sessions.

---

## 4. Phase 0: Pre-Flight Spec Readiness Checklist

Regardless of the selected track, raw Swagger UI specs frequently fail when converted directly to MCP without pre-flight sanitization. Verify the following before implementation:

- [ ] **OpenAPI 3.x Standard:** Ensure the spec is OpenAPI 3.0+ (if legacy Swagger 2.0, convert using standard tooling prior to ingestion).
- [ ] **Operation ID Hygiene:** Every endpoint path must have a unique `operationId`.
  - **Crucial Rule:** MCP tool names strictly forbid slashes (`/`), dashes (`-`), and spaces. Replace with clean underscores (e.g., `list_issues`, not `issues/list-all`).
- [ ] **Tool Budget Pruning:** Production APIs often have 100+ endpoints. Exposing 100 tools destroys LLM attention and exhausts context tokens.
  - **Target:** Prune spec to keep only the **top 10–25 high-value tools** needed by the agent.
- [ ] **Component References (`$ref`):** Ensure all JSON schemas referenced in pruned paths remain intact within the `components/schemas` block to prevent parsing errors.
- [ ] **Clear Parameter Descriptions:** Verify that input parameters have descriptive `description` fields; LLMs rely on these descriptions to decide which tool to trigger.

---

## 5. Track A: LiteLLM Implementation Blueprint

### How It Works
LiteLLM dynamically reads the OpenAPI spec file at launch, iterates through defined endpoints, parses path parameters and JSON bodies into JSON-RPC tool schemas, and registers them directly in gateway memory under `/mcp`.

### Core Setup Steps
1. **Sanitize & Vendor:** Place the sanitized OpenAPI JSON/YAML in the gateway specs directory.
2. **Gateway Configuration:**
   - Define a new MCP server entry pointing to the local specification file.
   - Set the upstream `base_url` pointing to the real or mock backend service.
   - Configure authorization header mapping referencing environment secrets.
3. **Restart / Deploy Gateway:** LiteLLM exposes the synthesized tools immediately under the unified `/mcp` JSON-RPC endpoint.
4. **Client Verification:** Connect client (e.g., Claude Desktop, Cursor) through the standard gateway URL with the allocated Virtual Key.

### Key Advantages
- Instant turnaround for incoming requests.
- Gateway handles token metrics, user rate-limiting, and RBAC out of the box.
- Zero extra server processes to manage.

---

## 6. Track B: FastMCP Implementation Blueprint

### How It Works
FastMCP is a specialized, lightweight framework designed specifically for building MCP servers. The spec is loaded in Python, giving the engineer complete lifecycle hooks over each tool request and response before sending it back over SSE or stdio.

### Core Setup Steps
1. **Initialize FastMCP Service:**
   - Instantiate a FastMCP server instance configured for Server-Sent Events (SSE) or stdio transport.
2. **Register Tools Programmatically:**
   - Ingest the OpenAPI spec using `FastMCP.from_openapi` or custom Python decorators (`@mcp.tool`).
   - Configure HTTP client (`httpx`) with custom timeouts, connection pooling, and retry policies.
3. **Implement Middleware & Handlers:**
   - Inject dynamic auth tokens (e.g., fetching a fresh OAuth bearer token per request).
   - Strip unnecessary fields from API payloads (e.g., removing nested metadata, timestamps, and redundant IDs to minimize context window consumption).
4. **Deploy & Bind to AI Gateway:**
   - Run the FastMCP service as a container on its designated port (e.g., `:8005`).
   - Register the FastMCP SSE endpoint in the central AI Gateway configuration so clients access all tools uniformly through `:4000/mcp`.

### Key Advantages
- Complete observability and custom error messages tailored for LLM reasoning.
- Deep defensive filtering (preventing sensitive backend internal fields from leaking into prompt history).
- Ability to compose complex multi-call workflows into single intuitive tools.

---

## 7. Operational Best Practices & Guardrails

### 1. Token Budget & Context Window Protection
- Endpoints returning large arrays (e.g., `GET /logs` or `GET /all-records`) can exceed context windows and trigger exorbitant LLM costs.
- Enforce mandatory `limit` and `offset` parameters or summarize outputs before returning them to the client.

### 2. Zero Data Retention (ZDR) & Compliance
- Route all MCP invocations through the AI Gateway to ensure audit logging occurs on tool names and caller identity without storing confidential payload data.

### 3. Read vs. Mutating Operations
- Group endpoints by risk level:
  - **Read-Only (GET):** Safe for automated agent execution.
  - **Mutating (POST/PUT/DELETE):** Configure gateway policy interrupts or confirmation prompts for high-blast-radius operations (e.g., deleting records, sending emails).

### 4. Error Message Structuring
- When an upstream API returns HTTP 4xx/5xx, wrap the error in a readable format (`isError: false` with friendly diagnostics or structured guidance) so the LLM understands why the call failed and can self-correct.

---

## 8. Five-Point Request Intake Checklist

When a stakeholder submits a new Swagger UI conversion request, run through this 2-minute assessment:

```
[ ] 1. SPEC SCOPE: Is the endpoint count ≤ 20, or does it require pruning?
[ ] 2. AUTHENTICATION: Is it standard Bearer/Header auth (LiteLLM) or dynamic OAuth/OIDC (FastMCP)?
[ ] 3. PAYLOAD SIZE: Does any endpoint return > 50KB JSON? (If YES → FastMCP required for trimming)
[ ] 4. NAMING: Are all operationIds sanitized (no slashes, no hyphens)?
[ ] 5. ROUTING: Should this run directly inside the AI Gateway (LiteLLM) or as an independent microservice (FastMCP)?
```
