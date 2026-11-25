# Full-Project Security Audit & Release Assessment (`docs/security/audit-report.md`)

**Date:** 2026-11-25  
**Scope:** Full-project audit of the ASAAS Scholarship Advisor Agent (`api/main.py`, `modules/*`, `core/*`, `utils/*`, `migrations/*`, `frontend/`, `prompts/*`, `evals/*`, `integrations/*`, `monitor_service.py`, `Dockerfile`, `render.yaml`, `railway.json`, and disposition of legacy `src/agent_platform/` & `ai/scholarship_agent/`).  
**Target State:** Post-Phase 8 hardening edits prior to deployment (`ENV=production` readiness check; not deployed).

---

## 1. Component Inventory & Lifecycle Disposition

| Component ID | Paths / Artifacts | Role & Exposure | Applicable Profiles | Disposition |
|---|---|---|---|---|
| **HTTP Edge & Static UI** | `api/main.py`, `api/schemas.py`, `frontend/dist` | Primary FastAPI service exposing `/api/*` and built React 19 SPA | `web-api`, `platform-supply-chain` | Inspected + runtime tested (`TestClient` & Chromium) |
| **Auth & Session Layer** | `modules/auth/{router,schemas,service}.py` | Admin login/cookie (`__Host-asaas_admin`), `X-Admin-Key`, anonymous opaque student cookie (`__Host-asaas_student`), CSRF Origin/`Sec-Fetch-Site` check | `web-api` | Inspected + negative/positive tests |
| **Student Data & Retention** | `modules/students/{router,schemas,service,repository,retention}.py` | Consent (`privacy-v1`), minimal academic profile, PII scrubber, export, atomic cascade deletion, D12 retention purge | `web-api`, `services-data-packages` | Inspected + time-shifted & cascade tests |
| **Matching & Planning** | `modules/matching/*`, `modules/plans/*` | Deterministic eligibility/GPA/match scoring, profile analysis, ranked application plans, `.ics` export | `web-api`, `ai-ml-systems`, `specialized-systems` | Inspected + pytest + live/stub evals |
| **Advisor Chat & Docs AI** | `modules/assistant/*`, `modules/documents/*`, `modules/llm/*`, `prompts/*.md` | Bounded tool-calling chatbot, strengthening + CV/SOP/recommendation brief, Facts Ledger, OpenAI-compatible client | `ai-ml-systems`, `specialized-systems`, `web-api` | Inspected + pytest + live/stub evals |
| **External Search & URL Guard** | `modules/search/*`, `external_search_sub_agent.py`, `ingestion_sub_agent.py`, `utils/{url_guard,url_validator,evidence_check}.py` | SSRF-guarded outbound fetcher (IPv4/IPv6 check, DNS pinning, max 3 hops, 2MB cap), official-domain allowlist, verbatim quote checker | `web-api`, `specialized-systems`, `services-data-packages` | Inspected + SSRF unit tests + evals + HTTP RBAC/rate tests |
| **Monitor & Telegram** | `monitor_service.py`, `modules/notifications/*`, `integrations/telegram_watcher.py` | SHA-256 portal monitor, staged admin change queue (`GrantChangeReview`), OS leader lock, deduplicated in-app alerts, Telegram URL filter | `services-data-packages`, `web-api` | Inspected + pytest on recorded posts & OS lock (`live Telethon` untested without creds) |
| **Database & Migrations** | `core/{config,db,models,repository}.py`, `migrations/{runner,v001..v007}.py`, `seed/*` | SQLite WAL / PostgreSQL SQLAlchemy 2.x schema + ordered migrations | `services-data-packages` | Inspected + fresh & upgrade migration tests |
| **Frontend Client** | `frontend/src/{pages,components,lib,asaas-ui,styles}/*` | React 19 + TypeScript + Vite SPA, typed `api.ts`, `safeHref`, `i18n.tsx` RTL/LTR | `web-api`, `platform-supply-chain` | Lint + `tsc -b` + Vite build + Playwright UI/CSP check |
| **Deploy & Dependencies** | `Dockerfile`, `render.yaml`, `railway.json`, `requirements*.txt`, `frontend/package*.json` | Container packaging, PaaS specs, npm lockfile & Python manifests | `platform-supply-chain` | Inspected (`requirements.txt` unpinned lockfile noted as `SEC8-05`) |
| **Legacy Prototype** | `src/agent_platform/*`, `ai/scholarship_agent/*` | Standalone prototype from pre-Phase 0 branch; **not launched** by `Dockerfile`, `render.yaml`, or `railway.json` | Assessed as non-deployed legacy | Retained untouched per D1; prior Phase 0 gaps remain if invoked standalone |

