#!/usr/bin/env python3
"""
cps_webhook_server.py: Companion Listener & Web Dashboard for Minimal Local AI Gateway.
Features:
1. Listens on port 4001 for GitHub PR merge webhooks (/webhooks/github).
2. Resolves task_id from Redis bhash:<sha256> and updates SQLite gateway.db.
3. Serves the interactive AI Gateway CPS & ZDR Observability Dashboard (GET / & GET /dashboard).
4. Serves JSON APIs: /api/stats, /api/cps, /api/audit (with ?q= or ?request_id= search support).
"""
import os
import sys
import json
import hashlib
import sqlite3
import socket
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, Any, List
from http.server import HTTPServer, BaseHTTPRequestHandler

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
PORT = int(os.environ.get("WEBHOOK_PORT", 4001))
JAEGER_HOST = os.environ.get("JAEGER_HOST", "localhost")
JAEGER_PORT = os.environ.get("JAEGER_PORT", "16686")

def get_db_path() -> str:
    if os.environ.get("DB_PATH"):
        return os.environ.get("DB_PATH")
    if os.path.exists("data/gateway.db"):
        return "data/gateway.db"
    if os.path.exists("/app/data/gateway.db"):
        return "/app/data/gateway.db"
    if os.path.exists("gateway.db"):
        return "gateway.db"
    return "data/gateway.db"

def query_redis_branch(branch_name: str) -> Optional[str]:
    """Queries Redis directly via socket / RESP protocol for bhash:<sha256>."""
    bhash = hashlib.sha256(branch_name.encode("utf-8")).hexdigest()
    key = f"bhash:{bhash}"
    cmd = f"*2\r\n$3\r\nGET\r\n${len(key)}\r\n{key}\r\n".encode("utf-8")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((REDIS_HOST, REDIS_PORT))
        s.sendall(cmd)
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        lines = resp.split("\r\n")
        if len(lines) >= 2 and lines[0].startswith("$") and int(lines[0][1:]) > 0:
            return lines[1]
    except Exception as e:
        print(f"[!] Redis lookup error: {e}", file=sys.stderr)
    return None

