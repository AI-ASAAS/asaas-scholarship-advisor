# Phase 0: Architecture & Product Decisions (`docs/decisions.md`)

**Date:** 2026-11-25  
**Scope:** Resolves D1–D13 and settles contradictions between `docs/spec.md`, the lead brief, and the checked-out `orchestrator` branch.

---

## Overarching Branch Reconciliation (`orchestrator` vs. Brief)

- **Context:** The `orchestrator` branch added `src/agent_platform/` (a second FastAPI service on port 8010 with LangGraph, `sessions.db`, and 157 tests) and `ai/scholarship_agent/`, while `api/main.py` (port 8001) + `frontend/` serves the ASAAS Discovery UI. Having two separate FastAPI apps, two SQLite files with duplicated `/api/grants/top10` logic, three LLM clients, and an unwired frontend contradicts the single-backend product and `AGENTS.md` architecture.
- **Decision:** Keep **`api/main.py` as the single primary FastAPI service and deployment boundary**. New capabilities (Phases 1–7) are built cleanly under `modules/<name>/` registered on `api/main.py` and wired into `frontend/`. Pure, tested domain helpers from `src/agent_platform/` (e.g., Arabic/English `guardrails.py` patterns, `deadlines.py`, `resolution.py`, `extraction.py` parsers, `document_agent.py` reflection structure, `planning.py` base step templates) will be reused/ported incrementally into `modules/*` rather than rewriting from scratch or operating two separate servers in production. `src/agent_platform/` stays untouched and its tests remain green until its capabilities are fully superseded in `api/main.py`.

---

## D1 — Layout Strategy

- **Context:** `skills/backend/SKILL.md` prefers `modules/<capability>/{router,schemas,service,repository}.py` with async SQLite (`aiosqlite`) and raw SQL. The existing discovery codebase uses flat files (`api/main.py`, `core/`, `utils/`, root agents) with synchronous SQLAlchemy 2.x.
- **Options Considered:**
  - **(A) Incremental modularization:** Leave existing working files (`core/`, `utils/`, root agents, `api/main.py` legacy routes) in place; place every **new** capability (and shared `modules/llm/`, `modules/auth/`, `modules/student/`, `modules/matching/`, `modules/assistant/`, `modules/documents/`, `modules/plan/`, `modules/notifications/`) in `modules/<name>/{router,schemas,service,repository}.py`, registered via `app.include_router(..., prefix="/api")` in `api/main.py`. Shrink `api/main.py` only when routes are naturally modified. Keep synchronous SQLAlchemy 2.x as the shared DB layer.
  - **(B) Full migration now:** Rewrite `core/`, `utils/`, and all agents into async `aiosqlite` + raw SQL `modules/`.
- **Recommendation:** **Option A.**
- **Trade-offs & Mixed-Convention Assessment:** Option B risks breaking 202 existing tests and violates the rule against rewriting working code. Option A has zero rewrite cost. The mixed convention (sync SQLAlchemy ORM in `core/` + modular `modules/<name>/` using `core/db.py` `Session`) creates **no technical blocker**: FastAPI executes `def` routes in a threadpool automatically, and blocking outbound HTTP/LLM calls in `async def` routes are either offloaded with `asyncio.to_thread` or executed via `httpx.AsyncClient` inside `modules/llm/`. The only minor friction is having both `Grant` ORM models in `core/models.py` and `TypedDict`/dict records in new repositories, which is cleanly bridged by `Grant.to_dict()`.
- **What Would Change It:** If sustained high write concurrency forces async PostgreSQL (`asyncpg`) across all endpoints, migrate `core/db.py` to `AsyncSession` in a dedicated phase.

---

## D2 — Schema Migrations

- **Context:** `core/db.py:53` uses `Base.metadata.create_all(bind=engine)`, which cannot add columns or backfill data on existing `grants.db` files. `skills/backend/references/database-and-migrations.md` requires ordered, versioned migrations. `render.yaml` and `railway.json` indicate PostgreSQL could be used later.
- **Options Considered:**
  - **(A) Small hand-rolled versioned migration runner (`migrations/`)** using SQLAlchemy `engine.begin()` + `text(...)` + a `schema_migrations(version, description, applied_at)` table (supporting both SQLite and PostgreSQL dialects).
  - **(B) Alembic** (`alembic/` env + revision scripts).