*Non-applicable profiles:* `client-native-devices` (no native mobile/desktop binaries, firmware, or IoT/OT components exist).

---

## 2. Trust Boundaries & Security Invariants

1. **Public vs. Admin Boundary**: Unauthenticated callers can only access public Top 10/published grants (`GET /api/grants/{id}` returns `404` for `DRAFT`/`EXPIRED`), `GET /api/health`, `GET /api/assistant/status` (`200` status metadata only), and `/privacy` & `/terms`. All state-changing admin routes, drafts/reviews, system status, and promote endpoints require `require_admin` failing closed when `ADMIN_API_KEY` is unset.
2. **Public vs. Paid/Stateful Student Endpoints**: After Phase 8 remediation (`SEC8-01`), `POST /api/search/external`, `POST /api/search/external/{run_id}/cancel`, `/api/matches`, `/api/profile/analysis`, `/api/documents/*`, `/api/plan/*`, and `/api/notifications/*` require `require_student` (`HttpOnly` cookie session) plus explicit consent where personal data is persisted.
3. **Cross-Student Isolation (IDOR)**: `session_id` is always derived server-side from SHA-256 of the `HttpOnly` cookie, never request payloads or URL path params. Active external search run cancellation binds `(budget, owner_session_id)`. Every repository read/update/delete scopes queries by `session_id`.
4. **Deletion, Retention & Backups Policy**: `DELETE /api/students/data` atomically deletes across `messages`, `plan_items`, `notifications`, `document_drafts`, `application_plans`, `conversations`, `student_profiles`, `student_consents`, `student_sessions`, and clears cookies. `external_search_cache` stores only normalized non-identifying search facets (no `session_id` or PII) and expires at 24h. `run_retention_cleanup` purges expired sessions/cache (`90d`/`24h`), chat (`30d`), inactive drafts (`90d`), and old read alerts (`90d`). Encrypted backups (daily hosting responsibility) age out per 30-day backup rotation.
5. **Outbound SSRF & Prompt-Injection Boundary**: `safe_request()` validates scheme, port (`80`/`443`), DNS IPv4/IPv6 ranges (blocking private/loopback/link-local/cloud-metadata), pins resolved TCP IP, checks every redirect (`<= 3`), enforces `2MB` byte caps and HTML/plain text `Content-Type`. Scraped text is untrusted: `verify_evidence()` strips unverified claims, `_deterministic_extract_verified` skips prompt-injection phrases, and neither external search nor monitor nor Telegram can auto-publish or auto-edit published grant fields.
6. **LLM Privacy & Rendering Boundary**: No `session_id`, name, email, phone, or national ID is passed to `AsyncLLMClient`; `scrub_pii_notes()` runs on both profile experience notes, document source text, AND user chat messages (`SEC8-04`). OpenRouter sets `provider: {"data_collection": "deny"}`. Frontend uses React auto-escaping with zero `dangerouslySetInnerHTML`, strict CSP (`script-src 'self'`), and `safeHref()` on every external URL.

---

## 3. Coverage Ledger & Executed Checks

