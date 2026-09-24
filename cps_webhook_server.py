#!/usr/bin/env python3
"""
cps_webhook_server.py: Companion Listener & Web Dashboard for Minimal Local AI Gateway.
Features:
1. Listens on port 4001 for GitHub PR merge webhooks (/webhooks/github).
2. Resolves task_id from Redis bhash:<sha256> and updates SQLite gateway.db.
3. Serves the interactive AI Gateway CPS & ZDR Observability Dashboard (GET / & GET /dashboard).
4. Serves JSON APIs: /api/stats, /api/cps, /api/audit.
"""
import os
import sys
import json
import hashlib
import sqlite3
import socket
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

        # CPS summaries
        cur.execute("""
            SELECT 
                COUNT(*) AS total_tasks,
                SUM(CASE WHEN task_outcome = 'verified_success' THEN 1 ELSE 0 END) AS verified_tasks,
                ROUND(SUM(accumulated_cost_usd), 6) AS total_spend,
                ROUND(AVG(final_cps_usd), 6) AS avg_cps
            FROM v_coding_cps_summary
        """)
        s_row = cur.fetchone()
        if s_row:
            stats["total_tasks"] = s_row["total_tasks"] or 0
            stats["verified_tasks"] = s_row["verified_tasks"] or 0
            stats["total_spend"] = s_row["total_spend"] or 0.0
            stats["avg_cps"] = s_row["avg_cps"] or 0.0
            
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

def get_recent_audit_records(limit: int = 50) -> List[Dict[str, Any]]:
    db_path = get_db_path()
    rows = []
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
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
      padding: 20px 24px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
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
        <div class="metric-label">Average Cost / Success</div>
        <div class="metric-value" id="kpi-avg-cps" style="color: var(--accent-amber);">$0.00</div>
        <div class="metric-sub">Cost Per Successful Task (CPS)</div>
      </div>
      <div class="metric-card" style="--card-accent: var(--accent-emerald);">
        <div class="metric-label">ZDR Invariant Status</div>
        <div class="metric-value" id="kpi-zdr-status" style="font-size: 1.125rem; font-weight: 600; color: var(--accent-emerald); padding-top: 8px;">100% COMPLIANT</div>
        <div class="metric-sub">0 Bytes Plaintext Persisted</div>
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

    <!-- Section 2: Recent Transaction Audit Log -->
    <div class="section-box">
      <div class="section-header">
        <div class="section-title">
          <span>Zero Data Retention Audit Ledger & Traces</span>
          <span class="badge-count" id="badge-audit-count">0 Calls</span>
        </div>
        <div style="font-size: 0.8125rem; color: var(--text-dim);">Source: <code>gateway_audit_ledger</code></div>
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
    async function fetchDashboardData() {
      try {
        const [statsRes, cpsRes, auditRes] = await Promise.all([
          fetch('/api/stats').then(r => r.json()),
          fetch('/api/cps').then(r => r.json()),
          fetch('/api/audit').then(r => r.json())
        ]);

        // 1. Update KPIs
        document.getElementById('kpi-total-tasks').textContent = statsRes.total_tasks || 0;
        document.getElementById('kpi-total-records').textContent = `${statsRes.total_records || 0} Ledger Requests Recorded`;
        document.getElementById('kpi-verified-tasks').textContent = statsRes.verified_tasks || 0;
        document.getElementById('kpi-total-spend').textContent = `$${(statsRes.total_spend || 0).toFixed(4)}`;
        document.getElementById('kpi-avg-cps').textContent = statsRes.avg_cps ? `$${statsRes.avg_cps.toFixed(4)}` : '$0.0000';
        document.getElementById('kpi-zdr-status').textContent = statsRes.zdr_status.includes('100%') ? '100% COMPLIANT' : statsRes.zdr_status;

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
            }
            const cpsText = t.final_cps_usd !== null 
              ? `<strong style="color:var(--accent-emerald);">$${Number(t.final_cps_usd).toFixed(6)}</strong>`
              : `<span style="color:var(--text-dim);">Pending Verification</span>`;

            return `<tr>
              <td><span class="mono" style="color:var(--primary-light);">${t.task_id}</span></td>
              <td>${t.total_turns} turns</td>
              <td>${t.total_tokens || 0}</td>
              <td class="mono">$${Number(t.accumulated_cost_usd || 0).toFixed(6)}</td>
              <td>${statusBadge}</td>
              <td class="mono">${cpsText}</td>
            </tr>`;
          }).join('');
        }

        // 3. Render Audit Table
        document.getElementById('badge-audit-count').textContent = `${auditRes.length} Calls`;
        const tbodyAudit = document.getElementById('tbody-audit');
        if (auditRes.length === 0) {
          tbodyAudit.innerHTML = '<tr><td colspan="9" style="text-align:center; color:var(--text-dim); padding:24px;">No audit records found.</td></tr>';
        } else {
          tbodyAudit.innerHTML = auditRes.map(r => {
            const promptHashShort = r.prompt_sha256 ? `${r.prompt_sha256.substring(0, 8)}...${r.prompt_sha256.substring(56)}` : '-';
            const jaegerLink = `http://${window.location.hostname}:16686/trace/${r.trace_id}`;
            return `<tr>
              <td style="color:var(--text-dim); font-size:0.75rem;">${r.created_at || '-'}</td>
              <td><span class="mono">${r.request_id}</span></td>
              <td><span class="mono" style="color:var(--text-muted);">${r.api_key_alias || 'developer'}</span></td>
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
            data = get_recent_audit_records(limit=40)
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