- **Recommendation:** **Option A (hand-rolled ordered SQLAlchemy-backed runner in `migrations/`).**
- **Trade-offs:** Aligns directly with `skills/backend/references/database-and-migrations.md`, adds **zero new dependencies**, keeps fresh-install and upgrade paths identical (running `run_migrations(engine)` in `lifespan` and CLI), and makes data backfills (e.g., populating structured eligibility from existing seeded grants) explicit and trivial to test with `pytest` on temporary SQLite DBs. Trade-off: DDL statements must be written carefully for SQLite/PostgreSQL portability (no autogenerate).
- **What Would Change It:** Switching exclusively to PostgreSQL with a larger team making frequent concurrent schema edits would justify adopting Alembic.

---

## D3 — LLM Provider Boundary

- **Context:** Three separate LLM clients currently exist (`utils/llm_extractor.py`, `ai/scholarship_agent/agents/llm_client.py`, `src/agent_platform/llm.py` + `graph/model.py`). Only `src/agent_platform/llm.py` has retries/circuit breaker/single fallback, none log token usage/cost, none set OpenRouter `data_collection: "deny"`, and `utils/llm_extractor.py` sniffs providers from API key prefixes.
- **Options Considered:**
  - **(A)** Build one shared `modules/llm/` package (`client.py`, `schemas.py`, `prompts.py`) per `skills/ai/references/llm-integration.md` (OpenAI-compatible `httpx`, explicit `LLM_BASE_URL` defaulting to OpenRouter with `provider: {"data_collection": "deny"}`, `LLM_MODELS` fallback list, timeouts, bounded retries, skip-on-400 fallback, `max_tokens`, prompt version & token/cost logging, fail-closed `LLMError`). Keep `utils/llm_extractor.py` (`extract_grant_from_text`, `LLMClient`) as thin backward-compatible adapters delegating to `modules/llm/` so existing ingestion tests keep passing.
  - **(B)** Keep separate clients per component.
- **Recommendation:** **Option A.**
- **Dev Convenience & Key Sniffing:** Replace implicit key-prefix sniffing in client business logic with explicit `LLM_BASE_URL` and `LLM_MODELS` in `core/config.py`. For developer convenience with non-OpenRouter keys (Gemini/Groq/OpenAI), support an explicit optional `LLM_PROVIDER` setting (or UI dropdown on Admin) that resolves the default `base_url` in `core/config.py` *only when `LLM_BASE_URL` is unset*; `LLM_EXTRA_BODY` defaults to `{"provider": {"data_collection": "deny"}}` for OpenRouter and `{}` when `LLM_BASE_URL` targets another provider. Always reject `tvly-` keys cleanly.
- **Trade-offs:** Slight adapter shim in `utils/llm_extractor.py` during Phase 2, repaid immediately by one telemetry/retry/privacy choke point across extraction, chat, documents, and search.
- **What Would Change It:** If a feature requires non-OpenAI-compatible multimodal/batch APIs only available via a vendor SDK, isolate that behind the same `modules/llm/` interface.

---

## D4 — Identity and Authorization

- **Context:** No student accounts exist today; `ADMIN_API_KEY` is opt-in and unprotected when unset; `frontend/` sends no admin key; `src/agent_platform` accepts client-supplied `session_id`s without ownership verification.
- **Options Considered:**
  - **Student identity:**
    - **(A1) Anonymous server-side student session:** Server issues an opaque random token (`secrets.token_urlsafe(32)`), stores its SHA-256 hash in `student_sessions`, sets an `HttpOnly`, `SameSite=Lax`, `Secure` (when HTTPS / non-localhost) cookie (`__Host-asaas_student` on HTTPS, `asaas_student` on localhost HTTP). Profile, consent, plans, drafts, chat, and notifications are keyed to `session_id` with export & hard-delete endpoints.
    - **(A2) Full student accounts (email + password / OAuth).**
  - **Admin auth:**
    - **(B1) Single `ADMIN_API_KEY` from env + `POST /api/admin/login`** (constant-time `hmac.compare_digest`, IP rate-limited 5 attempts/min, sets `HttpOnly`/`SameSite=Lax`/`Secure` admin session cookie; `X-Admin-Key` header also accepted for automated clients/tests). Fail **closed** (HTTP 503/401) if `ADMIN_API_KEY` is unset unless `ALLOW_INSECURE_LOCAL_ADMIN=1` is explicitly set in local dev.
    - **(B2) Integrate with an external ASAAS SSO/identity provider.**
