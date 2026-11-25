# Operations Manual (`docs/operations.md`)

## 1. Settings & Limits Inventory

Items marked **[Tune after 1 week of real use]** have production defaults chosen for safety and cost control and should be calibrated once real student traffic logs are observed.

| Setting / Env Var | Default | Scope / Purpose | Tune after 1 week? |
|---|---|---|---|
| `LLM_PROVIDER` | `openrouter` | Explicit OpenAI-compatible preset (`openrouter`, `gemini`, `google`, `openai`, `groq`) | No |
| `LLM_MODELS` / `LLM_MODEL` | `google/gemini-2.0-flash-001` | Primary + fallback model chain | Yes (compare evals + latency) |
| `LLM_TIMEOUT_SECONDS` | `30.0` | Upstream LLM HTTP timeout | **[Tune after 1 week of real use]** |
| `LLM_MAX_TOKENS` | `1500` | Global extraction/completion token cap | No |
| `ASSISTANT_HISTORY_LIMIT` | `8` | Max prior chat messages passed per turn | No (D8 bound) |
| `ASSISTANT_MAX_MESSAGE_CHARS` | `1500` | Max student chat input characters | No |
| `ASSISTANT_MAX_STEPS` | `5` | Max assistant tool-calling loop iterations | No |
| `ASSISTANT_MAX_TOKENS` | `700` | Output token cap per assistant step | **[Tune after 1 week of real use]** |
| `ASSISTANT_RATE_LIMIT_PER_HOUR` | `60` | Chat requests/hour per student session & IP | **[Tune after 1 week of real use]** |
| `ASSISTANT_RETENTION_DAYS` | `30` | Chat message retention TTL (D12) | No |
| `DOCUMENTS_MAX_INPUT_CHARS` | `8000` | Pasted draft input limit (no file uploads) | No |
| `DOCUMENTS_MAX_TOKENS` | `1400` | Output token cap for document drafting | **[Tune after 1 week of real use]** |
| `DOCUMENTS_RATE_LIMIT_PER_HOUR` | `30` | Strengthening & document drafts/hour per session | **[Tune after 1 week of real use]** |
| `DOCUMENTS_RETENTION_DAYS` | `90` | Saved draft & inactive session retention TTL (D12) | No |
| `DOCUMENTS_ASSUMED_LANGUAGE_TEST_WEEKS` | `6` | Labeled assumption for prep time gap check | Review w/ advisors |
| `PLANS_RATE_LIMIT_PER_HOUR` | `60` | Plan write mutations/hour per student | **[Tune after 1 week of real use]** |
| `PLANS_MAX_ITEMS` | `25` | Max tracked scholarships per student plan | No |
| `SEARCH_MAX_QUERIES` | `3` | Max external search queries per run | No |
| `SEARCH_MAX_PAGES` | `5` | Max official pages fetched per search run | **[Tune after 1 week of real use]** |
| `SEARCH_MAX_STEPS` | `5` | Max search pipeline steps per run | No |
| `SEARCH_WALL_CLOCK_SECONDS` | `30.0` | Wall-clock stop timeout for external search | **[Tune after 1 week of real use]** |
| `SEARCH_MAX_TOKENS_PER_RUN` | `3000` | Token cap per external search run | **[Tune after 1 week of real use]** |
| `SEARCH_CACHE_TTL_HOURS` | `24` | `external_search_cache` reuse TTL | **[Tune after 1 week of real use]** |
| `SEARCH_STUDENT_RATE_LIMIT_PER_HOUR` | `10` | External search runs/hour per student session & IP | **[Tune after 1 week of real use]** |
| `SEARCH_GLOBAL_RATE_LIMIT_PER_HOUR` | `60` | Global external search ceiling/hour | **[Tune after 1 week of real use]** |
| `NOTIFICATIONS_DEADLINE_OFFSETS` | `14,7,3,1` | Days before deadline to trigger plan reminders | No |
| `NOTIFICATIONS_HIGH_MATCH_THRESHOLD` | `80.0` | Minimum `%` match for opt-in new grant alerts | **[Tune after 1 week of real use]** |
| `LOGIN_RATE_LIMIT` / `WINDOW` | `5` / `60s` | Admin login throttling per IP | No |
| `INGEST_RATE_LIMIT` / `SEARCH_RATE_LIMIT` | `20` / `3600s` | Legacy admin ingest/search endpoints | No |
| `MAX_FETCH_BYTES` / `MAX_REDIRECT_HOPS` | `2MB` / `3` | Outbound SSRF fetch caps | No |