def get_db_stats() -> Dict[str, Any]:
    db_path = get_db_path()
    stats = {
        "total_records": 0,
        "total_tasks": 0,
        "verified_tasks": 0,
        "total_spend": 0.0,
        "avg_cps": 0.0,
        "fully_loaded_cps": 0.0,
        "success_rate": 0.0,
        "spend_by_outcome": {
            "merged": 0.0,
            "closed_unmerged": 0.0,
            "pending": 0.0,
            "blocked_by_policy": 0.0,
            "other": 0.0
        },
        "zdr_status": "UNKNOWN"
    }
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # ZDR compliance
        cur.execute("SELECT * FROM v_zdr_compliance_check")
        zdr_row = cur.fetchone()
        if zdr_row:
            stats["total_records"] = zdr_row["total_records"] or 0
            stats["zdr_status"] = zdr_row["compliance_status"] or "COMPLIANT"

        # 1. Existing Nominal CPS (kept unchanged from v_coding_cps_summary as instructed)
        cur.execute("""
            SELECT 
                COUNT(*) AS total_tasks,
                SUM(CASE WHEN task_outcome = 'verified_success' THEN 1 ELSE 0 END) AS verified_tasks,
                ROUND(SUM(accumulated_cost_usd), 6) AS total_spend,
                ROUND(AVG(final_cps_usd), 6) AS avg_cps
            FROM v_coding_cps_summary
        """)
        s_row = cur.fetchone()
        nominal_avg_cps = 0.0
        if s_row:
            nominal_avg_cps = s_row["avg_cps"] or 0.0
        stats["avg_cps"] = nominal_avg_cps

        # Total spend across all ledger records (including any untracked rows)
        cur.execute("SELECT ROUND(COALESCE(SUM(cost_usd), 0.0), 6) AS total_ledger_spend FROM gateway_audit_ledger")
        t_row = cur.fetchone()
        if t_row and t_row["total_ledger_spend"] is not None:
            stats["total_spend"] = float(t_row["total_ledger_spend"])

        # 2. New Task-Level Query (1 task = 1 unit, spend summed per task_id, outcome precedence)
        # Precedence: merged > closed_unmerged > blocked_by_policy > failed > pending
        # 'failed' mapped into 'closed_unmerged' as decided.
        cur.execute("""
            WITH task_aggregates AS (
                SELECT 
                    task_id,
                    SUM(cost_usd) AS task_spend,
                    CASE
                        WHEN SUM(CASE WHEN task_outcome = 'verified_success' THEN 1 ELSE 0 END) > 0 THEN 'merged'
                        WHEN SUM(CASE WHEN task_outcome = 'unmerged_closed' THEN 1 ELSE 0 END) > 0 THEN 'closed_unmerged'
                        WHEN SUM(CASE WHEN task_outcome = 'tool_policy_rejected' THEN 1 ELSE 0 END) > 0 THEN 'blocked_by_policy'
                        WHEN SUM(CASE WHEN task_outcome = 'failed' THEN 1 ELSE 0 END) > 0 THEN 'closed_unmerged'
                        WHEN SUM(CASE WHEN task_outcome = 'pending' THEN 1 ELSE 0 END) > 0 THEN 'pending'
                        ELSE 'other'
                    END AS task_resolved_outcome
                FROM gateway_audit_ledger
                WHERE task_id IS NOT NULL
                GROUP BY task_id
            )
            SELECT 
                COUNT(*) AS total_tasks_task_level,
                SUM(CASE WHEN task_resolved_outcome = 'merged' THEN 1 ELSE 0 END) AS merged_tasks_count,
                ROUND(SUM(task_spend), 6) AS all_task_spend,
                ROUND(SUM(CASE WHEN task_resolved_outcome = 'merged' THEN task_spend ELSE 0.0 END), 6) AS spend_merged,
                ROUND(SUM(CASE WHEN task_resolved_outcome = 'closed_unmerged' THEN task_spend ELSE 0.0 END), 6) AS spend_closed_unmerged,
                ROUND(SUM(CASE WHEN task_resolved_outcome = 'pending' THEN task_spend ELSE 0.0 END), 6) AS spend_pending,
                ROUND(SUM(CASE WHEN task_resolved_outcome = 'blocked_by_policy' THEN task_spend ELSE 0.0 END), 6) AS spend_blocked_by_policy,
                ROUND(SUM(CASE WHEN task_resolved_outcome = 'other' THEN task_spend ELSE 0.0 END), 6) AS spend_other
            FROM task_aggregates
        """)
        t_agg = cur.fetchone()
        
        total_tasks = 0
        merged_tasks = 0
        all_task_spend = 0.0
        spend_merged = 0.0
        spend_closed_unmerged = 0.0
        spend_pending = 0.0
        spend_blocked_by_policy = 0.0
        spend_other = 0.0

        if t_agg:
            total_tasks = t_agg["total_tasks_task_level"] or 0
            merged_tasks = t_agg["merged_tasks_count"] or 0
            all_task_spend = float(t_agg["all_task_spend"] or 0.0)
            spend_merged = float(t_agg["spend_merged"] or 0.0)
            spend_closed_unmerged = float(t_agg["spend_closed_unmerged"] or 0.0)
            spend_pending = float(t_agg["spend_pending"] or 0.0)
            spend_blocked_by_policy = float(t_agg["spend_blocked_by_policy"] or 0.0)
            spend_other = float(t_agg["spend_other"] or 0.0)

        # Check for untracked spend (task_id IS NULL) to ensure buckets strictly sum to total spend
        cur.execute("SELECT ROUND(COALESCE(SUM(cost_usd), 0.0), 6) AS untracked_spend FROM gateway_audit_ledger WHERE task_id IS NULL")
        u_row = cur.fetchone()
        untracked = float(u_row["untracked_spend"]) if u_row and u_row["untracked_spend"] else 0.0
        spend_other = round(spend_other + untracked, 6)

        stats["total_tasks"] = total_tasks
        stats["verified_tasks"] = merged_tasks
        
        # Fully-loaded CPS: all task spend / merged tasks
        if merged_tasks > 0:
            stats["fully_loaded_cps"] = round(all_task_spend / merged_tasks, 6)
        else:
            stats["fully_loaded_cps"] = 0.0

        # Success rate: merged tasks / total tasks (0.0 - 1.0 ratio)
        if total_tasks > 0:
            stats["success_rate"] = round(merged_tasks / total_tasks, 4)
        else:
            stats["success_rate"] = 0.0

        stats["spend_by_outcome"] = {
            "merged": spend_merged,
            "closed_unmerged": spend_closed_unmerged,
            "pending": spend_pending,
            "blocked_by_policy": spend_blocked_by_policy,
            "other": spend_other
        }
            
        conn.close()
    except Exception as e:
        print(f"[!] get_db_stats error: {e}", file=sys.stderr)
    return stats

def get_cps_summary() -> List[Dict[str, Any]]:
    db_path = get_db_path()
    rows = []
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM v_coding_cps_summary ORDER BY (task_outcome = 'verified_success') DESC, accumulated_cost_usd DESC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        print(f"[!] get_cps_summary error: {e}", file=sys.stderr)
    return rows

