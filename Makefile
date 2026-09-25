# ==============================================================================
# Minimal Local AI Gateway Makefile
# Standardized Developer Workflow Targets
# ==============================================================================
.PHONY: help up down restart logs ps test verify test-mcp clean setup

SHELL := /usr/bin/env bash
PYTHON ?= python3

help:
	@echo "Available commands:"
	@echo "  make setup       Bootstrap local database, .env, and start containers"
	@echo "  make up          Start the AI Gateway multi-container stack"
	@echo "  make down        Stop all gateway services"
	@echo "  make restart     Restart the gateway containers"
	@echo "  make logs        Follow litellm gateway container logs"
	@echo "  make ps          List running gateway service containers"
	@echo "  make test        Execute all test suites in tests/"
	@echo "  make test-mcp    Run MCP tool interrupt & Ingress PEP verification"
	@echo "  make verify      Execute 7-step automated verification runbook"
	@echo "  make clean       Remove Python bytecode and transient caches"

setup:
	bash setup.sh

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart litellm cps_webhook

logs:
	docker compose logs -f litellm

ps:
	docker compose ps

test:
	@echo "==> Running Phase 1 Tests (Schema, Ledger, ZDR)..."
	$(PYTHON) tests/test_phase1.py
	@echo "==> Running Phase 2 Tests (CPS Webhook, PR Reconciliation)..."
	$(PYTHON) tests/test_phase2.py
	@echo "==> Running Phase 3 Tests (RBAC, Rate Limits, Fallbacks)..."
	$(PYTHON) tests/test_phase3.py
	@echo "==> Running MCP Interrupt PEP Tests..."
	$(PYTHON) tests/test_mcp_interrupt.py

test-mcp:
	$(PYTHON) tests/test_mcp_interrupt.py

verify:
	bash verify.sh

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
