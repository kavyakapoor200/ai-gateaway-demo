#!/usr/bin/env python3
"""
scripts/mock_ops_service.py
Mock backend for the Engineering Ops OpenAPI specification.
Implements the 10 endpoints for Issues, CI Runs, Pull Requests, and Deployments.
Can be used standalone via Uvicorn on port 8089 or directly via ASGI in FastMCP.
"""

from datetime import datetime, timezone
import json
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

# In-memory mock database
ISSUES = [
    {
        "id": "ISS-142",
        "title": "Memory leak in background telemetry worker",
        "description": "Worker processes consume excess RAM during long batch exports and get killed by OOM killer.",
        "status": "open",
        "labels": ["bug", "backend", "memory"],
        "assignee": "kavyakapoor",
        "created_at": "2026-10-04T14:20:00Z",
        "comments": [
            {
                "id": "cmt_01",
                "body": "Observed on staging during stress testing with 50k messages.",
                "author": "lead-architect",
                "created_at": "2026-10-04T15:00:00Z"
            }
        ]
    },
    {
        "id": "ISS-101",
        "title": "Fix flaky CI test in gateway authentication suite",
        "description": "Test test_virtual_key_expiry occasionally fails due to race condition with redis cache.",
        "status": "in_progress",
        "labels": ["ci", "testing"],
        "assignee": "alex",
        "created_at": "2026-10-03T09:15:00Z",
        "comments": []
    },
    {
        "id": "ISS-98",
        "title": "Configure FastMCP OpenAPI converter on AI Gateway",
        "description": "Auto-convert OpenAPI specs to MCP tools and route through LiteLLM Gateway with Zero Data Retention.",
        "status": "closed",
        "labels": ["gateway", "mcp"],
        "assignee": "claude-desktop",
        "created_at": "2026-10-01T11:00:00Z",
        "comments": [
            {
                "id": "cmt_02",
                "body": "Verified working with SSE transport on port 8005 proxying through Gateway :4000.",
                "author": "claude-desktop",
                "created_at": "2026-10-01T16:30:00Z"
            }
        ]
    }
]

CI_RUNS = [
    {
        "id": "run_8831",
        "branch": "fix/telemetry-memory-leak",
        "commit_sha": "a1b2c3d4e5f67890",
        "status": "failed",
        "jobs": [
            {"name": "lint", "status": "passed"},
            {"name": "unit-tests", "status": "passed"},
            {"name": "integration-tests", "status": "failed"}
        ],
        "started_at": "2026-10-05T17:30:00Z",
        "finished_at": "2026-10-05T17:35:12Z"
    },
    {
        "id": "run_8832",
        "branch": "main",
        "commit_sha": "f9e8d7c6b5a43210",
        "status": "passed",
        "jobs": [
            {"name": "lint", "status": "passed"},
            {"name": "unit-tests", "status": "passed"},
            {"name": "integration-tests", "status": "passed"}
        ],
        "started_at": "2026-10-05T16:00:00Z",
        "finished_at": "2026-10-05T16:04:45Z"
    }
]

PULL_REQUESTS = [
    {
        "id": "PR-57",
        "title": "fix(worker): release buffer memory after batch export",
        "description": "Explicitly invoke garbage collection and clear buffer chunks to prevent OOM.",
        "source_branch": "fix/telemetry-memory-leak",
        "target_branch": "main",
        "state": "open",
        "linked_issue_id": "ISS-142",
        "checks_status": "failing",
        "review_status": "none"
    }
]

DEPLOYMENTS = [
    {
        "id": "dep_204",
        "environment": "staging",
        "ref": "main",
        "status": "succeeded",
        "requested_by": "claude-desktop",
        "approved_by": "lead-architect",
        "created_at": "2026-10-05T15:00:00Z"
    }
]


# Endpoint Handlers
async def list_issues(request):
    status_filter = request.query_params.get("status")
    label_filter = request.query_params.get("label")
    assignee_filter = request.query_params.get("assignee")
    limit = int(request.query_params.get("limit", 20))

    results = []
    for issue in ISSUES:
        if status_filter and issue["status"] != status_filter:
            continue
        if label_filter and label_filter not in issue.get("labels", []):
            continue
        if assignee_filter and issue.get("assignee") != assignee_filter:
            continue
        # Single issue view includes comments; list view omits or includes
        results.append(issue)
        if len(results) >= limit:
            break

    return JSONResponse({"items": results, "next_cursor": None})


async def get_issue(request):
    issue_id = request.path_params.get("issueId")
    for issue in ISSUES:
        if issue["id"].lower() == issue_id.lower():
            return JSONResponse(issue)
    return JSONResponse({"code": "not_found", "message": f"Issue '{issue_id}' not found."}, status_code=404)