def get_recent_audit_records(limit: int = 50, query: Optional[str] = None) -> List[Dict[str, Any]]:
    db_path = get_db_path()
    rows = []
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if query and query.strip():
            q = query.strip()
            cur.execute("""
                SELECT request_id, trace_id, created_at, api_key_alias, caller_role,
                       model_requested, model_routed, http_status, latency_ms,
                       prompt_tokens, completion_tokens, cost_usd,
                       prompt_sha256, completion_sha256, zdr_verified,
                       task_id, task_outcome
                FROM gateway_audit_ledger
                WHERE request_id LIKE ? OR task_id LIKE ? OR trace_id LIKE ? OR api_key_alias LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", limit))
        else:
            cur.execute("""
                SELECT request_id, trace_id, created_at, api_key_alias, caller_role,
                       model_requested, model_routed, http_status, latency_ms,
                       prompt_tokens, completion_tokens, cost_usd,
                       prompt_sha256, completion_sha256, zdr_verified,
                       task_id, task_outcome
                FROM gateway_audit_ledger
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        print(f"[!] get_recent_audit_records error: {e}", file=sys.stderr)
    return rows

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Gateway • Observability & CPS Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #080b11;
      --bg-card: rgba(18, 24, 38, 0.75);
      --bg-card-hover: rgba(26, 34, 54, 0.85);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-glow: rgba(99, 102, 241, 0.25);
      --primary: #6366f1;
      --primary-light: #818cf8;
      --accent-cyan: #06b6d4;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --font-ui: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-ui);
      background-image: 
        radial-gradient(circle at 15% 15%, rgba(99, 102, 241, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 85% 25%, rgba(6, 182, 212, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 50% 85%, rgba(16, 185, 129, 0.06) 0%, transparent 45%);
      background-attachment: fixed;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: rgba(11, 15, 25, 0.8);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-subtle);
      padding: 16px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand-icon {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, var(--primary), var(--accent-cyan));
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 0 20px rgba(99, 102, 241, 0.4);
    }
    .brand-title {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: linear-gradient(to right, #ffffff, #94a3b8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .nav-links {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .btn-link {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.875rem;
      font-weight: 500;
      padding: 8px 14px;
      border-radius: 8px;
      border: 1px solid var(--border-subtle);
      background: rgba(255, 255, 255, 0.02);
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .btn-link:hover {
      color: var(--text-main);
      background: rgba(255, 255, 255, 0.06);
      border-color: rgba(255, 255, 255, 0.15);
      transform: translateY(-1px);
    }
    .pulse-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.75rem;
      color: var(--accent-emerald);
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.25);
      padding: 6px 12px;
      border-radius: 20px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .dot {
      width: 7px;
      height: 7px;
      background-color: var(--accent-emerald);
      border-radius: 50%;
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
      70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    main {
      flex: 1;
      max-width: 1440px;
      margin: 0 auto;
      width: 100%;
      padding: 32px;
      display: flex;
      flex-direction: column;
      gap: 32px;
    }
    /* Metric Cards Grid */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 20px;
    }
    .metric-card {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 24px;
      position: relative;
      overflow: hidden;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .metric-card:hover {
      background: var(--bg-card-hover);
      border-color: var(--border-glow);
      transform: translateY(-2px);
      box-shadow: 0 12px 28px -10px rgba(0, 0, 0, 0.5);
    }
    .metric-card::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--card-accent, var(--primary)), transparent);
    }
    .metric-label {
      font-size: 0.8125rem;
      color: var(--text-muted);
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    .metric-value {
      font-size: 2.125rem;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.02em;
    }
    .metric-sub {
      margin-top: 8px;
      font-size: 0.8125rem;
      color: var(--text-dim);
    }
    /* Section Containers */
    .section-box {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
    }
    .section-header {
      padding: 18px 24px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      background: rgba(255, 255, 255, 0.015);
    }
    .section-title {
      font-size: 1.125rem;
      font-weight: 600;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .badge-count {
      background: rgba(99, 102, 241, 0.15);
      color: var(--primary-light);
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 0.75rem;
      font-weight: 600;
    }
    /* Search Box Styles */
    .search-wrapper {
      position: relative;
      display: flex;
      align-items: center;
      min-width: 320px;
    }
    .search-icon {
      position: absolute;
      left: 12px;
      color: var(--text-dim);
      pointer-events: none;
      transition: color 0.2s;
    }
    .search-input {
      width: 100%;
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      padding: 8px 34px 8px 36px;
      border-radius: 8px;
      outline: none;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .search-input:focus {
      background: rgba(15, 23, 42, 0.95);
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
    }
    .search-input:focus + .search-icon {
      color: var(--primary-light);
    }
    .search-clear {
      position: absolute;
      right: 10px;
      background: none;
      border: none;
      color: var(--text-dim);
      cursor: pointer;
      font-size: 0.875rem;
      padding: 2px 6px;
      border-radius: 4px;
      display: none;
      transition: all 0.2s;
    }
    .search-clear:hover {
      color: var(--text-main);
      background: rgba(255, 255, 255, 0.08);
    }
    .highlight-match {
      background: rgba(99, 102, 241, 0.45);
      color: #ffffff;
      padding: 1px 3px;
      border-radius: 3px;
      font-weight: 600;
    }
    .copyable-req {
      cursor: pointer;
      transition: color 0.2s;
    }
    .copyable-req:hover {
      color: var(--primary-light);
      text-decoration: underline;
    }
    .table-container {
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.875rem;
    }
    th {
      padding: 14px 20px;
      background: rgba(15, 23, 42, 0.4);
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border-subtle);
    }
    td {
      padding: 14px 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
      vertical-align: middle;
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }
    .mono {
      font-family: var(--font-mono);
      font-size: 0.8125rem;
    }
    /* Status Badges */
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 10px;
      border-radius: 16px;
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .status-success {
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .status-pending {
      background: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .status-closed {
      background: rgba(244, 63, 94, 0.15);
      color: #fb7185;
      border: 1px solid rgba(244, 63, 94, 0.3);
    }
    .btn-trace {
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: var(--primary-light);
      padding: 4px 10px;
      border-radius: 6px;
      text-decoration: none;
      font-size: 0.75rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }
    .btn-trace:hover {
      background: rgba(99, 102, 241, 0.25);
      border-color: var(--primary-light);
      color: #ffffff;
      transform: translateY(-1px);
    }
    .hash-chip {
      background: rgba(255, 255, 255, 0.04);
      padding: 3px 6px;
      border-radius: 4px;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--text-muted);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="brand-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
        </svg>
      </div>
      <div>
        <div class="brand-title">AI Gateway • CPS & Audit Console</div>
        <div style="font-size: 0.75rem; color: var(--text-dim);">Zero Data Retention & Cost-Per-Success Control Plane</div>
      </div>
    </div>
    <div class="nav-links">
      <div class="pulse-badge">
        <div class="dot"></div>
        Live Telemetry
      </div>
      <a href="http://localhost:16686" target="_blank" class="btn-link">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><path d="m10 15 5-3-5-3v6Z"/>
        </svg>
        Jaeger UI (:16686)
      </a>
      <a href="http://localhost:4000/ui" target="_blank" class="btn-link">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18M3 9h18"/>
        </svg>
        LiteLLM Proxy UI (:4000)
      </a>
    </div>
  </header>

  <main>
    <!-- Top KPI Grid -->
    <div class="metrics-grid">
      <div class="metric-card" style="--card-accent: var(--primary);">
        <div class="metric-label">Total Coding Tasks</div>
        <div class="metric-value" id="kpi-total-tasks">-</div>
        <div class="metric-sub" id="kpi-total-records">- Ledger Requests Recorded</div>
      </div>
      <div class="metric-card" style="--card-accent: var(--accent-emerald);">
        <div class="metric-label">Verified Successes</div>
        <div class="metric-value" id="kpi-verified-tasks" style="color: var(--accent-emerald);">-</div>
        <div class="metric-sub">Reconciled via Git Merge Lifecycle</div>
      </div>
      <div class="metric-card" style="--card-accent: var(--accent-cyan);">
        <div class="metric-label">Accumulated Spend</div>
        <div class="metric-value" id="kpi-total-spend" style="color: var(--accent-cyan);">$0.00</div>
        <div class="metric-sub">Real-Time Micro-Cent Token Card</div>
      </div>
      <div class="metric-card" style="--card-accent: var(--accent-amber);">
        <div class="metric-label">Nominal CPS (Merged Only)</div>
        <div class="metric-value" id="kpi-avg-cps" style="color: var(--accent-amber);">$0.00</div>
        <div class="metric-sub">Cost / Successful Task</div>
      </div>
      <div class="metric-card" style="--card-accent: #f43f5e;">
        <div class="metric-label">Fully-Loaded CPS</div>
        <div class="metric-value" id="kpi-fully-loaded-cps" style="color: #fb7185;">$0.00</div>
        <div class="metric-sub" id="kpi-fully-loaded-sub">All Task Spend / Merged Tasks</div>
      </div>
      <div class="metric-card" style="--card-accent: #38bdf8;">
        <div class="metric-label">Task Success Rate</div>
        <div class="metric-value" id="kpi-success-rate" style="color: #38bdf8;">0.0%</div>
        <div class="metric-sub" id="kpi-success-rate-sub">0 of 0 tasks merged</div>
      </div>
      <div class="metric-card" style="--card-accent: var(--accent-emerald);">
        <div class="metric-label">ZDR Invariant Status</div>
        <div class="metric-value" id="kpi-zdr-status" style="font-size: 1.125rem; font-weight: 600; color: var(--accent-emerald); padding-top: 8px;">100% COMPLIANT</div>
        <div class="metric-sub">0 Bytes Plaintext Persisted</div>
      </div>
    </div>

    <!-- Executive Section: Where the Money Went Breakdown -->
    <div class="section-box">
      <div class="section-header">
        <div class="section-title">
          <span>Where the Money Went (Capital Allocation)</span>
          <span class="badge-count" id="badge-spend-total">$0.00 Total</span>
        </div>
        <div style="font-size: 0.8125rem; color: var(--text-dim);">Financial breakdown by task outcome: Merged vs Closed Unmerged vs Pending vs Policy Blocked</div>
      </div>
      <div style="padding: 20px 24px;">
        <!-- Visual Progress Bar -->
        <div id="spend-bar" style="display: flex; height: 14px; border-radius: 7px; overflow: hidden; background: rgba(255,255,255,0.06); margin-bottom: 20px;">
          <div id="bar-merged" style="background: #10b981; width: 0%; transition: width 0.4s ease;" title="Merged"></div>
          <div id="bar-closed" style="background: #f43f5e; width: 0%; transition: width 0.4s ease;" title="Closed Unmerged"></div>
          <div id="bar-pending" style="background: #f59e0b; width: 0%; transition: width 0.4s ease;" title="Pending"></div>
          <div id="bar-blocked" style="background: #8b5cf6; width: 0%; transition: width 0.4s ease;" title="Blocked by Policy"></div>
          <div id="bar-other" style="background: #64748b; width: 0%; transition: width 0.4s ease;" title="Other"></div>
        </div>
        <!-- Metric Grid for Categories -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px;">
          <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 10px; padding: 12px 16px;">
            <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #34d399; font-weight: 600;">
              <span style="width: 8px; height: 8px; border-radius: 50%; background: #10b981;"></span> Merged (Productive)
            </div>
            <div id="spend-val-merged" style="font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-top: 6px;">$0.0000</div>
            <div id="spend-pct-merged" style="font-size: 0.75rem; color: var(--text-dim);">0.0% of total spend</div>
          </div>
          <div style="background: rgba(244, 63, 94, 0.08); border: 1px solid rgba(244, 63, 94, 0.2); border-radius: 10px; padding: 12px 16px;">
            <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #fb7185; font-weight: 600;">
              <span style="width: 8px; height: 8px; border-radius: 50%; background: #f43f5e;"></span> Closed Unmerged (Waste)
            </div>
            <div id="spend-val-closed" style="font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-top: 6px;">$0.0000</div>
            <div id="spend-pct-closed" style="font-size: 0.75rem; color: var(--text-dim);">0.0% of total spend</div>
          </div>
          <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.2); border-radius: 10px; padding: 12px 16px;">
            <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #fbbf24; font-weight: 600;">
              <span style="width: 8px; height: 8px; border-radius: 50%; background: #f59e0b;"></span> Pending (In-Flight)
            </div>
            <div id="spend-val-pending" style="font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-top: 6px;">$0.0000</div>
            <div id="spend-pct-pending" style="font-size: 0.75rem; color: var(--text-dim);">0.0% of total spend</div>
          </div>
          <div style="background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.2); border-radius: 10px; padding: 12px 16px;">
            <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #a78bfa; font-weight: 600;">
              <span style="width: 8px; height: 8px; border-radius: 50%; background: #8b5cf6;"></span> Blocked by Policy
            </div>
            <div id="spend-val-blocked" style="font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-top: 6px;">$0.0000</div>
            <div id="spend-pct-blocked" style="font-size: 0.75rem; color: var(--text-dim);">0.0% of total spend</div>
          </div>
          <div style="background: rgba(100, 116, 139, 0.08); border: 1px solid rgba(100, 116, 139, 0.2); border-radius: 10px; padding: 12px 16px;">
            <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #94a3b8; font-weight: 600;">
              <span style="width: 8px; height: 8px; border-radius: 50%; background: #64748b;"></span> Other / Fallback
            </div>
            <div id="spend-val-other" style="font-size: 1.25rem; font-weight: 700; color: #ffffff; margin-top: 6px;">$0.0000</div>
            <div id="spend-pct-other" style="font-size: 0.75rem; color: var(--text-dim);">0.0% of total spend</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Section 1: Coding Tasks CPS Analytical Table -->
    <div class="section-box">
      <div class="section-header">
        <div class="section-title">
          <span>Cost Per Successful Task (CPS) Summary</span>
          <span class="badge-count" id="badge-cps-count">0 Tasks</span>
        </div>
        <div style="font-size: 0.8125rem; color: var(--text-dim);">Aggregated via <code>v_coding_cps_summary</code></div>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Task Identifier</th>
              <th>Total Turns</th>
              <th>Tokens Used</th>
              <th>Accumulated Spend</th>
              <th>Task Outcome</th>
              <th>Final CPS ($/Task)</th>
            </tr>
          </thead>
          <tbody id="tbody-cps">
            <tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 32px;">Loading tasks...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Section 2: Recent Transaction Audit Log with Search Box -->
    <div class="section-box">
      <div class="section-header">
        <div class="section-title">
          <span>Zero Data Retention Audit Ledger & Traces</span>
          <span class="badge-count" id="badge-audit-count">0 Calls</span>
        </div>
        <!-- Search by Request ID, Task ID, or Trace ID -->
        <div class="search-wrapper">
          <svg class="search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
          <input type="text" id="input-search-request" class="search-input" placeholder="Search by Request ID (e.g. chatcmpl-...)" autocomplete="off" spellcheck="false" />
          <button id="btn-clear-search" class="search-clear" title="Clear search">✕</button>
        </div>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Request ID</th>
              <th>Key Alias</th>
              <th>Model</th>
              <th>Latency</th>
              <th>Tokens (In/Out)</th>
              <th>Spend</th>
              <th>Prompt SHA-256</th>
              <th>Distributed Trace</th>
            </tr>
          </thead>
          <tbody id="tbody-audit">
            <tr><td colspan="9" style="text-align: center; color: var(--text-dim); padding: 32px;">Loading audit ledger...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <script>
    let currentSearchQuery = "";
    let searchDebounceTimer = null;

    function highlightText(text, query) {
      if (!query || !text) return text || "";
      const escaped = query.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
      const regex = new RegExp(`(${escaped})`, 'gi');
      return String(text).replace(regex, '<span class="highlight-match">$1</span>');
    }

    async function copyToClipboard(text, elem) {
      try {
        await navigator.clipboard.writeText(text);
        const originalText = elem.innerHTML;
        elem.innerHTML = '<span style="color:var(--accent-emerald);">Copied!</span>';
        setTimeout(() => { elem.innerHTML = originalText; }, 1200);
      } catch (e) {
        console.error("Copy failed:", e);
      }
    }

    async function fetchDashboardData(isManualSearch = false) {
      try {
        const auditUrl = currentSearchQuery 
          ? `/api/audit?q=${encodeURIComponent(currentSearchQuery)}`
          : '/api/audit';

        const [statsRes, cpsRes, auditRes] = await Promise.all([
          fetch('/api/stats').then(r => r.json()),
          fetch('/api/cps').then(r => r.json()),
          fetch(auditUrl).then(r => r.json())
        ]);

        // 1. Update KPIs
        document.getElementById('kpi-total-tasks').textContent = statsRes.total_tasks || 0;
        document.getElementById('kpi-total-records').textContent = `${statsRes.total_records || 0} Ledger Requests Recorded`;
        document.getElementById('kpi-verified-tasks').textContent = statsRes.verified_tasks || 0;
        document.getElementById('kpi-total-spend').textContent = `$${(statsRes.total_spend || 0).toFixed(4)}`;
        document.getElementById('kpi-avg-cps').textContent = statsRes.avg_cps ? `$${statsRes.avg_cps.toFixed(4)}` : '$0.0000';
        
        // Fully-Loaded CPS
        const fullyLoadedEl = document.getElementById('kpi-fully-loaded-cps');
        const fullyLoadedSub = document.getElementById('kpi-fully-loaded-sub');
        if ((statsRes.verified_tasks || 0) === 0) {
          fullyLoadedEl.textContent = 'N/A';
          fullyLoadedSub.textContent = (statsRes.total_spend || 0) > 0 
            ? `$${statsRes.total_spend.toFixed(4)} unmerged spend (0 merged)` 
            : '0 merged tasks';
        } else {
          fullyLoadedEl.textContent = `$${(statsRes.fully_loaded_cps || 0).toFixed(4)}`;
          fullyLoadedSub.textContent = `${statsRes.verified_tasks} merged of ${statsRes.total_tasks} total`;
        }

        // Success Rate
        const successRateEl = document.getElementById('kpi-success-rate');
        const successRateSub = document.getElementById('kpi-success-rate-sub');
        const ratePct = ((statsRes.success_rate || 0) * 100).toFixed(1);
        successRateEl.textContent = `${ratePct}%`;
        successRateSub.textContent = `${statsRes.verified_tasks || 0} of ${statsRes.total_tasks || 0} tasks merged`;

        document.getElementById('kpi-zdr-status').textContent = statsRes.zdr_status.includes('100%') ? '100% COMPLIANT' : statsRes.zdr_status;

        // Where the Money Went Breakdown
        const sByO = statsRes.spend_by_outcome || {};
        const totalSp = statsRes.total_spend || 0.000001; // Avoid divide by zero
        const mSpend = sByO.merged || 0;
        const cSpend = sByO.closed_unmerged || 0;
        const pSpend = sByO.pending || 0;
        const bSpend = sByO.blocked_by_policy || 0;
        const oSpend = sByO.other || 0;

        document.getElementById('badge-spend-total').textContent = `$${(statsRes.total_spend || 0).toFixed(4)} Total`;

        // Progress bar widths
        const mPct = (statsRes.total_spend || 0) > 0 ? (mSpend / totalSp) * 100 : 0;
        const cPct = (statsRes.total_spend || 0) > 0 ? (cSpend / totalSp) * 100 : 0;
        const pPct = (statsRes.total_spend || 0) > 0 ? (pSpend / totalSp) * 100 : 0;
        const bPct = (statsRes.total_spend || 0) > 0 ? (bSpend / totalSp) * 100 : 0;
        const oPct = (statsRes.total_spend || 0) > 0 ? (oSpend / totalSp) * 100 : 0;

        document.getElementById('bar-merged').style.width = `${mPct}%`;
        document.getElementById('bar-closed').style.width = `${cPct}%`;
        document.getElementById('bar-pending').style.width = `${pPct}%`;
        document.getElementById('bar-blocked').style.width = `${bPct}%`;
        document.getElementById('bar-other').style.width = `${oPct}%`;

        document.getElementById('spend-val-merged').textContent = `$${mSpend.toFixed(4)}`;
        document.getElementById('spend-pct-merged').textContent = `${mPct.toFixed(1)}% of total spend`;

        document.getElementById('spend-val-closed').textContent = `$${cSpend.toFixed(4)}`;
        document.getElementById('spend-pct-closed').textContent = `${cPct.toFixed(1)}% of total spend`;

        document.getElementById('spend-val-pending').textContent = `$${pSpend.toFixed(4)}`;
        document.getElementById('spend-pct-pending').textContent = `${pPct.toFixed(1)}% of total spend`;

        document.getElementById('spend-val-blocked').textContent = `$${bSpend.toFixed(4)}`;
        document.getElementById('spend-pct-blocked').textContent = `${bPct.toFixed(1)}% of total spend`;

        document.getElementById('spend-val-other').textContent = `$${oSpend.toFixed(4)}`;
        document.getElementById('spend-pct-other').textContent = `${oPct.toFixed(1)}% of total spend`;

        // 2. Render CPS Table
        document.getElementById('badge-cps-count').textContent = `${cpsRes.length} Tasks`;
        const tbodyCps = document.getElementById('tbody-cps');
        if (cpsRes.length === 0) {
          tbodyCps.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-dim); padding:24px;">No coding tasks recorded yet.</td></tr>';
        } else {
          tbodyCps.innerHTML = cpsRes.map(t => {
            let statusBadge = '<span class="status-badge status-pending">● pending</span>';
            if (t.task_outcome === 'verified_success') {
              statusBadge = '<span class="status-badge status-success">✓ verified_success</span>';
            } else if (t.task_outcome === 'unmerged_closed') {
              statusBadge = '<span class="status-badge status-closed">✕ unmerged_closed</span>';
            } else if (t.task_outcome === 'tool_policy_rejected') {
              statusBadge = '<span class="status-badge" style="background:rgba(139,92,246,0.15); color:#a78bfa; border:1px solid rgba(139,92,246,0.3);">⊘ blocked_policy</span>';
            } else if (t.task_outcome === 'failed') {
              statusBadge = '<span class="status-badge status-closed">⚠ failed</span>';
            }
            const cpsText = t.final_cps_usd !== null 
              ? `<strong style="color:var(--accent-emerald);">$${Number(t.final_cps_usd).toFixed(6)}</strong>`
              : `<span style="color:var(--text-dim);">Pending Verification</span>`;

            return `<tr>
              <td><span class="mono" style="color:var(--primary-light); cursor:pointer;" onclick="setSearchFilter('${t.task_id}')" title="Click to filter transactions by this Task ID">${t.task_id}</span></td>
              <td>${t.total_turns} turns</td>
              <td>${t.total_tokens || 0}</td>
              <td class="mono">$${Number(t.accumulated_cost_usd || 0).toFixed(6)}</td>
              <td>${statusBadge}</td>
              <td class="mono">${cpsText}</td>
            </tr>`;
          }).join('');
        }

        // 3. Render Audit Table
        const countLabel = currentSearchQuery ? `${auditRes.length} Matching` : `${auditRes.length} Calls`;
        document.getElementById('badge-audit-count').textContent = countLabel;
        const tbodyAudit = document.getElementById('tbody-audit');
        if (auditRes.length === 0) {
          const emptyMsg = currentSearchQuery 
            ? `No transactions found matching Request ID "<strong>${currentSearchQuery}</strong>". <button onclick="clearSearchFilter()" style="margin-left:8px; background:rgba(99,102,241,0.2); border:1px solid rgba(99,102,241,0.4); color:var(--primary-light); padding:3px 8px; border-radius:4px; cursor:pointer;">Reset</button>`
            : 'No audit records found.';
          tbodyAudit.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--text-dim); padding:32px;">${emptyMsg}</td></tr>`;
        } else {
          tbodyAudit.innerHTML = auditRes.map(r => {
            const promptHashShort = r.prompt_sha256 ? `${r.prompt_sha256.substring(0, 8)}...${r.prompt_sha256.substring(56)}` : '-';
            const jaegerLink = `http://${window.location.hostname}:16686/trace/${r.trace_id}`;
            const reqDisplay = highlightText(r.request_id, currentSearchQuery);
            return `<tr>
              <td style="color:var(--text-dim); font-size:0.75rem;">${r.created_at || '-'}</td>
              <td><span class="mono copyable-req" onclick="copyToClipboard('${r.request_id}', this)" title="Click to copy Request ID">${reqDisplay}</span></td>
              <td><span class="mono" style="color:var(--text-muted);">${highlightText(r.api_key_alias || 'developer', currentSearchQuery)}</span></td>
              <td><span style="font-weight:500;">${r.model_routed || r.model_requested}</span></td>
              <td class="mono">${r.latency_ms ? r.latency_ms.toFixed(1) : 0}ms</td>
              <td class="mono">${r.prompt_tokens || 0} / ${r.completion_tokens || 0}</td>
              <td class="mono">$${Number(r.cost_usd || 0).toFixed(6)}</td>
              <td><span class="hash-chip" title="${r.prompt_sha256}">${promptHashShort}</span></td>
              <td>
                <a href="${jaegerLink}" target="_blank" class="btn-trace">
                  <span>View Waterfall</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>
                </a>
              </td>
            </tr>`;
          }).join('');
        }
      } catch (err) {
        console.error("Dashboard refresh error:", err);
      }
    }

    function setSearchFilter(val) {
      const searchInput = document.getElementById('input-search-request');
      const clearBtn = document.getElementById('btn-clear-search');
      searchInput.value = val;
      currentSearchQuery = val.trim();
      clearBtn.style.display = currentSearchQuery ? 'block' : 'none';
      fetchDashboardData(true);
    }

    function clearSearchFilter() {
      const searchInput = document.getElementById('input-search-request');
      const clearBtn = document.getElementById('btn-clear-search');
      searchInput.value = '';
      currentSearchQuery = '';
      clearBtn.style.display = 'none';
      fetchDashboardData(true);
      searchInput.focus();
    }

    const searchInput = document.getElementById('input-search-request');
    const clearBtn = document.getElementById('btn-clear-search');

    searchInput.addEventListener('input', (e) => {
      currentSearchQuery = e.target.value.trim();
      clearBtn.style.display = currentSearchQuery ? 'block' : 'none';
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        fetchDashboardData(true);
      }, 200);
    });

    clearBtn.addEventListener('click', clearSearchFilter);

    fetchDashboardData();
    setInterval(fetchDashboardData, 3000);
  </script>
