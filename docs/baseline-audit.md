# Phase 0: Baseline Audit

**Date:** 2026-11-25  
**Branch / Revision:** `orchestrator` (`b76bc97`, tracking `fork/orchestrator`)  
**Auditor Note:** Conducted strictly as read-only inspection and test execution; no product code was modified. `AGENTS.md` and `docs/spec.md` were absent from disk at start (`AGENTS.md` was created from the lead's prompt text and corrected for the `orchestrator` branch prior to this audit).

---

## 1. Existing Test Suite Results & Root-Cause Analysis

### Run 1 — Default repository state (`grants.db` present at repo root)
Command executed (using uv Python 3.12 with `.venv\Lib\site-packages` because `.venv\pyvenv.cfg` points to a non-existent `W:\Anaconda\python.exe`):
```powershell
$env:PYTHONPATH = ".;src;.venv\Lib\site-packages"
$env:AGENT_OFFLINE = "1"
& "C:\Users\mahmoodSaeed\AppData\Roaming\uv\python\cpython-3.12.15-windows-x86_64-none\python.exe" -m pytest -q
```
- **Result:** `202 passed in 30.58s` (first run: `202 passed in 24.70s`; root `tests/` ignoring `tests/agent_platform`: `45 passed in 1.35s`; `tests/agent_platform/`: `157` tests).

### Run 2 — Clean database (`DATABASE_URL=sqlite:///<temp>.db`)
Command executed:
```powershell
$env:DATABASE_URL = "sqlite:///$tmpdb"
& "C:\Users\mahmoodSaeed\AppData\Roaming\uv\python\cpython-3.12.15-windows-x86_64-none\python.exe" -m pytest tests/test_api.py -q
```
- **Result:** `4 failed in 5.82s`:
  - `tests/test_api.py::test_api_system_status_and_top10`
  - `tests/test_api.py::test_api_error_contract_returns_message_field`
  - `tests/test_api.py::test_api_telegram_dry_run_filters_and_deduplicates`
  - `tests/test_api.py::test_api_update_keys_activates_live_and_masks_secrets`
- **Failure:** `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: grants`
- **Root Cause & Classification:** **Test-isolation bug** (not a product bug).
  - `tests/test_api.py:6` instantiates `client = TestClient(app)` at module scope without a `with TestClient(app):` context manager, so FastAPI's `lifespan` (`api/main.py:57-66`, which invokes `init_db()`) never executes.
  - `tests/conftest.py:21-24` only isolates `test_seed.py`, leaving `tests/test_api.py` dependent on whatever `grants.db` happens to exist on disk (`test_admin_auth.py:16` uses `with TestClient(app) as test_client:` and therefore runs the lifespan properly).
  - **Environment issue:** `.venv/pyvenv.cfg` hardcodes `home = W:\Anaconda`, breaking `.venv\Scripts\python.exe` and `.venv\Scripts\pytest.exe` on other machines.

---

## 2. Capability Coverage Table (10 Spec Capabilities)

| # | Capability (`docs/spec.md`) | Status | Where in Code | What Exists & What Is Missing |
|---|---|---|---|---|
| 1 | **Top 10 grants** (details, conditions, deadlines, how to apply) | **Partial** | `core/repository.py:14-36`, `api/main.py:223-227`, `seed/seed_db.py`, `frontend/src/pages/Top10Page.tsx`, `src/agent_platform/knowledge.py` | Displays up to 10 published non-expired grants with evidence modal. **Missing:** team curation/featured ranking (currently ordered solely by `deadline ASC NULLS LAST`), structured conditions, and unified response shape (`api/main.py` returns `List[GrantResponse]`, `agent_platform/api.py` returns `{"count", "grants"}`). |
| 2 | **Admin ingestion by official URL** (`DRAFT` -> approval) | **Partial** (core done) | `ingestion_sub_agent.py`, `utils/llm_extractor.py`, `utils/evidence_check.py`, `utils/url_validator.py`, `api/main.py:258-311`, `frontend/src/pages/AdminPage.tsx` | Fetches URL + 1 same-host sublink, extracts JSON via LLM (`temperature=0`), verifies verbatim quotes (`verify_evidence`), saves as `DRAFT`, admin publishes via `/publish`. **Missing:** SSRF/private-IP guard, structured eligibility fields (GPA/language/age/experience/nationality rule), model fallback list & usage logging, and `X-Admin-Key` header in `AdminPage`. |
| 3 | **Personal advisor & match percentage** | **Partial** | `src/agent_platform/matching.py`, `src/agent_platform/api.py:555-566`, `ai/scholarship_agent/agents/matcher_evaluator_agent.py` | Weighted scoring + disqualifiers exist in `agent_platform` (port 8010). **Missing/Gaps:** not wired to `api/main.py` or `frontend/`; computes weighted score where missing grant requirements score `100.0` instead of reporting `unknown` + coverage; requires `gpa` up front; uses `accepts_yemeni`-only nationality (`["Yemeni"]`/`["__ineligible__"]`/`[]`); infers GPA/language via regex from free text; no student auth/consent. |
| 4 | **External deep search** | **Partial** | `external_search_sub_agent.py`, `api/main.py:318-348`, `frontend/src/pages/SearchPage.tsx`, `src/agent_platform/graph/tools.py` | Bounded 5-step scripted pipeline calling Tavily/Serper via `httpx`, validating domain + HTTP 200, fetching page, checking verbatim quote + Yemen eligibility. **Zero LLM calls** (`prompts/react_search.md` is unused). **Missing:** full-profile query generation, structured condition/deadline extraction, generic nationality support (`check_yemen_eligibility` filters specifically on Yemen), SSRF guard, and search result caching. |
| 5 | **Profile analysis** (strengths, weaknesses, gaps) | **Partial** | `src/agent_platform/advisor.py:32-207`, `src/agent_platform/api.py:587-604` | Deterministic rule-based analysis of GPA, English level, test certs, research interests, publications, experiences, target countries, and internal match summary. **Missing:** not wired to `api/main.py` or `frontend/`; tied to `agent_platform` sessions without consent/auth; does not evaluate against structured per-grant conditions. |
| 6 | **Profile strengthening suggestions** | **Partial** | `src/agent_platform/advisor.py` (`AdvisorReport.actions`), `src/agent_platform/api.py:587-604` | Returns prioritized deterministic `AdvisorAction` items (`title`, `why`, `how`, `timeframe`, `priority`). **Missing:** not wired to `api/main.py` or `frontend/`; not personalized to specific target-grant gaps. |
| 7 | **Application-document help** (CV, motivation letter, recommendation support) | **Partial** | `src/agent_platform/document_agent.py`, `src/agent_platform/guardrails.py:373-457`, `src/agent_platform/api.py:520-552` | Implements `CV`, `MOTIVATION_LETTER`, and `RECOMMENDATION_BRIEF` (explicitly forbids signed letter) with a 4-stage reflection loop + numeric grounding checks. **Missing/Gaps:** not wired to `api/main.py` or `frontend/`; sends `profile.name` and `profile.email` to the LLM (`document_agent.py:148-149`); does not accept student-pasted CV/draft text to improve; lacks full facts-ledger check on institutions/dates/names. |
| 8 | **Personalized application plan** | **Partial** | `src/agent_platform/planning.py`, `ai/scholarship_agent/tools/application_planner_tool.py`, `src/agent_platform/api.py:568-585` | Generates prioritized `ScholarshipPlan` steps ordered by deadline with deterministic fallback and document lists. **Missing:** not wired to `api/main.py` or `frontend/`; not persisted as editable/trackable `plan_items` for the student; `application_planner_tool.py:89` includes `student.name` in LLM prompt. |
| 9 | **Monitoring, freshness checks, deadline alerts** | **Partial** | `monitor_service.py`, `api/main.py:355-390`, `frontend/src/pages/MonitorPage.tsx` | SHA-256 page change detection, `UpdateLog` recording without mutating published grants, exact 7-day and 3-day closing alerts + expiry (`EXPIRED`), APScheduler daemon, optional `ALERT_WEBHOOK_URL`. **Missing:** nothing reaches students (no student notification inbox, no `.ics` export); exact `== 7` / `== 3` day equality misses alerts if a daily run is skipped; no SSRF guard on URLs/webhook. |
| 10 | **Scoped conversational advisor (Chatbot)** | **Partial** | `src/agent_platform/api.py:481-517`, `src/agent_platform/orchestrator.py`, `src/agent_platform/graph/`, `src/agent_platform/guardrails.py`, `src/agent_platform/memory.py` | LangGraph supervisor + deterministic fallback, session memory (`sessions.db`), input/output guardrails, SSE streaming. **Missing/Gaps:** not wired to `api/main.py` or `frontend/` (`AssistantWidget` in `src/asaas-ui/assistant/` is unused); uses multiple refusal/redirect strings in AR/EN instead of one fixed Arabic refusal; writes by assistant mutate profile directly (`_profile_for` / `update_profile` tool) instead of returning student-confirmed proposals; sends `name`/`email` in system prompt (`graph/prompts.py:45-52`). |

---

## 3. Verification of "Known Gaps" in `AGENTS.md`

1. **Auth (`AGENTS.md` originally claimed "no authentication on any endpoint"):**
   - **Corrected.** `api/admin_auth.py:35-84` (`AdminAuthMiddleware`, registered at `api/main.py:91`) enforces `X-Admin-Key` on `/api/system/*`, `/api/agents/*`, `POST /api/grants/{id}/publish`, and `GET /api/grants` **when `ADMIN_API_KEY` is set**. Similarly, `src/agent_platform/observability.py:130-158` enforces `API_KEY` **when set**.
   - **Remaining gap:** Both are **disabled by default** when env vars are empty (`api/admin_auth.py:66-68`, `observability.py:145-146`), `frontend/src/lib/api.ts:145-162` never sends `X-Admin-Key`, and neither app has per-user student identity, login/cookie sessions, or session-ownership checks (`src/agent_platform/api.py:451-612`).
2. **SSRF protection:**
   - **Confirmed.** `utils/url_validator.py:94` and `ingestion_sub_agent.py:129` create `httpx.Client(timeout=timeout, follow_redirects=True)` with zero IP/DNS checks for loopback (`127.0.0.0/8`, `::1`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`), link-local/metadata (`169.254.169.254`, `fe80::/10`), or redirect targets. Additionally, `utils/url_validator.py:54` checks `item in hostname`, allowing domain-substring bypasses (e.g. `gov` matches `mygov-evil.com`). `monitor_service.py:52-53` also posts to `ALERT_WEBHOOK_URL` without validation.
3. **Eligibility free-text lists & `accepts_yemeni`-only field:**
   - **Confirmed.** `core/models.py:51-67` stores `eligibility`, `criteria`, `fields_of_study`, `required_documents` as untyped JSON string lists (`List[str]`), `deadline` as `Date`, and `accepts_yemeni` as `SAEnum(YemeniEligibilityStatus)`. `src/agent_platform/matching.py:143-258` parses GPA/language/degree with brittle regexes and maps `accepts_yemeni` to `["Yemeni"]` / `["__ineligible__"]` / `[]`.
4. **Evaluation sets & LLM client consolidation:**
   - **Partially corrected.** `ai/scholarship_agent/evals/matcher/cases.jsonl` exists (5 cases), while root `evals/` (for extraction, chat, documents, advisor, search) does not exist.
   - **Expanded finding:** There are **three** separate LLM clients: `utils/llm_extractor.py:70-206`, `ai/scholarship_agent/agents/llm_client.py:145-201`, and `src/agent_platform/llm.py:441-742` (+ `graph/model.py:43-261`). Only `src/agent_platform/llm.py` has retries, circuit breaker, single `LLM_FALLBACK_MODEL`, and turn budget; none log token usage/cost per call or enforce per-user quotas, and none send OpenRouter `provider: {"data_collection": "deny"}`.
5. **Unused dependencies (`playwright`, `crawl4ai`):**
   - **Confirmed** (plus `tavily-python` and `pytest-asyncio` — see Section 5).

---

## 4. Security Baseline (First Pass per `security-review`)

### 4.1 Endpoint Inventory & Authorization Surface

**Service A — Discovery & Admin API (`api/main.py`, port 8001)**

| Method & Path | Line | Auth Today | State / Side Effect | Target Auth |
|---|---|---|---|---|
| `GET /api/grants/top10` | `api/main.py:223` | Public | Read published grants | Public |
| `GET /api/grants/{grant_id}` | `api/main.py:246` | Public (**leaks DRAFT/EXPIRED grants**) | Read any grant by ID | Public only if `PUBLISHED`; admin for `DRAFT`/`EXPIRED` |
| `GET /api/grants` | `api/main.py:230` | `AdminAuthMiddleware` (open if `ADMIN_API_KEY` unset) | Read all grants incl. drafts | Admin |
| `POST /api/grants/{grant_id}/publish` | `api/main.py:258` | `AdminAuthMiddleware` (open if unset) | Publishes grant to public Top 10 | Admin |
| `POST /api/agents/ingest` | `api/main.py:274` | `AdminAuthMiddleware` (open if unset) | **Server-side URL fetch (SSRF)**, LLM spend, writes `DRAFT`, **writes keys to `.env`** | Admin (remove inline key persistence to `.env`) |
| `POST /api/agents/search` | `api/main.py:318` | `AdminAuthMiddleware` (open if unset) | **Outbound search + URL fetches (SSRF)**, **writes keys to `.env`** | Student (rate-limited) or Admin; remove inline key persistence to `.env` |
| `POST /api/agents/monitor/run` | `api/main.py:355` | `AdminAuthMiddleware` (open if unset) | Fetches all published URLs, writes `UpdateLog`, marks `EXPIRED`, posts webhook | Admin |
| `GET /api/agents/monitor/logs` | `api/main.py:367` | `AdminAuthMiddleware` (open if unset) | Reads `UpdateLog` | Admin |
| `POST /api/agents/telegram/process` | `api/main.py:397` | `AdminAuthMiddleware` (open if unset) | Parses posts, fetches URLs via `ingest()`, writes `DRAFT` | Admin |
| `GET /api/system/status` | `api/main.py:181` | `AdminAuthMiddleware` (open if unset) | Masked key hints, channel names, DB counts | Admin |
| `POST /api/system/keys` | `api/main.py:186` | `AdminAuthMiddleware` (open if unset) | **Mutates in-memory settings & writes `.env` on disk** | Admin (or disable runtime `.env` writes in production) |
| `GET /{full_path:path}` | `api/main.py:449` | Public | Serves `frontend/dist` static files / SPA fallback | Public |

**Service B — Platform Orchestrator API (`src/agent_platform/api.py`, port 8010)**

| Method & Path | Line | Auth Today | State / Side Effect |
|---|---|---|---|
| `GET /`, `/health`, `/health/live`, `/health/ready` | `401-432` | Public (even when `API_KEY` set) | Health/config summary (`repos_present`, `grants_available`, `llm_config_error`) |
| `GET /api/grants/top10` | `435` | `API_KEY` if set | Reads published grants |
| `POST /api/session` | `446` | `API_KEY` if set | Issues random `session_id` (no cookie, no binding) |
| `GET / PUT /api/profile/{session_id}` | `451, 464` | `API_KEY` if set (no per-student auth -> **IDOR** if `session_id` known/chosen when `STRICT_SESSION_IDS=0`) | Reads/merges student profile in `sessions.db` |
| `POST /api/chat`, `POST /api/chat/stream` | `481, 491` | `API_KEY` if set | LLM calls, profile mutation, transcript write in `sessions.db` |
| `POST /api/documents`, `/api/match`, `/api/plan`, `/api/advisor` | `520-604` | `API_KEY` if set | LLM calls, writes artifacts in `sessions.db` |
| `POST /api/session/{session_id}/reset` | `607` | `API_KEY` if set | Deletes session, messages, artifacts in `sessions.db` |

### 4.2 Findings Ledger (Prioritized by Severity)

| ID | Severity | Area | Evidence (File & Line) | Risk & Proposed Fix |
|---|---|---|---|---|
| **SEC-01** | **Critical** | Unauthenticated Admin & `.env` Mutation by Default | `api/admin_auth.py:66-68`; `api/main.py:148-154, 186-216, 276-283, 320-327`; `src/agent_platform/observability.py:145-146` | When `ADMIN_API_KEY` / `API_KEY` is unset, any caller can publish grants, trigger LLM/search spend, ingest URLs, and overwrite `.env` keys (`POST /api/system/keys`, or via `ingest`/`search` payloads). **Fix:** Fail closed on admin routes when `ADMIN_API_KEY` is unset (unless explicit local dev flag), add `POST /api/admin/login` with rate-limited constant-time check issuing `HttpOnly`/`SameSite=Lax` cookie, and remove runtime `.env` mutation from `ingest`/`search` (and restrict `POST /api/system/keys` or disable in production). |
| **SEC-02** | **High** | Server-Side Request Forgery (SSRF) & Weak Domain Allowlist | `utils/url_validator.py:54, 94`; `ingestion_sub_agent.py:129, 179`; `external_search_sub_agent.py:354, 373`; `integrations/telegram_watcher.py:143`; `monitor_service.py:52, 149` | `httpx.Client(follow_redirects=True)` fetches admin URLs, search URLs, Telegram-extracted URLs, same-host sublinks, and `ALERT_WEBHOOK_URL` with no check against loopback, private, link-local, or cloud-metadata IPs, and no redirect revalidation. `is_trusted_domain` (`item in hostname`) allows `gov.attacker.com`. **Fix:** Implement one shared `utils/url_guard.py` (Phase 1) that enforces `https`/`http`, exact/suffix domain matching, DNS resolution + connected-socket IP check rejecting all non-global IPs (IPv4/IPv6), manual hop-by-hop redirect re-validation (max 3 hops), response size cap (e.g. 2 MB), and strict timeouts. |
| **SEC-03** | **High** | Student PII Sent to Model Providers & Missing Consent/Ownership | `src/agent_platform/schemas.py:90-97`; `document_agent.py:148-149`; `graph/prompts.py:45-52`; `ai/scholarship_agent/tools/application_planner_tool.py:89`; `src/agent_platform/api.py:451-612` | `name` and `email` are sent to external LLM providers without OpenRouter `provider: {"data_collection": "deny"}`. No consent table/gate exists, and `session_id` has no server-side cookie/ownership verification (`STRICT_SESSION_IDS=0` default allows arbitrary session IDs -> IDOR). **Fix:** Drop `name`/`email` from required profile and from all LLM payloads, enforce `data_collection: deny`, bind student identity to opaque `HttpOnly` cookie sessions (`require_student`), and require explicit consent before persisting/processing. |
| **SEC-04** | **High** | Indirect Prompt Injection & Unbounded Webpage Text to LLM | `ingestion_sub_agent.py:188`; `utils/llm_extractor.py:216-223` | Raw scraped HTML text (main page + subpage) is passed unbounded into the LLM `user` prompt with no truncation cap or untrusted-data framing. While `evidence_check.py` blocks fabricated quotes, an adversarial page could place prompt instructions inside legitimate page text to manipulate `description`/`how_to_apply` or exhaust tokens. **Fix:** Cap extracted text size (e.g. 24k chars), frame scraped text as untrusted data inside extraction prompt `v2.0`, enforce `max_tokens` and schema `Field(max_length=...)` bounds, and treat all extracted output as untrusted text (never HTML). |
| **SEC-05** | **Medium** | Public Draft Exposure (`GET /api/grants/{grant_id}`) | `api/main.py:246-255` | `GET /api/grants/{grant_id}` is not covered by `AdminAuthMiddleware` (`api/admin_auth.py:35-47`) and returns `DRAFT` or `EXPIRED` grants to unauthenticated callers. **Fix:** Restrict `GET /api/grants/{grant_id}` to `PUBLISHED` grants for public callers; require `require_admin` for `DRAFT`/`EXPIRED`. |
| **SEC-06** | **Medium** | Raw Exception Leakage & Inconsistent Error Contract | `api/main.py:345-348, 361-364`; `src/agent_platform/api.py:275-282, 532-537`; `src/agent_platform/observability.py:132, 138` | `/api/agents/search` and `/api/agents/monitor/run` embed raw `{exc}` strings into 502/500 error details (can expose internal URLs, SQLite paths, or httpx internals). `agent_platform` returns `{"detail": ...}` instead of ASAAS `{"message": ...}`. **Fix:** Log full exception server-side (`logger.exception`), return generic localized `{"message": ...}` errors publicly, and unify error handlers. |
| **SEC-07** | **Medium** | Permissive CORS Methods/Headers & Missing Security Headers on Discovery App | `api/main.py:75-88`; `src/agent_platform/api.py:377-384` | `api/main.py` sets `allow_credentials=True` with `allow_methods=["*"]`, `allow_headers=["*"]`, hardcoded localhost origins, and lacks `X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy` headers (unlike `agent_platform/observability.py:188-190`). **Fix:** Explicitly list allowed methods/headers, make `CORS_ORIGINS` env-configurable on `api/main.py`, and add security headers middleware. |
| **SEC-08** | **Low / Hardening** | Unbounded Input Lengths & Missing Rate Limits on Discovery App | `api/main.py` (no rate limiter); `api/schemas.py:68-73` (`TelegramProcessRequest.posts` items unbounded) | No rate limiting on discovery endpoints or future login/chat endpoints. **Fix:** Add sliding-window `RateLimiter` for auth, search, and assistant routes (`utils/rate_limit.py`). |

---

## 5. Dependency Audit (`requirements.txt` & `requirements-deploy.txt`)

Verified via AST import scan across all non-vendored `.py` files in the repository:

| Package | In `requirements.txt` | In `requirements-deploy.txt` | Imported in Repo? | Notes / Impact |
|---|---|---|---|---|
| `pydantic` | Yes | Yes | Yes (`api/`, `core/`, `utils/`, `ai/`, `src/`) | Core schema validation. |
| `python-dotenv` | Yes | Yes | Yes (`api/main.py`, `core/config.py`, `src/agent_platform/config.py`, `scripts/`) | Loads `.env`. |
| `SQLAlchemy` | Yes | Yes | Yes (`core/`, `src/agent_platform/knowledge.py`, tests) | ORM & SQLite/PostgreSQL engine. |
| `httpx` | Yes | Yes | Yes (`api/`, `utils/`, root agents, `src/agent_platform/`) | HTTP client for scraping, search APIs, webhooks, LLM. |
| `beautifulsoup4` (`bs4`) | Yes | Yes | Yes (`ingestion_sub_agent.py`, `utils/url_validator.py`) | HTML parsing. |
| `fastapi` | Yes | Yes | Yes (`api/main.py`, `src/agent_platform/api.py`) | HTTP framework. |
| `uvicorn` | Yes | Yes | Yes (`src/agent_platform/main.py`, CMD) | ASGI server. |
| `APScheduler` | Yes | Yes | Yes (`monitor_service.py`) | Optional CLI `--schedule` daemon. |
| `telethon` | Yes | Yes | Yes (`integrations/telegram_watcher.py`) | Optional live Telegram channel reader. |
| `langgraph`, `langchain-core`, `langchain-openai` | Yes | Yes | Yes (`src/agent_platform/graph/`) | Heavy dependency tree used only by `src/agent_platform/graph/`; removable once chat migrates to `modules/assistant/` on `modules/llm/`. |
| `playwright` | **Yes** | No | **NO** (0 imports) | **Unused.** Large binary/browser footprint (~150–400 MB with browsers) and unnecessary attack surface. Remove in Phase 1. |
| `crawl4ai` | **Yes** | No | **NO** (0 imports) | **Unused.** Pulls heavy scraping/ML sub-dependencies. Remove in Phase 1. |
| `tavily-python` | **Yes** | No | **NO** (0 imports) | **Unused.** `external_search_sub_agent.py:97` calls `https://api.tavily.com/search` directly via `httpx`. Remove in Phase 1. |
| `pytest` | Yes | No | Yes (`tests/`) | Test runner. |
| `pytest-asyncio` | **Yes** | No | **NO** (0 async tests) | Only referenced by `pytest.ini:2`; keep or drop unless async tests are added in Phase 1+. |
| *(Transitive / Missing explicit)* `pydantic-settings` | No | No | No | Referenced by `skills/ai/references/llm-integration.md`; current `core/config.py` uses `pydantic.BaseModel` + `dotenv`, so no new dependency is needed. |
