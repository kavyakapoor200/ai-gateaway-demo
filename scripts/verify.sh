#!/usr/bin/env bash
# ==============================================================================
# verify.sh: 1-Command Automated Verification Runbook for Minimal Local AI Gateway
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================================================="
echo "   Minimal Local AI Gateway PoC: Automated Runbook Verification"
echo "=============================================================================="

# Check if LiteLLM is reachable
GATEWAY_URL="${GATEWAY_URL:-http://localhost:4000}"
if ! curl -s "$GATEWAY_URL/health/liveliness" >/dev/null 2>&1; then
    echo "⚠️ Gateway at $GATEWAY_URL is not responding."
    echo "   Attempting to start services via setup.sh..."
    bash "${SCRIPT_DIR}/setup.sh" --up
fi

# Run the 7-Step Verification Suite
echo "🚀 Executing 7-Step Verification Runbook..."
python3 "${SCRIPT_DIR}/../tests/test_verification_runbook.py"
