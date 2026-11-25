# Admin Runbook: Adding & Curating Scholarships (`docs/add-a-grant.md`)

Nothing from automated ingestion, Telegram posts, external search, or portal monitoring ever becomes visible to students without explicit administrator approval.

---

## 1. Adding a Scholarship from an Official URL

1. Open `/login` and sign in using the server `ADMIN_API_KEY` (stored as an `HttpOnly` cookie).
2. Navigate to `/admin` -> **Agentic URL Scraper** (`POST /api/agents/ingest`).
3. Paste the **official provider URL** (must belong to a trusted official domain in `TRUSTED_DOMAINS` and pass SSRF/HTTP 200 checks; scholarship aggregators and social links such as `t.me` are blocked automatically).
4. Click **Ingest as Draft**:
   - The server fetches the page + up to 1 same-host detail link via `utils/url_guard.py`.
   - `extraction@2.0` extracts structured eligibility conditions (`allowed_degrees`, `min_gpa_value`, `min_gpa_scale`, `language_requirements`, `nationality_rule`, `min_work_years`, `max_age`, `funding_type`) alongside verbatim quotes.
   - `verify_evidence()` strips any field whose verbatim quote cannot be confirmed in the fetched text.
   - The grant is stored strictly with `status = "draft"`.

## 2. Reviewing Quotes & Promoting External / Telegram Candidates

- **Telegram Watcher**: In `/admin`, paste approved channel posts into **Telegram Channel Watcher** (`POST /api/agents/telegram/process`). Only official domains are extracted and passed to `ingest()`; post text is never used as grant facts.
- **External Search Promotion**: Admins reviewing verified results on `/search` can click **Promote to Draft** (`POST /api/search/promote`), which saves a `DRAFT` record for review (never auto-published).
- Open **Details & Evidence** on each draft in the **Review & Publish Queue** to confirm:
  - Official URL opens the real provider portal.
  - Verbatim quotes support the stated deadline, nationality rule, funding, and GPA/language conditions.

## 3. Setting Curated Top-10 Priority & Publishing

1. On `/admin`, choose a **Featured Rank (`#1`–`#10`)** (`PATCH /api/grants/{grant_id}/featured`) if the grant belongs in ASAAS's curated Top 10 picks, or leave **Auto** to sort after curated picks by nearest deadline.
2. Click **Approve & Publish** (`POST /api/grants/{grant_id}/publish`).
   - Immediately exposes the grant on `/` (Top 10), `/matches`, `/plan`, and `/api/grants/{id}`.
   - Automatically dispatches deduplicated in-app alerts to opted-in students (`high_match_alerts = true`) if their match meets `NOTIFICATIONS_HIGH_MATCH_THRESHOLD` (default `80.0%`).

## 4. Handling Monitor Change Reviews

- When `monitor_service.py` detects a content hash or deadline change on a published grant, it logs an `UpdateLog` row and queues a `pending` item in **Monitor Change Review Queue** (`GET /api/admin/monitor/reviews`) **without overwriting published fields**.
- Click **Approve & Notify Students** (`POST /api/admin/monitor/reviews/{id}/approve`) to send a deduplicated in-app alert to students tracking that grant in their plan, or **Reject Change** (`.../reject`) if the change was cosmetic/irrelevant.