- **Recommendation:** **A1 (Anonymous server-side student session) + B1 (`ADMIN_API_KEY` login + cookie/header)**, wrapped behind two FastAPI dependencies in `modules/auth/dependencies.py`:
  - `require_student(request) -> StudentPrincipal` (creates/validates session cookie; enforces CSRF Origin/Referer check on state-changing browser requests).
  - `require_admin(request) -> AdminPrincipal` (validates admin session cookie or `X-Admin-Key` header).
- **Trade-offs:** A1 satisfies minimum data collection and zero-friction mobile onboarding while preventing IDOR (since the ID comes from the `HttpOnly` cookie, never URL path params). Because all modules depend only on `require_student` / `require_admin`, swapping to ASAAS user accounts (A2/B2) later requires changing only `modules/auth/`.
- **Flagged for Lead Confirmation (Question 1):** Confirm A1 vs. full accounts for Phase 3, and confirm whether ASAAS already has an internal SSO/auth service to integrate for admins.

---

## D5 — Generic Nationality Eligibility Model

- **Context:** `core/models.py` only has `accepts_yemeni` (`yes`/`no`/`unclear`), and `external_search_sub_agent.py` + `matching.py` hard-code Yemen checks. Spec and brief require Yemeni students to be first-class defaults while supporting all nationalities generically.
- **Decision:**
  - Keep `accepts_yemeni` on `grants` and `GrantResponse` for backward compatibility (auto-derived when `nationality_rule` is evaluated for `"YE"`).
  - Add `nationality_rule` (JSON) per grant with schema:
    `{"mode": "all" | "include" | "exclude" | "group" | "unclear", "countries": ["YE", ...], "groups": ["developing_countries" | "isdb_members" | "non_eu" | "belt_and_road" | ...], "evidence": "<verbatim quote>"}`.
  - Maintain a versioned, code-owned mapping of recognized country groups (`COUNTRY_GROUPS` in `modules/matching/nationalities.py`) to ISO-3166 alpha-2 codes.
  - Default student nationality in UI and onboarding copy is `"YE"` (Yemen), and Yemen-focused grants/copy remain prominent, **but the matcher executes purely generic logic** (`evaluate_nationality(student.nationality_code, grant.nationality_rule)`).
- **Trade-offs:** Group definitions (e.g., "developing countries" list) are approximations if a donor uses a custom list; therefore, `mode="group"` marks `YE` / members as `met` only if in the verified group *and* displays the verbatim evidence quote with an official-portal verification reminder.

---

## D6 — Matching and Scoring Engine

