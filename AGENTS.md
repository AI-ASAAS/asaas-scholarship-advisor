# AGENTS.md: ASAAS Scholarship Advisor Agent (وكيل المنح الدراسية)

Read this file first in every session. It is the short, current map of the project. The product source of truth is `docs/spec.md`; decisions live in `docs/decisions.md` (created in Phase 0). If this file and the code disagree, verify, then fix this file.

## 1. Product
An Arabic-first (RTL, phone-first) web agent that helps students find and apply for scholarships: it shows a curated top 10, lets the admin add grants from an official URL, matches a student's profile to grants with an explainable percentage, searches outside the platform, analyzes and strengthens the student's profile, helps prepare application documents, builds a personal application plan, monitors changes and deadlines, and answers questions in a scoped chat.

Audience: Yemeni students are first-class (default nationality, Yemen-focused copy and sources). Students of any nationality are supported through a generic nationality-eligibility model. Never hard-code Yemen into new logic.

## 2. The ten capabilities (from docs/spec.md) and their status
Status verified against the checked-out `orchestrator` branch. Update this table at the end of every phase.

| # | Capability | Observed status | Phase |
|---|---|---|---|
| 1 | Top 10 grants with details, conditions, deadlines, how to apply | Done (Curated `featured_rank` then nearest deadline; team priority endpoint/UI + structured modal) | 2 |
| 2 | Admin adds a grant from an official URL, extracted automatically, published after approval | Done (DRAFT -> admin publish, `extraction@2.0` structured conditions & `nationality_rule` via `modules/llm/`) | 2 |
| 3 | Personal advisor: student profile and match percentage | Done (`modules/students/`, `modules/matching/`, `PUT /api/students/profile`, `GET /api/matches`, wizard + matches UI) | 3 |
| 4 | External deep search with official sources and apply links | Done (`modules/search/`, full-profile query planner + SSRF/aggregator guard + `verify_evidence` + Phase 3 scoring + budget caps + 24h `external_search_cache` + `evals/external_search/` + `SearchPage`) | 7 |
| 5 | Profile analysis: strengths, weaknesses, gaps | Done (`modules/matching/analysis.py`, `POST /api/profile/analysis`, grounded findings + deterministic fallback + UI) | 3 |
| 6 | Profile strengthening suggestions | Done (`modules/documents/service.py`, `POST /api/documents/strengthening`, deterministic gaps + labeled prep assumptions + UI) | 5 |
| 7 | Application-document help (CV, motivation letter, recommendation support) | Done (`modules/documents/`, `ledger.py` FactsLedger, `POST /api/documents/generate`, `.txt` export, `DocumentsPage` UI) | 5 |
| 8 | Personalized application plan | Done (`modules/plans/`, `POST /api/plan/items`, `GET /api/plan`, `.ics` export, `PlanPage` UI, wired to `get_my_plan` tool) | 6 |
| 9 | Monitoring, freshness checks, deadline alerts | Done (`modules/notifications/`, `monitor_service.py` single-leader lock + staged `GrantChangeReview` admin queue, `14/7/3/1`d plan reminders + opt-in high-match alerts + `NotificationsPage` inbox) | 7 |
| 10 | Scoped conversational advisor | Done (`modules/assistant/`, `prompts/assistant.md` `assistant@1.0`, `POST /api/assistant` & `GET /api/assistant/status`, tool boundaries, `evals/advisor/`, `AdvisorAssistant` widget) | 4 |

## 3. Product decisions (do not reopen without telling the lead)
- Continue the existing repository. Preserve working interfaces and existing tests. Do not rewrite working agents, move working files, or migrate frameworks just to match a skill.
- **The code decides, the model explains.** A grant fact (deadline, GPA minimum, language level, eligibility, funding) is shown only with its source URL and a verbatim evidence quote verified by code. Match results, eligibility gates, deadlines, plan ordering and permissions are computed in code. The model may extract, explain, summarize and draft; it never decides eligibility, a deadline, a score or a permission.
- Admin approval stays: nothing from ingestion, external search or Telegram becomes a published grant without an admin action. The monitor never edits a published grant by itself.
- A match percentage means "how many of the grant's published conditions the student's stated profile meets". It is never the probability of admission. Unknown is reported as unknown, never as pass or fail.
- Scope: the chat and every generation feature stay inside scholarships and the advice around them; anything else gets one fixed Arabic refusal.
- Student data is sensitive: minimum collection, explicit consent, deletion and export on request, no name/email/phone/ID sent to a model provider, provider data collection denied, no prompts or personal data in logs.
- Documents: help the student improve THEIR OWN text. Never invent achievements, grades, institutions, dates or experience. Never write a ready-to-sign recommendation letter in a recommender's voice; produce a request message, a brief for the recommender, and structure guidance.
- Writes by the assistant are proposals; the student confirms through the normal endpoint.
- Arabic RTL, phone-first (375px) is primary; the existing English toggle keeps working.
- Hosting is undecided. Never deploy.

