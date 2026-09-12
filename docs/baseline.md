# QueryMind Import Baseline

Captured on 2026-09-08 before the InsightForge Agent rebrand and feature development.

## Source baseline

- Baseline tag: `baseline-querymind-import`
- Development branch: `codex/rebrand-insightforge`
- Imported application version: `6.2.0`

## Automated tests

- Result: 11 passed
- Duration: 1.42 seconds
- Warning: LangGraph reports one pending deprecation warning for the default `allowed_objects` value.

## Runtime health

- API status: `ok`
- Runtime: LangGraph + PostgreSQL Checkpoint
- LLM: `qwen-plus`
- PostgreSQL: healthy
- pgvector: enabled
- Redis worker: online
- Northwind rows: 3,204

## Browser smoke test

- Main page: HTTP 200
- Stylesheet and JavaScript: HTTP 200
- Public configuration and thread list APIs: HTTP 200
- ECharts CDN dependency: HTTP 200
- Known non-blocking issue: `/favicon.ico` returns HTTP 404

The corresponding UI screenshot is stored as `docs/baseline-ui.png`.
