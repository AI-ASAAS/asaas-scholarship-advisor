# Architecture: ASAAS Scholarship Advisor Agent

**Primary Deployment Service:** `api/main.py` (Single FastAPI service serving both `/api/*` JSON routes and optional compiled SPA assets under `frontend/dist`).

> Note: Legacy `src/agent_platform/` (from early branch prototyping) remains isolated and is **not** exposed or launched by `Dockerfile`, `render.yaml`, or `railway.json`.

---

## 1. Module Inventory (`modules/`, `core/`, `utils/`, `migrations/`)

| Module / Layer | Responsibility | Key Files |
|---|---|---|
| **Auth & Sessions** | Admin secret verification (`ADMIN_API_KEY`, HMAC cookie / `X-Admin-Key`), opaque server-side student sessions (`__Host-asaas_student`), CSRF/Origin + `Sec-Fetch-Site` check | `modules/auth/{router,schemas,service}.py` |
| **LLM Boundary (D3)** | Single `httpx.AsyncClient` OpenAI-compatible boundary, explicit `LLM_PROVIDER`/`LLM_BASE_URL`, fallback model chain (`LLM_MODELS`), OpenRouter `data_collection: deny`, token/latency logging, JSON Schema validation + 1 retry | `modules/llm/{client,prompts,schemas}.py`, `prompts/*.md` |
| **Students & Privacy (D4, D12)** | Minimal academic profile storage, explicit versioned consent (`privacy-v1`), regex PII scrubber (`scrub_pii_notes`), JSON data export, atomic cascade deletion, automated retention purge | `modules/students/{router,schemas,service,repository,retention}.py` |
| **Matching & Analysis (D5, D6)** | 100% deterministic code-computed eligibility gates, generic nationality rules (`COUNTRY_GROUPS`), GPA scale normalization (`gpa_scales.json`), weighted scoring (`weights.json`), grounded analysis findings + optional explanation phrasing | `modules/matching/{router,schemas,service,analysis,gpa,nationalities}.py` |
| **Scoped Advisor Chat (D8)** | Bounded single-assistant tool loop (`assistant@1.0`, max 5 steps, `tool_choice="required"` step 0), read-only profile/grant/match/plan/notifications tools, write proposals requiring student confirmation, fixed Arabic scope refusal, PII scrubbing | `modules/assistant/{router,schemas,service,tools,repository}.py` |
| **Documents & Strengthening (D9)** | Deterministic gap prioritization + labeled prep assumptions (`DOCUMENTS_ASSUMED_LANGUAGE_TEST_WEEKS`), Facts Ledger grounding checking every number/GPA/date/email/URL/entity in pasted text & generated drafts, CV / Motivation / Recommendation brief (`recommendation_support` only) | `modules/documents/{router,schemas,service,ledger,repository}.py` |
| **Personalized Plan (D6, D11)** | Priority-ranked application plan (`eligible` first by match then deadline), checklist & milestone generation, overlapping-deadline conflict alerts, RFC-5545 `.ics` calendar export, optional LLM weekly summary | `modules/plans/{router,schemas,service,generator,ics,repository}.py` |
| **Profile External Search (D10)** | Bounded query planner + official-domain check (`is_trusted_domain`) + SSRF-guarded fetch + verbatim `verify_evidence` + Phase 3 scoring + 24h `external_search_cache` + Admin-only `DRAFT` promotion | `modules/search/{router,schemas,service,repository}.py` |
| **Monitoring & Notifications (D11)** | Page-hash & deadline change detection staged in `grant_change_reviews` for admin approval (never auto-editing published grants), deduplicated in-app notifications (`14/7/3/1d` deadlines, unavailable plan grants, missing criteria, opt-in high match), OS file-lock leader scheduler | `modules/notifications/{router,schemas,service,repository}.py`, `monitor_service.py` |
| **Core, Migrations & Guards** | SQLite WAL / PostgreSQL DB connection, versioned ordered migrations (`001`–`007`), shared DNS-pinned + redirect-revalidating SSRF guard (`safe_request`), sliding-window rate limiter, log secret redaction | `core/{config,db,models,repository}.py`, `migrations/{runner,v001..v007}.py`, `utils/{url_guard,url_validator,evidence_check,rate_limit,logging_redaction}.py` |

---

## 2. Trust Boundaries

1. **Browser <-> FastAPI Edge (`api/main.py`)**:
   - Student identity comes strictly from the signed/hashed `HttpOnly` cookie resolved via `require_student` (never client-supplied `session_id` query/body fields).
   - Admin routes enforce `require_admin` (`ADMIN_API_KEY` via `X-Admin-Key` header or signed `HttpOnly` admin cookie). When unset outside explicit `ALLOW_INSECURE_LOCAL_ADMIN`, admin access fails closed.
   - `SecurityHeadersMiddleware` sets CSP (`script-src 'self'; object-src 'none'; frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and `Cache-Control: no-store` on all student/admin API responses.
2. **Backend <-> External Web / Telegram / Webhook (`utils/url_guard.py`)**:
   - Every non-hardcoded HTTP request (ingestion, sublink crawl, search fetch, monitor check, webhook) passes through `safe_request()`: HTTP/HTTPS only, port `80`/`443`, rejects loopback/private/link-local/cloud-metadata IPv4/IPv6 ranges, pins TCP connection to resolved IP to prevent DNS rebinding, manually validates each redirect hop (`max_redirects=3`), and caps bytes (`MAX_FETCH_BYTES=2MB`).
   - All fetched HTML/text and Telegram post bodies are untrusted data; quotes must appear verbatim in `page_text` (`verify_evidence`) before storage or display.
3. **Backend <-> AI Model Provider (`modules/llm/client.py`)**:
   - Only anonymized academic attributes and PII-scrubbed text are serialized into messages; `session_id`, cookies, emails, phones, and national IDs are never included.
   - Model outputs are parsed into strict Pydantic schemas and treated as untrusted text (React auto-escaping on frontend, `safeHref` on links, code-computed scores/gates).

---

## 3. Where the Model Is and Is NOT Used

| Used (Validated JSON / Text Drafts / Explanations) | Strictly Code-Only (Never Model-Decided) |
|---|---|
| `extraction@2.0`: extract structured fields + verbatim quotes from official HTML text | URL trust / SSRF guard, verbatim quote check (`verify_evidence`), `DRAFT -> PUBLISHED` status |
| `profile_analysis@1.0`: phrase Arabic strengths/weaknesses grounded strictly in finding IDs | Hard eligibility gates, nationality evaluation, GPA normalization, match & coverage percentages |
| `assistant@1.0`: tool-calling conversation & phrasing tool outputs | Tool authorization, proposal persistence confirmation, rate limits, fixed out-of-scope refusal |
| `strengthening@1.0` & `documents@1.0`: actionable tips & tailored CV/SOP/recommendation brief | Deterministic gap list, `FactsLedger` hallucination flagging, conflict checks |
| `plan_summary@1.0` & `search_planner@1.0`: short weekly plan summary & up to 3 search queries | Plan priority ranking, `.ics` generation, search budget stops, deduplicated notification rules |
