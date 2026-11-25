# Deployment Guide (`docs/deploy.md`)

> Do not deploy without completing the Pre-Launch Checklist and ASAAS legal/academic approvals.

---

## 1. Process Model (HTTPS Proxy -> Web App + Single Monitor Process)

```text
Internet (HTTPS :443)
   │  Reverse Proxy (Nginx / Caddy / Cloud Ingress: TLS + HSTS)
   ▼  X-Forwarded-For (proxy IP listed in TRUSTED_PROXIES)
Container / Host Process 1:
   uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
   (Serves FastAPI /api/* + built frontend/dist SPA assets; healthcheck -> GET /api/health)

Container / Host Process 2 (EXACTLY ONE INSTANCE):
   python -m monitor_service --schedule --interval 24
   (Enforces OS lock acquire_scheduler_lock; runs page checks, student alerts & D12 retention)
```

---

## 2. Reverse Proxy, TLS & HSTS

The application intentionally does **not** terminate TLS or emit `Strict-Transport-Security` from inside Uvicorn (avoiding HSTS traps on local HTTP dev servers). Configure the reverse proxy or edge load balancer to:
1. Redirect all HTTP (`:80`) traffic to HTTPS (`:443`).
2. Terminate TLS 1.2/1.3 with valid certificates.
3. Add `Strict-Transport-Security: max-age=31536000; includeSubDomains` only after confirming HTTPS works cleanly across the domain.
4. Pass the real client IP in `X-Forwarded-For` and set `TRUSTED_PROXIES` in `.env` to the proxy's internal IP(s) so `get_client_ip()` resolves client IPs accurately without trusting spoofed headers.
5. Set `COOKIE_SECURE=true` in production so admin (`__Host-asaas_admin`) and student (`__Host-asaas_student`) cookies require HTTPS.

---

## 3. Required Production Environment Variables

| Variable | Required? | Notes |
|---|---|---|
| `ENV` | **Yes** (`production`) | Disables dev key endpoints (`ENABLE_DEV_KEYS_ENDPOINT`), `.env` writes, and insecure admin bypasses. |
| `DATABASE_URL` | **Yes** | `sqlite:///data/grants.db` (single host persistent volume) or PostgreSQL URL (`postgresql+psycopg2://...`). |
| `ADMIN_API_KEY` | **Yes** | High-entropy random secret (`>= 32` chars). Fails closed (`401`/`503`) if omitted. |
| `COOKIE_SECURE` | **Yes** (`true`) | Required on HTTPS so `__Host-` `HttpOnly` cookies stay encrypted in transit. |
| `CORS_ORIGINS` | **Yes** | Comma-separated exact HTTPS public origin(s) (e.g. `https://scholarships.asaas.ai`). |
| `TRUSTED_PROXIES` | Recommended | Proxy IP(s) allowed to supply `X-Forwarded-For`. |
| `LLM_PROVIDER` / `LLM_MODELS` / `LLM_API_KEY` | **Yes** (for AI) | Explicit provider (`openrouter` recommended for `data_collection: deny`, or `gemini`/`openai`) + model chain + server key. |
| `TAVILY_API_KEY` / `SERPER_API_KEY` | Optional | Enables Capability #4 live external search (`POST /api/search/external`). |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_CHANNELS` | Optional | Required only for live Telegram polling (`integrations/telegram_watcher.py`). |
| `ALERT_WEBHOOK_URL` | Optional | HTTPS webhook destination validated through `utils/url_guard.py`. |

---

## 4. Container Build & Verification

`Dockerfile` uses a multi-stage build:
- Stage 1 (`node:22-alpine`): installs `frontend/package-lock.json` via `npm ci` and runs `npm run build`.
- Stage 2 (`python:3.12-slim`): installs `requirements-deploy.txt`, copies `api/`, `core/`, `migrations/`, `modules/`, `utils/`, `prompts/`, `seed/`, `integrations/`, `ai/`, `src/`, `*.py`, plus compiled `frontend/dist`, switches to non-root user `appuser`, and runs `uvicorn api.main:app`.
- **Important**: Generate a pinned Python `requirements.lock` (e.g., `pip freeze > requirements.lock` or `uv pip compile`) in your target Linux build image before production release.

---

## 5. Pre-Launch Checklist

- [ ] `ENV=production`, `COOKIE_SECURE=true`, `ENABLE_DEV_KEYS_ENDPOINT=false`, `ALLOW_INSECURE_LOCAL_ADMIN=false`, `ALLOW_RUNTIME_ENV_WRITE=false`.
- [ ] `ADMIN_API_KEY` generated cleanly (never in Git/build logs) and stored in platform secrets manager.
- [ ] Database migrations applied (`python -c "from core.db import engine; from migrations.runner import run_migrations; run_migrations(engine)"` or via app lifespan) and initial Top 10 grants verified.
- [ ] Dedicated single monitor worker (`python -m monitor_service --schedule`) configured with persistent lock volume if SQLite is used.
- [ ] Legal/management sign-off received on `/privacy` and `/terms` drafts (remove DRAFT banners after approval).
- [ ] Academic sign-off received on Yemeni GPA labels in `modules/matching/gpa_scales.json`.
- [ ] All live `evals/` (`extraction`, `profile_analysis`, `advisor`, `documents`, `external_search`) passed on the chosen production model and cost/latency reviewed.
- [ ] Reverse proxy TLS + HSTS verified, and `GET /api/health` returning `200 {"status": "ok"}`.
