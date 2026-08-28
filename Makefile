.PHONY: install start dev test test-backend test-frontend

install:
	python3.12 -m venv .venv
	env -u SSLKEYLOGFILE .venv/bin/pip install -e 'backend[dev]'
	cd frontend && pnpm install

test: test-backend test-frontend

test-backend:
	cd backend && env -u SSLKEYLOGFILE ../.venv/bin/pytest

test-frontend:
	cd frontend && pnpm test

dev:
	./scripts/dev.sh

start:
	./start.sh