- **Context:** `src/agent_platform/matching.py` uses an arbitrary weighted formula that awards `100.0` when grant requirements are missing and requires `gpa` up front, violating the spec's "percentage of published conditions met" and "unknown stays unknown" rules.
- **Decision:** Compute 100% of gates, criteria states, percentages, and coverage in deterministic Python code (`modules/matching/service.py`); the LLM never produces scores.
  1. **Hard Gates (`eligible: bool`, `disqualifiers: list`):**
     - `deadline` is in the past (`deadline < today`).
     - `nationality_rule` evaluates to `not_met` (explicitly excludes student's nationality or `include`/`group` excludes them).
     - `allowed_degrees` is stated and does not contain `student.target_degree`.
     - Failed hard gate => `eligible = False`, `match_percentage = 0.0` (with explicit reason + source evidence).
  2. **Criterion Evaluation (`met | not_met | unknown | not_applicable`):**
     - Evaluated per stated criterion: `nationality`, `degree_level`, `gpa`, `language`, `field_of_study`, `work_experience` (if `min_work_years` stated), `age` (if `max_age` stated).
     - If the grant does not publish a condition -> `not_applicable` (excluded from denominator).
     - If the grant publishes a condition and the student omitted that profile field -> `unknown` (never counted as pass or fail!).
  3. **Match Percentage & Coverage:**
     - `applicable` = all criteria where status != `not_applicable`.
     - `known` = criteria in `applicable` where status is `met` or `not_met`.
     - `match_percentage` = `round(sum(w_i for i in met) / sum(w_i for i in known) * 100, 1)` (0.0 if `known` is empty or `not eligible`).
     - `coverage_percentage` = `round(sum(w_i for i in known) / sum(w_i for i in applicable) * 100, 1)` (100.0 if `applicable` is empty).
     - Weights live in a versioned JSON config (`modules/matching/weights.json`, `version: "1.0"`). Default equal-or-priority weights: `nationality: 20, degree_level: 20, gpa: 20, language: 20, field_of_study: 10, work_experience: 5, age: 5`.
  4. **GPA Normalization Table (`modules/matching/gpa.py`) — ASSUMPTION (Verify with ASAAS):**
     - `4.0` scale: `value` directly.
     - `5.0` scale: `(value / 5.0) * 4.0`.
     - Percentage (`0–100%`): linear/piecewise configurable table (default `>=90 -> 3.85`, `80–89 -> 3.35`, `70–79 -> 2.75`, `65–69 -> 2.30`, `50–64 -> 1.80`, `<50 -> 1.00`, or exact linear `max(0, (pct - 50) / 50 * 3.0 + 1.0)` above 50%).
     - Yemeni grade labels (**ASSUMPTION — verify with ASAAS / Yemeni universities**): `ممتاز` -> `3.80`, `جيد جداً` -> `3.30`, `جيد` -> `2.60`, `مقبول` -> `2.00`, `ضعيف` -> `1.00`. Stored in `modules/matching/gpa_scales.json` so ASAAS can adjust without code changes.
- **Flagged for Lead Confirmation (Question 2):** Confirm the Yemeni GPA/grade-label mapping table.

---

## D7 — Curated Top 10 Ordering

- **Context:** `core/repository.py:14-36` orders `get_top_10_grants` solely by `deadline ASC NULLS LAST`, without admin curation.
- **Decision:** Add `featured_rank` (`Integer NULL`, e.g., `1..10`) to `grants` editable via an admin endpoint (`PATCH /api/grants/{grant_id}/featured`). Query orders published non-expired grants by:
  1. `featured_rank IS NULL ASC` (curated grants first),
  2. `featured_rank ASC`,
  3. `deadline ASC NULLS LAST`,
  4. `updated_at DESC`.
- **When fewer than 10 are curated:** Fill remaining slots up to 10 with published non-expired grants ordered by nearest deadline, and tag curated items (`is_featured: true`, `featured_rank`) so the UI clearly distinguishes team picks from deadline-sorted grants.

---

## D8 — Scoped Conversational Advisor Design

- **Context:** `skills/ai/references/assistant-pattern.md` prescribes one assistant with server-filtered tools, proposals for writes, `tool_choice="required"` on step 0, strict budgets, and one fixed refusal. `src/agent_platform` currently uses LangGraph and multiple category refusals.
- **Decision:** Follow `assistant-pattern.md` on `api/main.py` (`modules/assistant/`), wired to the `asaas-ui` `AssistantWidget` (`POST /api/assistant`, `GET /api/assistant/status`):
  - **Why single assistant with tools (not RAG, not multi-agent):** The verified catalog (10–few hundred structured grants) and the student's profile/plan fit cleanly in deterministic SQL/service tool calls without vector retrieval (`rag-qdrant.md` not justified), and one tool-calling loop handles all 10 capabilities without multi-agent handoff latency or failure modes.
  - **Tools:**
    - Read-only: `get_student_profile`, `list_top_grants`, `get_grant_details`, `compute_matches`, `get_profile_analysis`, `get_application_plan`, `get_notifications`.
    - Write proposals (`writes=True`, returns `{type: "proposal", ...}` confirmed via normal REST API): `propose_profile_update`, `propose_add_to_plan`.
  - **Limits:** `HISTORY_LIMIT = 8` messages, `max_length = 1500` chars/message, `MAX_STEPS = 5`, `max_tokens = 700`/step, `60` requests/hour per `student_session_id` (`429` with `Retry-After`), `tool_choice="required"` at step 0.
  - **Fixed Arabic refusal (contradiction resolved):** Any out-of-scope, prompt-injection, secret-extraction, fabrication, or cross-user privacy request returns **one fixed Arabic refusal constant**:
    `"عذراً، هذا المساعد مخصّص فقط للمنح الدراسية والاستشارات الأكاديمية المرتبطة بها. كيف أساعدك في ملفك أو منحك؟"` (with English toggle fallback only when UI/session explicitly requests English).
  - **Conversation memory:** Stored per `student_session_id` in `conversations` + `messages` (30-day TTL); profile and plan are always re-fetched fresh through tools on step 0 rather than trusted from old chat text.

---

## D9 — Application Documents Help & Facts Ledger

- **Context:** Spec Tasks 6–7 help students prepare/improve their own CV, motivation letter, and recommendation support without forging grades/achievements or writing signed recommendation letters.
- **Decision:**
  - **Outputs:**
    1. `cv`: Tailored academic CV structure + improved draft from student's real facts.
    2. `motivation_letter`: Tailored motivation letter / SOP draft or revision of student's pasted draft aligned to the target grant's criteria.
    3. `recommendation_support`: Three artifacts—(a) polite **request message** from the student to the professor/manager, (b) **recommender brief** summarizing verified student facts & target grant criteria, and (c) **structure checklist** for the recommender. **Never** a ready-to-sign letter in the recommender's voice.
  - **Facts Ledger (`FactsLedger`):** Before calling the LLM, code builds a ledger of verified claims from `student_profile` + the student's pasted source text (institutions, degrees, dates, GPA, test scores, jobs/projects, publications). After generation, deterministic verification scans numbers, GPAs, test scores, years/dates, URLs, emails, and capitalized proper/institution phrases in the draft against the ledger. Any unverified item is **not silently kept**—it is returned in `flagged_claims` with a prominent UI warning so the student must verify or remove it.
  - **MVP Input Mode — Pasted Text Only (No File Uploads):** Accepts sanitized pasted text (`max_length=8000`) rather than PDF/DOCX uploads. Reasons: eliminates parser vulnerabilities (PDF JavaScript/embedded streams, DOCX XML/XXE, zip bombs, polyglot files, malware scanning, temp-file lifecycle) and streamlines 375px mobile entry. File uploads can be added later with sandboxed text extraction.

---

## D10 — External Deep Search

- **Context:** `external_search_sub_agent.py` is currently a 5-step scripted pipeline with zero LLM calls, 3-field profile, and Yemen-only filtering.
- **Decision:** Preserve the deterministic code-verified pipeline (URL guard + official domain check + page fetch + verbatim evidence verification; read-only, never auto-published) and enhance it with two **bounded, schema-validated `modules/llm/` steps** (with deterministic fallback if LLM unavailable):
  1. **Query planner call (`SearchQueryPlan`):** Turns full student profile (degree, major, target fields, languages, nationality, target countries) into up to 3 targeted queries.
  2. **Structured page extractor call:** Runs verified fetched pages through `GrantExtractionSchema` v2 + `verify_evidence` so results include structured conditions, deadlines, and generic `nationality_rule` alongside verbatim quotes and apply links.
- **Why not CrewAI:** Per `skills/ai/build-ai-agents/SKILL.md`, *"A fixed sequence of calls is a pipeline, not an agent."* Search -> validate -> fetch -> extract -> verify is a fixed bounded pipeline; CrewAI adds unnecessary dependency/orchestration complexity.
- **Limits & Caching:** Max `3` search queries, max `5` pages fetched per request, `30s` total request budget, `10` searches/hour per student session, `24h` `external_search_cache` keyed by normalized profile hash. Admin can promote a verified external result to `DRAFT` for review.

---

## D11 — Monitoring & Student Alerts Delivery

- **Context:** `monitor_service.py` detects changes and 7/3-day deadlines for admin logs (`UpdateLog`) only; nothing reaches students.
- **Decision:**
  - **MVP Channel:**
    1. **In-app notification inbox** (`notifications` table keyed to `student_session_id`, surfaced in UI header badge + Notifications drawer/page) triggered after monitor cycles for grants saved in a student's `plan_items` (or matching their profile): `14d` / `7d` / `3d` deadline reminders (using `<=` window + `dedupe_key` instead of fragile `== 7`/`== 3`), `deadline_changed`, `content_changed`, and `grant_expired`.
    2. **Downloadable `.ics` calendar export** (`GET /api/plan/calendar.ics`) generated deterministically for the student's plan deadlines.
  - **Monitor invariant preserved:** Monitor still **never** auto-edits published grant content (except marking `EXPIRED` when `deadline < today` per existing behavior); field changes remain logged in `UpdateLog` for admin review.
  - **Future Channels (Email / Telegram Bot):** Will require verified contact info, explicit per-channel opt-in consent, unsubscribe/revocation support, and an async delivery outbox.

---

## D12 — Student Privacy, Minimization & Retention

- **Collected Fields:** `nationality` (default `"YE"`), `current_degree`, `target_degree`, `major`, `gpa_raw` + `gpa_scale`, `languages`, `target_countries`, `target_fields`, `work_experience_years`, anonymized experience/achievement bullets, `publications_count`, optional `age_years` (integer only, no DOB). **Not collected:** full name, email, phone, national ID, passport number, street address.
- **Model-Provider Boundary:** Only anonymized academic attributes reach `modules/llm/`. Regex/PII scrubber strips emails, phone numbers, and ID-like numeric sequences from student-pasted CV/draft text before LLM calls, and OpenRouter `provider: {"data_collection": "deny"}` is enforced. Prompts, scraped pages, and student profiles are **never** logged in production logs.
- **Consent & Lifecycle:** Explicit consent (`student_consents` with `consent_version`) required before creating/updating persistent profile, plan, or chat history. Retention: `90` days of session inactivity (`30` days for chat messages) enforced by periodic purge. Student has self-service `GET /api/student/export` (full JSON export) and `DELETE /api/student/data` (atomic cascade delete + cookie clear).

---

## D13 — Deviations from Company Skills

| Skill / Reference | Deviation | Reason |
|---|---|---|
| `skills/backend/SKILL.md` (`aiosqlite` + raw SQL) | Keep synchronous SQLAlchemy 2.x ORM on `core/db.py` while adding `modules/<name>/` | `backend/SKILL.md` instructs preserving established conventions in existing repos; avoids breaking 202 existing tests and keeps PostgreSQL portability. |
| `skills/backend/SKILL.md` (no test suite by default) | Keep and extend existing `pytest` suite | Project already has `pytest` with 202 tests; skill instructs preserving and extending existing tests when present. |
| `skills/ai/build-ai-agents/SKILL.md` (CrewAI default) | Do not adopt CrewAI; replace `src/agent_platform` LangGraph supervisor path with `assistant-pattern.md` tool-calling assistant on `api/main.py` | Both chat (`assistant-pattern.md`) and external search (bounded pipeline) fit simpler, lower-latency patterns explicitly preferred by `skills/ai/SKILL.md`. |
| `skills/ai/references/llm-integration.md` (OpenRouter-only `LLM_BASE_URL`) | Support optional `LLM_PROVIDER` presets in `core/config.py` when `LLM_BASE_URL` is unset | Existing developers/tests use direct Gemini/Groq/OpenAI keys; explicit config preset preserves DX without hardcoding provider sniffing inside `LLMClient`. |
| `skills/frontend/asaas-ui/SKILL.md` (`i18n` & layout) | Keep existing `frontend/src/lib/i18n.tsx` dictionary & `react-router-dom` setup while integrating `AssistantWidget` and new pages | Preserves existing working 4-page Arabic/English RTL UI per `frontend/SKILL.md`. |