## 4. Codebase map (verified on branch `orchestrator`)
Back end (Python, FastAPI), currently split across two FastAPI apps + one shared matcher package:
- Discovery/admin API (port 8001): `api/main.py` (~454 lines, all discovery routes + static `frontend/dist` SPA fallback); `api/admin_auth.py` (`AdminAuthMiddleware`, enforces `X-Admin-Key` when `ADMIN_API_KEY` is set); `api/schemas.py` Pydantic contracts. Error contract: `{"message": ...}`.
- `core/config.py` settings from `.env` (`LLM_MODEL` defaults to `gemini-1.5-flash`; `.env.example` recommends `gemini-2.0-flash`); `core/db.py` SQLite (WAL) via SQLAlchemy 2.x; `core/models.py` `Grant`, `GrantStatus` (draft/published/expired), `YemeniEligibilityStatus`, `UpdateLog`; `core/repository.py` queries (`get_top_10_grants` orders by nearest deadline, NULL last). Schema is created with `create_all`; there are no migrations.
- `utils/llm_extractor.py` `LLMClient` (OpenAI-compatible, auto-routes Gemini/OpenRouter/Groq/OpenAI from key prefix/model, rejects `tvly-`, `max_tokens=1500`, `timeout=30.0`, 1 retry on JSON/validation error, accepts `prompt_version` without logging it) and `GrantExtractionSchema`; `utils/evidence_check.py` verbatim-quote check; `utils/url_validator.py` official-domain (`item in hostname` substring match) + HTTP 200 check.
- Root agents & integrations: `ingestion_sub_agent.py` URL -> fetch (`httpx`, no Playwright despite docstring) -> extract -> verify -> DRAFT; `external_search_sub_agent.py` bounded (5 steps) scripted "ReAct" search over Tavily/Serper with code verification (`StudentProfile` has only major, degree_level, target_country; no model call; does not load `prompts/react_search.md`); `monitor_service.py` SHA-256 change detection, `UpdateLog`, exact 7/3-day closing alerts, expiry, APScheduler, optional `ALERT_WEBHOOK_URL`; `integrations/telegram_watcher.py` reads approved channels, extracts official links, de-duplicates, feeds ingestion.
- Matcher/planner package (`ai/scholarship_agent/`): `schemas/scholarship_schemas.py`, `agents/matcher_evaluator_agent.py` (weighted scorer), `agents/llm_client.py` (separate LLM client), `tools/application_planner_tool.py`, `evals/matcher/cases.jsonl` (5 cases), `example.py`.
- Orchestrator platform (port 8010, `python -m agent_platform.main`): `src/agent_platform/` with `api.py` (~617 lines), `main.py`, `config.py`, `schemas.py`, `repos.py`, `knowledge.py` (read facade over `grants.db`), `memory.py` (SQLite `sessions.db` for profiles, transcripts, artifacts), `extraction.py`, `matching.py`, `planning.py`, `advisor.py`, `document_agent.py`, `orchestrator.py` (deterministic fallback), `guardrails.py`, `deadlines.py`, `resolution.py`, `llm.py` (3rd LLM client with retries, circuit breaker, single `LLM_FALLBACK_MODEL`, turn budget), `concurrency.py`, `observability.py` (`RequestContextMiddleware` with optional `API_KEY` and `RATE_LIMIT_PER_MINUTE`), and `graph/{builder,model,prompts,service,state,tools}.py`.
- `prompts/*.md`: `extraction.md` (`version: extraction@1.0`) and `react_search.md` (`version: react_search@1.0`). `seed/` (`seed_db.py`, `top10_urls.json` with 10 real grants). `docs/PLATFORM.md` (`docs/spec.md` and `skills/` are not yet on disk in this checkout). `scripts/llm_smoke.py`. `Dockerfile`, `docker-compose.yml`, `render.yaml`, `railway.json`, `pytest.ini`, `requirements.txt`, `requirements-deploy.txt`.
- `tests/`: pytest, **202 tests** total (45 in root `tests/` including 6 in `tests/test_admin_auth.py` + 157 in `tests/agent_platform/`). All 202 pass offline (`PYTHONPATH=.;src`, `AGENT_OFFLINE=1`). `tests/conftest.py` isolates `test_seed.py` to a temp DB, while `tests/test_api.py` creates `TestClient(app)` without lifespan (passes while `grants.db` exists in repo root; would fail on a clean DB).
- Discovery API routes (`api/main.py`): `GET /api/grants/top10`, `GET /api/grants`, `GET /api/grants/{grant_id}`, `POST /api/grants/{grant_id}/publish`, `POST /api/agents/ingest`, `POST /api/agents/search`, `POST /api/agents/monitor/run`, `GET /api/agents/monitor/logs`, `POST /api/agents/telegram/process`, `GET /api/system/status`, `POST /api/system/keys`, `GET /{full_path:path}` (SPA when `frontend/dist` exists).
- Platform API routes (`src/agent_platform/api.py`): `GET /`, `GET /health`, `GET /health/live`, `GET /health/ready`, `GET /api/grants/top10` (returns `{"count", "grants"}`), `POST /api/session`, `GET /api/profile/{session_id}`, `PUT /api/profile/{session_id}`, `POST /api/chat`, `POST /api/chat/stream`, `POST /api/documents`, `POST /api/match`, `POST /api/plan`, `POST /api/advisor`, `POST /api/session/{session_id}/reset`.

