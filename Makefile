.PHONY: api-dev web-dev seed test test-api test-web build-web smoke stream-smoke

api-dev:
	cd services/api && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web-dev:
	cd apps/web && npm run dev

seed:
	PYTHONPATH=services/api python -m app.seed

test: test-api test-web

test-api:
	PYTHONPATH=services/api python -m unittest discover -s services/api/tests -v

test-web:
	cd apps/web && npm test

build-web:
	cd apps/web && npm run build

smoke:
	python scripts/e2e_smoke.py

stream-smoke:
	python scripts/stream_smoke.py