---

## 2. Scheduler & Retention Execution

- **Single-Leader Process Rule**: Run APScheduler as **one dedicated worker process** (`python -m monitor_service --schedule --interval 24`), never inside Uvicorn multi-worker lifespan.
- `acquire_scheduler_lock()` creates an exclusive OS lock (`.monitor_scheduler.lock` via `msvcrt.locking` on Windows or `fcntl.flock` on Linux), and `_MONITOR_RUN_LOCK` prevents overlapping runs within the process.
- Each `run_monitor_cycle()` executes:
  1. Official page SHA-256 hash check across published grants (`check_grant_updates` -> stages `GrantChangeReview` `pending` rows without auto-overwriting published data).
  2. Imminent deadline & expired-grant marking (`EXPIRED`).
  3. Deduplicated in-app student notifications (`NotificationsService.generate_plan_alerts`).
  4. D12 retention purge (`modules.students.retention.run_retention_cleanup`).
- Manual one-shot triggers:
  - Monitor + alerts + retention: `python -m monitor_service --now`
  - Retention purge alone: `python -m monitor_service --retention`

---

## 3. Database Backups & Deletion Policy

- **SQLite (`grants.db` in WAL mode)**: Never copy `grants.db` with `cp` while writing unless using SQLite's online backup API (`sqlite3 grants.db ".backup 'backups/grants-YYYYMMDD.db'"`). Schedule encrypted daily backups off-host and retain backups for 30 days.
- **PostgreSQL**: Use `pg_dump --format=custom` to encrypted storage on a daily schedule.
- **Student Deletion (`DELETE /api/students/data`) & Retention**: Student deletion removes active session, consent, profile, chat, drafts, plans, and notifications immediately from active database tables. Existing point-in-time encrypted backups naturally age out on the 30-day backup rotation window (never restore a stale backup over active deletion records without re-running purge).

---

## 4. Refreshing GPA Scales & Matching Weights

1. **GPA Scales (`modules/matching/gpa_scales.json`)**:
   - Contains percentage breakpoints and Yemeni academic grade labels (`ممتاز`, `جيد جداً`, `جيد`, `مقبول`, `ضعيف` — currently marked as assumptions pending ASAAS academic sign-off).
   - Update values JSON-only and increment `"version"` without code edits, then re-run `pytest tests/test_phase3_students_matching.py -q`.
2. **Matching Weights (`modules/matching/weights.json`)**:
   - Adjust weights (`nationality`, `degree_level`, `gpa`, `language`, `field_of_study`, `work_experience`, `age`) and bump `"version"`, then run matching tests and inspect sample scores.

---

## 5. Running AI Evaluations

```powershell
# Stub mode (offline CI/local check, zero API spend, never overwrites baseline.json)
python -m evals.run_eval extraction --stub
python -m evals.run_eval profile_analysis --stub
python -m evals.run_eval advisor --stub
python -m evals.run_eval documents --stub
python -m evals.run_eval external_search --stub

# Live model mode (requires LLM_API_KEY + provider preset; --save updates baseline.json)
$env:LLM_PROVIDER="gemini"
$env:LLM_MODELS="gemini-flash-lite-latest,gemini-3.1-flash-lite-preview"
$env:LLM_API_KEY="<your-key>"
python -m evals.run_eval extraction --save
```