Front end (`frontend/`): React 19 + Vite + TypeScript, `react-router-dom`, the `asaas-ui` kit under `src/asaas-ui/`, typed Arabic/English dictionary in `src/lib/i18n.tsx`, API client in `src/lib/api.ts`, shared components in `src/components/`. Pages: Top10 (`/`), Search (`/search`), Admin (`/admin`), Monitor (`/monitor`). Connects only to Discovery API (`api/main.py`), not to `src/agent_platform/api.py`, and does not send `X-Admin-Key`.

Known gaps (verified on branch `orchestrator`; to be confirmed in `docs/baseline-audit.md`):
- Auth is opt-in and disabled by default: `ADMIN_API_KEY` (`api/admin_auth.py`) and `API_KEY` (`src/agent_platform/observability.py`) leave endpoints unauthenticated when unset (including publish and `POST /api/system/keys`, which writes keys into `.env`); `frontend/` does not send `X-Admin-Key`; no per-user student identity or session ownership check.
- No SSRF protection: redirects are followed (`follow_redirects=True`) and no private/loopback/metadata address check exists in `utils/url_validator.py`, `ingestion_sub_agent.py`, or `monitor_service.py` webhook; `is_trusted_domain` also allows substring matches (`item in hostname`).
- Eligibility is free-text lists; `Grant` has only a Yemen-specific `accepts_yemeni` field (`matching.py` infers GPA/language via regex and scores missing requirements as 100%).
- Discovery (`api/main.py`) and Platform (`src/agent_platform/api.py`) are two separate services with different `/api/grants/top10` schemas; `frontend/` does not yet expose chat, profile, matching, documents, or planning.
- Three separate LLM clients exist (`utils/llm_extractor.py`, `ai/scholarship_agent/agents/llm_client.py`, `src/agent_platform/llm.py`); only `src/agent_platform/llm.py` has retries/circuit breaker/single fallback model/turn budget, and none have token-usage logging or per-user quotas; `document_agent.py` and `application_planner_tool.py` still include student `name`/`email` in LLM prompts, and there is no explicit consent gate.
- `ai/scholarship_agent/evals/matcher/cases.jsonl` (5 cases) exists, but there is no root `evals/` folder covering extraction, chat, documents, or advisor.
- `playwright` and `crawl4ai` are listed in `requirements.txt` (omitted in `requirements-deploy.txt`) and are unused.