| Control / Surface | Evidence Inspected | Method | Result | Remaining Gap / Rationale |
|---|---|---|---|---|
| **Auth, RBAC, Admin Login, Draft Privacy** | `modules/auth/*`, `api/main.py` | Code review + `tests/test_admin_auth.py`, `test_security_phase1.py`, `test_phase8_hardening_retention.py` | **Verified** | Production `ADMIN_API_KEY` secret rotation is deployment-owned |
| **Student Isolation, Consent, CSRF (`Sec-Fetch-Site`)** | `modules/students/*`, `modules/plans/repository.py`, `modules/documents/repository.py`, `modules/notifications/repository.py`, `modules/search/*` | Multi-principal HTTP tests + `test_phase8_hardening_retention.py` | **Verified** | Cookie `Secure` attribute tested false locally (`COOKIE_SECURE=true` required behind HTTPS proxy) |
| **Deletion & D12 Retention Job** | `modules/students/{repository,retention}.py` | Atomic delete tests + time-shifted `run_retention_cleanup` test | **Verified** | Production cron/worker process (`python -m monitor_service --schedule`) not run in live PaaS |
| **SSRF Guard & Redirects** | `utils/url_guard.py`, `utils/url_validator.py` | `tests/test_url_guard.py`, `test_security_phase1.py`, `evals/external_search` | **Verified** | Live internet redirect exploit tests excluded; verified via DNS/transport mocks |
| **XSS / CSP / `safeHref` / Accessibility** | `api/main.py` CSP, `frontend/src/*` | `git grep` sink scan, `npm run lint`, `npm run build`, Chromium Playwright (`360px`/`375px`/`1280px`) | **Verified** | Zero console/CSP errors observed across all tested routes |
| **AI Prompt Injection, PII Scrubbing, Cost/Rate Caps** | `modules/{assistant,documents,search,llm}/*` | Live Gemini & stub `evals/*`, `test_phase4..8` tests | **Verified** (`extraction` `14/15` live; `15/15` stub) | Gemini transient `429/503` affected 5 burst calls; `extraction` missed `edge-arabic-page` Yemen inference once |
| **Dependencies & Lockfiles** | `frontend/package-lock.json`, `requirements*.txt` | `npm audit --omit=dev` + `pip list` inspection | **Finding (`SEC8-05`)** | `npm audit` = `0` vulns; Python has no hash lockfile (`pip-audit` not installed offline) |
| **Secret Exposure** | Working tree & tracked files | `git grep` high-signal secret regexes (`AIza`, `sk-`, `tvly-`, `ghp_`) | **Verified** (`0` real keys; only test string `tvly-TestSearchKey5432` in `tests/test_api.py`) | Git history rewrite check not needed unless prior keys existed before Phase 0 |

---

## 4. Findings Ledger

### Fixed and Verified in Phase 8
- **[SEC8-01] High (Confirmed — Fixed & Verified) — Unauthenticated External Search & Unscoped Cancellation IDOR**
  - **Location**: `modules/search/router.py:33-69`, `modules/search/service.py:54-63, 303-325`
  - **Root Cause**: `POST /api/search/external` allowed anonymous `get_optional_student`, enabling unauthenticated external search + LLM token spend; `POST /api/search/external/{run_id}/cancel` checked `run_id` without verifying caller ownership.
  - **Fix**: Enforced `Depends(require_student)` on both `/external` and `/external/{run_id}/cancel`, added `ip_external_search_limiter`, and bound `_ACTIVE_BUDGETS` to `(budget, owner_session_id)`.
  - **Verification**: `test_phase8_hardening_retention.py` (`401` unauthenticated violating cases + `200` authenticated student + cross-student cancel returns `False`).

- **[SEC8-02] High (Confirmed — Fixed & Verified) — Missing Automated D12 Retention Enforcement**
  - **Location**: `modules/students/retention.py`, `monitor_service.py:272, 376-384`
  - **Root Cause**: `expires_at` and retention windows (`30d` chat, `90d` sessions/drafts, `24h` search cache) were configured without an active purge routine.
  - **Fix**: Implemented `run_retention_cleanup(db, *, now=None)` cleaning expired sessions (via atomic cascade), messages, empty conversations, drafts, read alerts, and expired cache; wired into `run_monitor_cycle()` and CLI `--retention`.
  - **Verification**: Time-shifted regression test (`test_d12_retention_cleanup_time_shifted`) verifying expired rows purged while active rows preserved.