</body>
</html>
"""

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/dashboard"):
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy", "service": "cps_webhook"}).encode("utf-8"))
        elif self.path == "/api/stats":
            data = get_db_stats()
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/cps":
            data = get_cps_summary()
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/audit"):
            q_param = None
            if "?" in self.path:
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                q_param = qs.get("q", [None])[0] or qs.get("request_id", [None])[0]
            data = get_recent_audit_records(limit=60, query=q_param)
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/metrics", "/metrics/"):
            stats = get_db_stats()
            s_by_o = stats.get("spend_by_outcome", {})
            prom_lines = [
                "# HELP ai_gateway_tasks_total Total coding tasks recorded by gateway",
                "# TYPE ai_gateway_tasks_total gauge",
                f"ai_gateway_tasks_total {stats.get('total_tasks', 0)}",
                "# HELP ai_gateway_verified_success_tasks_total Reconciled successful tasks via PR merge",
                "# TYPE ai_gateway_verified_success_tasks_total gauge",
                f"ai_gateway_verified_success_tasks_total {stats.get('verified_tasks', 0)}",
                "# HELP ai_gateway_total_spend_usd Cumulative gateway token spend in USD",
                "# TYPE ai_gateway_total_spend_usd gauge",
                f"ai_gateway_total_spend_usd {stats.get('total_spend', 0.0)}",
                "# HELP ai_gateway_avg_cps_usd Average Cost Per Successful Task (CPS) in USD",
                "# TYPE ai_gateway_avg_cps_usd gauge",
                f"ai_gateway_avg_cps_usd {stats.get('avg_cps', 0.0)}",
                "# HELP ai_gateway_fully_loaded_cps_usd Fully-loaded Cost Per Successful Task (all spend / merged tasks) in USD",
                "# TYPE ai_gateway_fully_loaded_cps_usd gauge",
                f"ai_gateway_fully_loaded_cps_usd {stats.get('fully_loaded_cps', 0.0)}",
                "# HELP ai_gateway_task_success_ratio Ratio of merged tasks over total tasks (0.0 - 1.0)",
                "# TYPE ai_gateway_task_success_ratio gauge",
                f"ai_gateway_task_success_ratio {stats.get('success_rate', 0.0)}",
                "# HELP ai_gateway_spend_by_outcome_usd Gateway spend categorized by lifecycle outcome",
                "# TYPE ai_gateway_spend_by_outcome_usd gauge",
                f'ai_gateway_spend_by_outcome_usd{{outcome="merged"}} {s_by_o.get("merged", 0.0)}',
                f'ai_gateway_spend_by_outcome_usd{{outcome="closed_unmerged"}} {s_by_o.get("closed_unmerged", 0.0)}',
                f'ai_gateway_spend_by_outcome_usd{{outcome="pending"}} {s_by_o.get("pending", 0.0)}',
                f'ai_gateway_spend_by_outcome_usd{{outcome="blocked_by_policy"}} {s_by_o.get("blocked_by_policy", 0.0)}',
                f'ai_gateway_spend_by_outcome_usd{{outcome="other"}} {s_by_o.get("other", 0.0)}',
                "# HELP ai_gateway_zdr_compliant Zero Data Retention Invariant Compliance (1 = 100% compliant)",
                "# TYPE ai_gateway_zdr_compliant gauge",
                f"ai_gateway_zdr_compliant {1 if '100%' in stats.get('zdr_status', '') else 0}"
            ]
            prom_body = ("\n".join(prom_lines) + "\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(prom_body)))
            self.end_headers()
            self.wfile.write(prom_body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/webhooks/github":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            pr = payload.get("pull_request", {})
            branch = pr.get("head", {}).get("ref", "")
            merged = pr.get("merged", False)
            
            task_id = query_redis_branch(branch) if branch else None
            new_status = "verified_success" if merged else "unmerged_closed"
            bhash = hashlib.sha256(branch.encode("utf-8")).hexdigest() if branch else ""
            db_path = get_db_path()
            updated_rows = 0

            # Fallback check if task_id was directly derived from hashed PR identity
            if not task_id and branch:
                candidate_ids = [f"task_{bhash[:16]}", f"task_pr_{bhash[:12]}"]
                try:
                    conn = sqlite3.connect(db_path, timeout=10.0)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    for cid in candidate_ids:
                        cur = conn.cursor()
                        cur.execute("SELECT task_id FROM gateway_audit_ledger WHERE task_id = ? LIMIT 1", (cid,))
                        if cur.fetchone():
                            task_id = cid
                            break
                    conn.close()
                except Exception as e:
                    print(f"[!] Direct PR hash lookup error: {e}", file=sys.stderr)
            
            if task_id:
                try:
                    conn = sqlite3.connect(db_path, timeout=10.0)
                    conn.execute("PRAGMA journal_mode=WAL;")
                    cur = conn.cursor()
                    cur.execute("UPDATE gateway_audit_ledger SET task_outcome = ? WHERE task_id = ?", (new_status, task_id))
                    updated_rows = cur.rowcount
                    conn.commit()
                    conn.close()
                    print(f"✅ Reconciled task {task_id} -> {new_status} (bhash: {bhash[:16]}..., rows: {updated_rows})")
                except Exception as e:
                    print(f"[!] SQLite update error: {e}", file=sys.stderr)
            else:
                print(f"⚠️ No active task found in Redis or SQLite for branch '{branch}' (bhash: {bhash[:16]}...)")
            
            response_data = {
                "status": "ok",
                "task_id": task_id,
                "branch_hash": bhash,
                "outcome": new_status,
                "updated_rows": updated_rows
            }
            body = json.dumps(response_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        sys.stdout.write(f"[cps_webhook] {self.address_string()} - {format%args}\n")

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"🚀 CPS Webhook Companion & Dashboard running on port {PORT}...")
    server.serve_forever()
