#!/usr/bin/env bash
# ==============================================================================
# Generic Agent / Tool Environment Configuration (OpenAI Compatible)
# ==============================================================================
# Source this file to configure any standard AI CLI, agent framework, or SDK
# (e.g. Aider, LangChain, LlamaIndex, AutoGen, CrewAI, Custom Agents):
#   source client_templates/generic_agent_env.sh
# ==============================================================================

# Route OpenAI SDK & HTTP client calls to the local AI Gateway
export OPENAI_BASE_URL="http://localhost:4000/v1"
export OPENAI_API_BASE="http://localhost:4000/v1"

# Provisioned virtual key (Developer role with access to gpt-4o, claude-3-5-sonnet, mock-model)
export OPENAI_API_KEY="sk-agent-developer"

# Default Model Selection
export OPENAI_MODEL="mock-model"

echo "✅ Agent environment configured for AI Gateway"
echo "   Endpoint : ${OPENAI_BASE_URL}"
echo "   Key      : ${OPENAI_API_KEY}"
echo "   Model    : ${OPENAI_MODEL}"
