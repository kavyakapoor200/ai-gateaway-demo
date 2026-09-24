#!/usr/bin/env bash
# ==============================================================================
# setup.sh: Bootstrap & Verification Script for Minimal Local AI Gateway PoC
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

MASTER_KEY="${LITELLM_MASTER_KEY:-sk-enterprise-master-secret-key-2026}"
GATEWAY_URL="http://localhost:4000"
CPS_URL="http://localhost:4001"

echo "=============================================================================="
echo "   Minimal Local AI Gateway PoC: Setup & Provisioning"
echo "=============================================================================="

# 1. Initialize SQLite Database
echo "📦 [1/4] Initializing SQLite database (data/gateway.db)..."
mkdir -p data
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 data/gateway.db < sqlite_schema.sql
    echo "    ✅ Created data/gateway.db with single-table ledger & analytical views."
else
    echo "    ⚠️ sqlite3 CLI not found locally. SQLite file will be initialized on first write."
    touch data/gateway.db
fi

# 2. Check / Copy .env
if [ ! -f .env ]; then
    echo "📄 Creating .env from .env.example..."
    cp .env.example .env
fi

# 3. Start Docker Compose Stack
start_docker() {
    echo "🐳 [2/4] Starting Docker Compose stack (LiteLLM, Postgres, Redis, Jaeger, CPS Webhook, Mock Upstream)..."
    docker compose up -d
    echo "    Waiting for services to become healthy..."
    
    # Wait for LiteLLM to respond
    local retries=40
    local count=0
    until curl -s "$GATEWAY_URL/health/liveliness" >/dev/null 2>&1 || [ "$count" -ge "$retries" ]; do
        sleep 2
        count=$((count + 1))
        printf "."
    done
    echo ""

    if [ "$count" -ge "$retries" ]; then
        echo "    ⚠️ Gateway did not report ready within 80s. Check 'docker compose logs litellm'."
    else
        echo "    ✅ Gateway is healthy at $GATEWAY_URL"
    fi
}

# 4. Provision Initial Virtual API Keys (RBAC Matrix)
provision_keys() {
    echo "🔑 [3/4] Provisioning RBAC Virtual API Keys..."

    # Developer Key: gpt-4o, claude-3-5-sonnet, mock-model ($5.00 daily budget, 30 RPM)
    echo "    Creating Developer Key ('sk-agent-developer')..."
    curl -s -X POST "$GATEWAY_URL/key/generate" \
      -H "Authorization: Bearer $MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "key": "sk-agent-developer",
        "key_alias": "sk-agent-developer",
        "models": ["gpt-4o", "claude-3-5-sonnet", "mock-model"],
        "max_budget": 5.0,
        "rpm_limit": 30,
        "duration": "1d",
        "metadata": {"role": "developer"}
      }' >/dev/null && echo "    ✅ Developer key provisioned." || echo "    ⚠️ Note: Check if key already exists."

    # Intern Key: Restricted to gpt-4o-mini & mock-model ($1.00 daily budget, 100 RPM)
    echo "    Creating Intern Key ('sk-agent-intern-poc')..."
    curl -s -X POST "$GATEWAY_URL/key/generate" \
      -H "Authorization: Bearer $MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "key": "sk-agent-intern-poc",
        "key_alias": "sk-agent-intern-poc",
        "models": ["gpt-4o-mini", "mock-model"],
        "max_budget": 1.0,
        "rpm_limit": 100,
        "duration": "1d",
        "metadata": {"role": "intern"}
      }' >/dev/null && echo "    ✅ Intern key provisioned." || echo "    ⚠️ Note: Check if key already exists."

    # CI Pipeline Key: Restricted to gpt-4o-mini & mock-model ($2.00 daily budget, 60 RPM)
    echo "    Creating CI Pipeline Key ('sk-agent-ci-pipeline')..."
    curl -s -X POST "$GATEWAY_URL/key/generate" \
      -H "Authorization: Bearer $MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "key": "sk-agent-ci-pipeline",
        "key_alias": "sk-agent-ci-pipeline",
        "models": ["gpt-4o-mini", "mock-model"],
        "max_budget": 2.0,
        "rpm_limit": 60,
        "duration": "1d",
        "metadata": {"role": "ci_pipeline"}
      }' >/dev/null && echo "    ✅ CI Pipeline key provisioned." || echo "    ⚠️ Note: Check if key already exists."

    # Budget-Capped Test Key: $0.0001 budget ceiling to verify HTTP 429
    echo "    Creating Budget-Capped Test Key ('sk-agent-budget-capped')..."
    curl -s -X POST "$GATEWAY_URL/key/generate" \
      -H "Authorization: Bearer $MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "key": "sk-agent-budget-capped",
        "key_alias": "sk-agent-budget-capped",
        "models": ["mock-model"],
        "max_budget": 0.0001,
        "duration": "1d",
        "metadata": {"role": "test_capped"}
      }' >/dev/null && echo "    ✅ Budget-capped key provisioned." || echo "    ⚠️ Note: Check if key already exists."
}

# 5. Display Summary and Endpoints
show_summary() {
    echo "=============================================================================="
    echo "🚀 AI Gateway PoC Stack is Ready!"
    echo "=============================================================================="
    echo "• Gateway Ingress:       $GATEWAY_URL/v1"
    echo "• Gateway Health:        $GATEWAY_URL/health"
    echo "• LiteLLM Admin UI:      $GATEWAY_URL/ui (Master Key: $MASTER_KEY)"
    echo "• Swagger API Docs:      $GATEWAY_URL/docs"
    echo "• Jaeger Distributed UI: http://localhost:16686"
    echo "• CPS Webhook Listener:  $CPS_URL/webhooks/github"
    echo "• SQLite Database:       $SCRIPT_DIR/data/gateway.db"
    echo "=============================================================================="
    echo "Test Commands:"
    echo "1. Test Allowed Request:"
    echo "   curl -X POST $GATEWAY_URL/v1/chat/completions \\"
    echo "     -H 'Authorization: Bearer sk-agent-developer' \\"
    echo "     -H 'Content-Type: application/json' \\"
    echo "     -d '{\"model\": \"mock-model\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello gateway\"}]}'"
    echo ""
    echo "2. Test RBAC Rejection (Intern attempting prohibited model):"
    echo "   curl -i -X POST $GATEWAY_URL/v1/chat/completions \\"
    echo "     -H 'Authorization: Bearer sk-agent-intern-poc' \\"
    echo "     -H 'Content-Type: application/json' \\"
    echo "     -d '{\"model\": \"gpt-4o\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}'"
    echo "=============================================================================="
}

case "${1:-all}" in
    --init-db)
        ;;
    --up)
        start_docker
        ;;
    --provision-keys)
        provision_keys
        ;;
    --summary)
        show_summary
        ;;
    all|--all)
        if command -v docker >/dev/null 2>&1; then
            start_docker
            provision_keys
        fi
        show_summary
        ;;
    *)
        echo "Usage: $0 [--init-db | --up | --provision-keys | --summary | --all]"
        exit 1
        ;;
esac
