#!/usr/bin/env bash
# ==============================================================================
# Claude Code / Anthropic Client Environment Configuration
# ==============================================================================
# Source this file before launching Claude Code CLI or Anthropic SDK agents:
#   source client_templates/claude_env.sh
# ==============================================================================

# Route all Anthropic SDK / Claude traffic to the local AI Gateway
export ANTHROPIC_BASE_URL="http://localhost:4000/v1"
export ANTHROPIC_API_BASE="http://localhost:4000/v1"

# Developer virtual key provisioned on the gateway
export ANTHROPIC_API_KEY="sk-agent-developer"

# Preferred default model (governed by gateway-level RBAC whitelist)
export ANTHROPIC_MODEL="claude-3-5-sonnet"

echo "✅ Claude Code environment configured for AI Gateway (http://localhost:4000/v1)"
echo "   Key: ${ANTHROPIC_API_KEY} | Model: ${ANTHROPIC_MODEL}"
