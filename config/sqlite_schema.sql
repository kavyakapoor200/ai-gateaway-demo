-- =============================================================================
-- Minimal Local AI Gateway: Single-Table SQLite Ledger & Analytical Views
-- Compliant with SUB-POC-02: SQLite Ledger, Observability & Cryptographic ZDR
-- =============================================================================

-- WAL Concurrency & Performance PRAGMAs
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA cache_size = -64000; -- 64MB cache
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- Single-Table Audit & CPS Ledger
-- -----------------------------------------------------------------------------
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
    task_outcome TEXT DEFAULT 'pending', -- 'pending', 'verified_success', 'unmerged_closed'

    -- Tool Governance & Policy Intercepts (CISO Observability)
    policy_action TEXT DEFAULT NULL,   -- 'strict_reject', 'filter'
    violating_tools TEXT DEFAULT NULL  -- JSON array of tool names, e.g. '["execute_command", "drop_table"]'
);

-- Fast lookup indexes
CREATE INDEX IF NOT EXISTS idx_trace_id ON gateway_audit_ledger(trace_id);
CREATE INDEX IF NOT EXISTS idx_task_id ON gateway_audit_ledger(task_id);
CREATE INDEX IF NOT EXISTS idx_created_at ON gateway_audit_ledger(created_at);
CREATE INDEX IF NOT EXISTS idx_policy_action ON gateway_audit_ledger(policy_action);

-- -----------------------------------------------------------------------------
-- Analytical View: Real-Time Coding CPS Summary
-- -----------------------------------------------------------------------------
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

-- -----------------------------------------------------------------------------
-- Analytical View: Automated ZDR Compliance Audit
-- -----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_zdr_compliance_check AS
SELECT 
    COUNT(*) AS total_records,
    SUM(CASE WHEN LENGTH(prompt_sha256) = 64 AND prompt_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END) AS valid_prompt_hashes,
    SUM(CASE WHEN LENGTH(completion_sha256) = 64 AND completion_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END) AS valid_completion_hashes,
    SUM(CASE WHEN zdr_verified = 1 THEN 1 ELSE 0 END) AS zdr_flags_valid,
    CASE 
        WHEN COUNT(*) = 0 THEN 'NO RECORDS YET'
        WHEN COUNT(*) = SUM(CASE WHEN LENGTH(prompt_sha256) = 64 AND prompt_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END)
         AND COUNT(*) = SUM(CASE WHEN LENGTH(completion_sha256) = 64 AND completion_sha256 GLOB '[0-9a-f]*' THEN 1 ELSE 0 END)
        THEN '100% COMPLIANT - ZERO PLAINTEXT DETECTED'
        ELSE 'VIOLATION DETECTED - AUDIT REQUIRED'
    END AS compliance_status
FROM gateway_audit_ledger;