async def add_issue_comment(request):
    issue_id = request.path_params.get("issueId")
    target_issue = None
    for issue in ISSUES:
        if issue["id"].lower() == issue_id.lower():
            target_issue = issue
            break
    if not target_issue:
        return JSONResponse({"code": "not_found", "message": f"Issue '{issue_id}' not found."}, status_code=404)

    try:
        body_data = await request.json()
    except Exception:
        body_data = {}

    comment_text = body_data.get("body", "")
    new_comment = {
        "id": f"cmt_{len(target_issue.get('comments', [])) + 1:02d}",
        "body": comment_text,
        "author": "claude-desktop",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    target_issue.setdefault("comments", []).append(new_comment)
    return JSONResponse(new_comment, status_code=201)


async def list_ci_runs(request):
    branch = request.query_params.get("branch")
    status = request.query_params.get("status")
    limit = int(request.query_params.get("limit", 20))

    results = []
    for run in CI_RUNS:
        if branch and run["branch"] != branch:
            continue
        if status and run["status"] != status:
            continue
        results.append(run)
        if len(results) >= limit:
            break

    return JSONResponse({"items": results, "next_cursor": None})


async def get_ci_run(request):
    run_id = request.path_params.get("runId")
    for run in CI_RUNS:
        if run["id"].lower() == run_id.lower():
            return JSONResponse(run)
    return JSONResponse({"code": "not_found", "message": f"CI run '{run_id}' not found."}, status_code=404)


async def get_ci_run_logs(request):
    run_id = request.path_params.get("runId")
    job = request.query_params.get("job", "integration-tests")
    tail = int(request.query_params.get("tail_lines", 200))

    logs = [
        f"==> Initiating CI run {run_id} on branch fix/telemetry-memory-leak",
        "Running test suite: unit-tests ... [PASS]",
        "Running test suite: integration-tests ...",
        "Test 1: test_gateway_connectivity ... OK",
        "Test 2: test_batch_export_allocation ... FAILED",
        "ERROR: Memory allocation exceeded limit of 512MB (observed 624MB).",
        "Worker thread terminated with exit code 137 (SIGKILL OOM).",
        "==> CI Pipeline completed with status: FAILED"
    ]
    return JSONResponse({
        "job": job,
        "lines": logs[-tail:],
        "truncated": False
    })


async def create_pull_request(request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    new_pr = {
        "id": f"PR-{len(PULL_REQUESTS) + 58}",
        "title": data.get("title", "New Pull Request"),
        "description": data.get("description", ""),
        "source_branch": data.get("source_branch", "feat/agent-fix"),
        "target_branch": data.get("target_branch", "main"),
        "state": "draft" if data.get("draft", True) else "open",
        "linked_issue_id": data.get("linked_issue_id"),
        "checks_status": "pending",
        "review_status": "none"
    }
    PULL_REQUESTS.append(new_pr)
    return JSONResponse(new_pr, status_code=201)


async def get_pull_request(request):
    pr_id = request.path_params.get("prId")
    for pr in PULL_REQUESTS:
        if pr["id"].lower() == pr_id.lower():
            return JSONResponse(pr)
    return JSONResponse({"code": "not_found", "message": f"Pull Request '{pr_id}' not found."}, status_code=404)


async def request_deployment(request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    env = data.get("environment", "staging")
    ref = data.get("ref", "main")
    status = "in_progress" if env == "staging" else "pending_approval"

    new_dep = {
        "id": f"dep_{len(DEPLOYMENTS) + 205}",
        "environment": env,
        "ref": ref,
        "status": status,
        "requested_by": "claude-desktop",
        "approved_by": None if env == "production" else "auto-staging",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    DEPLOYMENTS.append(new_dep)
    return JSONResponse(new_dep, status_code=202)


async def get_deployment(request):
    dep_id = request.path_params.get("deploymentId")
    for dep in DEPLOYMENTS:
        if dep["id"].lower() == dep_id.lower():
            return JSONResponse(dep)
    return JSONResponse({"code": "not_found", "message": f"Deployment '{dep_id}' not found."}, status_code=404)


# Starlette Application Routes
routes = [
    Route("/api/v1/issues", list_issues, methods=["GET"]),
    Route("/api/v1/issues/{issueId}", get_issue, methods=["GET"]),
    Route("/api/v1/issues/{issueId}/comments", add_issue_comment, methods=["POST"]),
    Route("/api/v1/ci/runs", list_ci_runs, methods=["GET"]),
    Route("/api/v1/ci/runs/{runId}", get_ci_run, methods=["GET"]),
    Route("/api/v1/ci/runs/{runId}/logs", get_ci_run_logs, methods=["GET"]),
    Route("/api/v1/pulls", create_pull_request, methods=["POST"]),
    Route("/api/v1/pulls/{prId}", get_pull_request, methods=["GET"]),
    Route("/api/v1/deployments", request_deployment, methods=["POST"]),
    Route("/api/v1/deployments/{deploymentId}", get_deployment, methods=["GET"]),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8089)