## 5. Architecture rules for new work
- Default (pending the Phase 0 decision D1): leave existing files in place; put every NEW capability in `modules/<name>/` using the backend skill's shape (`router.py`, `schemas.py`, `service.py`, `repository.py`; omit what is not needed), registered from `api/main.py`. Provider access for all model calls goes through one shared `modules/llm/`.
- Schema changes go through ordered migrations (mechanism decided in D2), never through `create_all`.
- Anything the application reads from a model is a validated Pydantic model; prompts are files in `prompts/` with a version tag logged on every call; every model call has `max_tokens`, a timeout and a bounded retry; model output is untrusted (never executed, never rendered as HTML).
- Every outbound fetch of a non-hardcoded URL goes through the one shared URL guard (Phase 1).
- Every new AI feature gets an evaluation set in `evals/<feature>/` (5 to 30 invented cases, deterministic checks first) and a recorded baseline.
- Monitor scheduling: APScheduler must run in a single dedicated leader process (`python -m monitor_service --schedule`, protected by `acquire_scheduler_lock`), never inside Uvicorn multi-worker lifespan.
- Reuse the existing pytest suite; extend it for deterministic logic. No new test framework, library or architectural layer without a justification in `docs/decisions.md`.

## 6. Skills map (in `skills/`)
Before ANY work in an area, read that area's foundation SKILL.md and the references it points to.
- Backend: `skills/backend/SKILL.md` (+ `references/project-structure.md`, `fastapi-patterns.md`, `database-and-migrations.md`; `ai-heavy-projects.md` only if a phase says so)
- Frontend: `skills/frontend/SKILL.md`, `skills/frontend/references/patterns.md`, `skills/frontend/asaas-ui/SKILL.md` (+ references `brand.md`, `components.md`, `assistant.md`)
- AI: `skills/ai/SKILL.md`, `skills/ai/references/llm-integration.md`, `assistant-pattern.md`, `evaluation.md`, `skills/ai/build-ai-agents/SKILL.md` (RAG is not used in this project; `rag-qdrant.md` only if a phase justifies it)
- Security: `skills/cyber/security-review/SKILL.md` + the references that apply. There is no `cyber/SKILL.md` foundation and `brand-identity` is empty; use security-review and `asaas-ui/references/brand.md`.
- `skills/readme.md` explains how to write new task skills.

For an EXISTING project the backend and frontend skills say to preserve established conventions and not to reorganize a working repository, and `build-ai-agents` says not to migrate frameworks or rewrite agents merely to match it. Record every deviation and its reason in `docs/decisions.md`; never deviate silently.

## 7. Working rules
- Work phase by phase. The lead sends one phase prompt at a time. Do only that phase, then STOP and send the report. Never start the next phase.
- Do not invent product requirements. Ask at most 5 focused questions, each with a recommended answer. For non-material gaps, state the assumption and keep it easy to change.
- Do not commit, push, deploy or change any external system unless the lead explicitly authorizes it.
- Never put secrets, real keys, real student data or Telegram session files in the repo, logs, tests, fixtures, evals or reports. Use invented students.
- Verify by running: the existing test suite, the API with real HTTP requests for a success path and at least one failure path (validation error, missing record, denied access), and the UI at 375px. Do not report something as verified unless you ran it.

## 8. Phase plan
| Prompt | Phase | Outcome |
|---|---|---|
| 1 | Phase 0 | Baseline audit, decisions (D1 to D13), data model |
| 2 | Phase 1 | Tests green, admin auth, URL guard, HTTP hardening |
| 3 | Phase 2 | Migrations, one LLM boundary, structured conditions, curated Top 10, `evals/` |
| 4 | Phase 3 | Student identity, profile, consent, matcher, profile analysis (3, 5) |
| 5 | Phase 4 | Scoped advisor chat (10) |
| 6 | Phase 5 | Strengthening and document help (6, 7) |
| 7 | Phase 6 | Application plan (8) |
| 8 | Phase 7 | Profile-aware external search and student alerts (4, 9) |
| 9 | Phase 8 | Full security audit, privacy pages, quality, documentation |

Decisions that need the lead or ASAAS management before Phase 3: D4 (student identity model) and D6 (GPA scale mapping, including Yemeni grade labels, which stays a marked assumption until confirmed).

## 9. Phase report format (end of every phase)
1. What was built or changed (file/module level, short).
2. What was verified, with the exact commands/requests/checks run and their results (include the full pytest summary line).
3. What could not be verified and why.
4. Deviations from skills or from the spec, with reasons.
5. Assumptions made.
6. Questions for the lead (max 5, each with your recommendation).