- **[SEC8-03] High (Confirmed — Fixed & Verified) — Broken Container Packaging & Auth-Gated Deploy Healthcheck**
  - **Location**: `Dockerfile`, `render.yaml`, `railway.json`, `api/main.py` (`GET /api/health`)
  - **Root Cause**: `Dockerfile` omitted `COPY migrations/` and `COPY modules/` and ran as `root`; `render.yaml` and `railway.json` checked `/api/system/status` (which returns `401` without admin auth).
  - **Fix**: Added minimal unauthenticated `GET /api/health` (`{"status": "ok"}`), updated `Dockerfile` (`migrations/`, `modules/`, non-root `appuser`), and pointed healthchecks to `/api/health`.
  - **Verification**: `test_public_health_and_unauthenticated_external_search_blocked` + static config review. (`docker build` not executed on host).

- **[SEC8-04] Medium (Confirmed — Fixed & Verified) — Missing `Sec-Fetch-Site: cross-site` Guard & Unscrubbed User Chat Text**
  - **Location**: `modules/auth/service.py:112-116`, `modules/assistant/service.py:93-102`
  - **Root Cause**: Cookie-authenticated browser origin check relied on `Origin`/`Referer` when present without rejecting `Sec-Fetch-Site: cross-site`; user chat turns could forward accidentally pasted emails/phones to the LLM.
  - **Fix**: Explicitly reject `Sec-Fetch-Site: cross-site` on cookie mutations; apply `scrub_pii_notes()` to outbound `user` messages in `AssistantService`.
  - **Verification**: `test_phase8_hardening_retention.py` (`cross-site` blocked `401`/`403` without mutating DB; email/phone/ID scrubbed from `_SpyLLM` payloads).

### Open Findings & Hardening Opportunities
- **[SEC8-05] Medium (Confirmed — Open) — Unpinned Python Dependency Manifests (`>=`) Without Lockfile**
  - **Location**: `requirements.txt`, `requirements-deploy.txt`
  - **Impact & Mitigation**: Floating `>=` constraints without a hashed `requirements.lock` reduce build reproducibility and allow future upstream drift; also `requirements-deploy.txt` still installs `langgraph`/`langchain-*` (used only by legacy `src/agent_platform/`).
  - **Recommended Action**: Generate a pinned `requirements.lock` inside the Linux release build and drop unused `langgraph`/`langchain-*` from `requirements-deploy.txt` once legacy `src/agent_platform/` is formally retired.

- **[INFO-01] Informational / Known Gap — Live Telegram Channel Polling Untested**
  - `integrations/telegram_watcher.py` `fetch_channel_posts` (`Telethon`) was not executed against a live Telegram account (no credentials/session present). `process_telegram_posts` URL filtering and draft isolation were tested on recorded posts.

**Conclusion within reviewed scope:** **No unresolved confirmed Critical or High vulnerabilities were identified within the reviewed scope and checks performed.**

---

## 5. Release Readiness Recommendation

**Recommendation: HOLD RELEASE** pending completion of the following external ASAAS operational and legal gates (no unresolved confirmed Critical/High code defect remains):
1. **Legal & Management Sign-Off**: Review and approve `/privacy` and `/terms` (currently marked `DRAFT`), and remove draft notices before public launch.
2. **Academic Confirmation**: Validate Yemeni university grade-label equivalents (`ممتاز`, `جيد جداً`, `جيد`, `مقبول`) in `modules/matching/gpa_scales.json`.
3. **Production Environment & Supply-Chain Lock**: Provision `ENV=production`, strong `ADMIN_API_KEY`, `COOKIE_SECURE=true`, `CORS_ORIGINS`, reverse-proxy HTTPS + HSTS, chosen AI/Search keys (`LLM_PROVIDER`/`LLM_MODELS`), dedicated single-leader monitor process (`python -m monitor_service --schedule`), and pinned Python `requirements.lock` tested via `docker build`.
4. **Model Quality Baseline**: Re-run live evals cleanly under production quota without burst throttling and review the Arabic `"متاحة لجميع الجنسيات حول العالم"` extraction miss (`edge-arabic-page` in `evals/extraction`).
5. **Telegram Production Setup (Optional Feature)**: Configure approved `TELEGRAM_CHANNELS` and `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` if automated Telegram watching is enabled.
