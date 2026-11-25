/**
 * Typed API client for the ASAAS Scholarship Advisor & Discovery backend.
 * Reads standardized ASAAS error payloads (`{"message": "...", "code": "..."}`).
 * Handles 401 responses in one place and always sends credentials (`include`).
 */

export interface Grant {
  id: number;
  title: string;
  official_url: string;
  description: string | null;
  eligibility: string[] | null;
  criteria: string[] | null;
  fields_of_study: string[] | null;
  funding: string | null;
  required_documents: string[] | null;
  deadline: string | null;
  how_to_apply: string | null;
  accepts_yemeni: 'yes' | 'no' | 'unclear';
  featured_rank?: number | null;
  is_featured?: boolean;
  provider_name?: string | null;
  host_country?: string | null;
  allowed_degrees?: string[] | null;
  min_gpa_value?: number | null;
  min_gpa_scale?: string | null;
  min_gpa_normalized_4?: number | null;
  language_requirements?: Array<{
    language: string;
    test?: string | null;
    min_score?: number | null;
    cefr?: string | null;
  }> | null;
  nationality_rule?: {
    mode: 'all' | 'include' | 'exclude' | 'group' | 'unclear';
    countries: string[];
    groups: string[];
    evidence?: string | null;
  } | null;
  min_work_years?: number | null;
  max_age?: number | null;
  funding_type?: string | null;
  evidence: Record<string, string>;
  field_verification: Record<string, string>;
  status: 'draft' | 'published' | 'expired';
  content_hash: string | null;
  last_checked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface GrantCounts {
  total: number;
  published: number;
  draft: number;
  expired: number;
  update_logs: number;
}

export interface GrantListResponse {
  grants: Grant[];
  counts: GrantCounts;
}

export type LLMProviderLiteral = 'gemini' | 'openai' | 'openrouter' | 'groq';

export interface SystemStatus {
  llm_configured: boolean;
  llm_provider?: string;
  llm_model: string;
  llm_models?: string[];
  llm_key_hint: string | null;
  search_configured: boolean;
  search_provider: string | null;
  tavily_key_hint: string | null;
  serper_key_hint: string | null;
  dev_keys_enabled: boolean;
  counts: GrantCounts;
}

export interface UpdateKeysPayload {
  llm_provider?: LLMProviderLiteral;
  llm_api_key?: string;
  llm_model?: string;
  tavily_api_key?: string;
  serper_api_key?: string;
}

export interface FetchModelsResponse {
  provider: string;
  models: string[];
  source: 'live' | 'presets';
  note?: string | null;
}

export interface KeyTestResponse {
  llm_ok: boolean;
  llm_provider: string;
  llm_model: string;
  llm_key_hint?: string | null;
  llm_message: string;
  search_configured: boolean;
  search_provider?: string | null;
  search_message: string;
}

export interface ManualGrantCreatePayload {
  title: string;
  official_url: string;
  description?: string | null;
  provider_name?: string | null;
  host_country?: string | null;
  deadline?: string | null;
  funding?: string | null;
  funding_type?: string | null;
  accepts_yemeni: 'yes' | 'no' | 'unclear';
  allowed_degrees?: string[] | null;
  fields_of_study?: string[] | null;
  eligibility?: string[] | null;
  criteria?: string[] | null;
  required_documents?: string[] | null;
  how_to_apply?: string | null;
  min_gpa_value?: number | null;
  min_gpa_scale?: '4.0' | '5.0' | '100' | 'label' | null;
  min_work_years?: number | null;
  max_age?: number | null;
  featured_rank?: number | null;
  evidence?: Record<string, string> | null;
  publish_immediately?: boolean;
}

export interface ManualGrantUpdatePayload extends Partial<Omit<ManualGrantCreatePayload, 'publish_immediately'>> {
  status?: 'draft' | 'published' | 'expired';
}

export interface GrantIngestPreviewResponse {
  title: string;
  official_url: string;
  description?: string | null;
  provider_name?: string | null;
  host_country?: string | null;
  deadline?: string | null;
  funding?: string | null;
  funding_type?: string | null;
  accepts_yemeni: 'yes' | 'no' | 'unclear';
  allowed_degrees?: string[] | null;
  fields_of_study?: string[] | null;
  eligibility?: string[] | null;
  criteria?: string[] | null;
  required_documents?: string[] | null;
  how_to_apply?: string | null;
  min_gpa_value?: number | null;
  min_gpa_scale?: string | null;
  min_gpa_normalized_4?: number | null;
  evidence: Record<string, string>;
  field_verification: Record<string, string>;
  already_exists_id?: number | null;
  already_exists_status?: 'draft' | 'published' | 'expired' | null;
}

export interface ReActStep {
  step_number: number;
  thought: string;
  action: string;
  action_input: Record<string, unknown>;
  observation: string;
}

export interface VerifiedScholarshipResult {
  title: string;
  official_url: string;
  match_reason: string;
  evidence_quote: string;
  accepts_yemeni: 'yes' | 'no' | 'unclear';
  yemen_evidence: string | null;
}

export interface ExternalSearchOutput {
  student_profile: {
    major: string;
    degree_level: string;
    target_country: string | null;
  };
  results: VerifiedScholarshipResult[];
  reason: string;
  steps_taken: number;
  trace: ReActStep[];
}

export interface UpdateLogItem {
  id: number;
  grant_id: number;
  grant_title: string | null;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  detected_at: string | null;
  notified: boolean;
}

export interface MonitorSummary {
  cycle_time: string;
  total_published_checked: number;
  content_modifications_found: number;
  deadline_alerts_issued: number;
  details: {
    modifications: Array<{ grant_id: number; title: string; changes: string[] }>;
    alerts: Array<{ alert_type: string; title: string; details: string }>;
  };
}

export interface AdminSessionStatus {
  authenticated: boolean;
}

export interface StudentSessionStatus {
  authenticated: boolean;
  has_consent: boolean;
  consent_version: string | null;
  profile_exists: boolean;
}

export interface StudentLanguageItem {
  language: string;
  test_name?: string | null;
  score?: number | null;
  self_assessed_cefr?: 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2' | null;
  is_self_assessed?: boolean;
}

export interface StudentProfile {
  nationality: string;
  country_of_residence?: string | null;
  current_degree?: 'high_school' | 'bachelor' | 'master' | 'phd' | null;
  expected_graduation_year?: number | null;
  target_degree: 'high_school' | 'bachelor' | 'master' | 'phd';
  major?: string | null;
  gpa_raw?: string | null;
  gpa_scale?: '4.0' | '5.0' | '100' | 'label' | null;
  gpa_normalized_4?: number | null;
  gpa_label_assumed?: boolean;
  languages: StudentLanguageItem[];
  target_countries: string[];
  target_fields: string[];
  funding_need?: 'full' | 'partial' | 'any' | null;
  work_experience_years?: number | null;
  experience_notes: string[];
  age_years?: number | null;
  publications_count: number;
  has_consent?: boolean;
  consent_version?: string | null;
  updated_at?: string | null;
}

export interface StudentProfileUpsertPayload extends Omit<
  StudentProfile,
  'gpa_normalized_4' | 'gpa_label_assumed' | 'has_consent' | 'updated_at'
> {
  consent_accepted?: boolean;
}

export interface CriterionBreakdown {
  key: string;
  status: 'met' | 'not_met' | 'unknown' | 'not_applicable';
  weight: number;
  grant_value?: string | null;
  student_value?: string | null;
  evidence_quote?: string | null;
  reason_ar: string;
  reason_en: string;
}

export interface DisqualifierItem {
  gate: string;
  reason_ar: string;
  reason_en: string;
  evidence_quote?: string | null;
}

export interface GrantMatchResult {
  grant_id: number;
  title: string;
  official_url: string;
  deadline?: string | null;
  host_country?: string | null;
  funding_type?: string | null;
  featured_rank?: number | null;
  accepts_yemeni: 'yes' | 'no' | 'unclear';
  eligible: boolean;
  status: 'eligible' | 'ineligible';
  disqualifiers: DisqualifierItem[];
  match_percentage: number;
  coverage_percentage: number;
  weights_version: string;
  criteria: CriterionBreakdown[];
  missing_info_hints: string[];
}

export interface MatchesListResponse {
  eligible_grants: GrantMatchResult[];
  ineligible_grants: GrantMatchResult[];
  total_evaluated: number;
  weights_version: string;
  gpa_scales_version: string;
  disclaimer_ar: string;
  disclaimer_en: string;
}

export interface DeterministicFinding {
  id: string;
  kind: 'strength' | 'weakness' | 'gap' | 'documents';
  summary_ar: string;
  summary_en: string;
  count: number;
  related_grants: string[];
}

export interface AnalysisStatement {
  text_ar: string;
  finding_ids: string[];
}

export interface ProfileAnalysisResponse {
  analysis_mode: 'llm_grounded' | 'deterministic_fallback';
  prompt_version?: string | null;
  retryable: boolean;
  fallback_notice_ar?: string | null;
  fallback_notice_en?: string | null;
  findings: DeterministicFinding[];
  summary_ar: string;
  strengths: AnalysisStatement[];
  weaknesses: AnalysisStatement[];
  improvement_areas: AnalysisStatement[];
  dropped_ungrounded_count: number;
}

export interface AssistantStatusResponse {
  enabled: boolean;
  configured: boolean;
  student_authenticated: boolean;
  has_consent: boolean;
  has_profile: boolean;
}

export interface AssistantProposalAttachment {
  type: 'proposal';
  tool: string;
  updates: Record<string, unknown>;
  summary_ar?: string;
  summary_en?: string;
}

export interface AssistantChatResponse {
  reply: string;
  attachments?: unknown[];
}

export type DocTypeLiteral = 'cv' | 'motivation_letter' | 'recommendation_support' | 'certificates';
export type DocLangLiteral = 'ar' | 'en';
export type ClaimStatusLiteral = 'needs_confirmation' | 'accepted' | 'removed';

export interface StrengtheningGap {
  gap_id: string;
  gap_type: 'language' | 'gpa' | 'documents' | 'deadline_proximity' | 'experience' | 'other';
  severity: 'high' | 'medium' | 'low';
  title_ar: string;
  title_en: string;
  evidence_ar: string;
  evidence_en: string;
  related_grants: string[];
  is_assumption: boolean;
  assumption_note_ar?: string | null;
  assumption_note_en?: string | null;
}

export interface StrengtheningActionItem {
  gap_id: string;
  what_ar: string;
  why_ar: string;
  next_step_ar: string;
  is_assumption: boolean;
}

export interface StrengtheningDocumentInput {
  doc_type: DocTypeLiteral;
  filename?: string | null;
  content: string;
}

export interface DocumentExtractFileResponse {
  doc_type: DocTypeLiteral;
  filename: string;
  extracted_text: string;
  char_count: number;
  truncated: boolean;
}

export interface StrengtheningResponse {
  gaps: StrengtheningGap[];
  summary_ar: string;
  actions: StrengtheningActionItem[];
  prompt_version?: string | null;
  used_fallback: boolean;
  disclaimer_ar: string;
  disclaimer_en: string;
}

export interface LedgerEntry {
  id: string;
  source: 'profile' | 'pasted_text' | 'grant';
  category: string;
  value: string;
  normalized_tokens?: string[];
}

export interface FlaggedClaim {
  id: string;
  claim_text: string;
  category: string;
  reason_ar: string;
  reason_en: string;
  status: ClaimStatusLiteral;
}

export interface DocumentGenerateResponse {
  grant_id?: number | null;
  grant_title?: string | null;
  doc_type: DocTypeLiteral;
  language: DocLangLiteral;
  draft_text: string;
  sections: Array<{ title: string; content: string }>;
  facts_ledger: LedgerEntry[];
  claims: Array<{ text: string; category: string; ledger_id?: string | null }>;
  flagged_claims: FlaggedClaim[];
  conflicts: FlaggedClaim[];
  missing_info_requests: string[];
  prompt_version: string;
  responsibility_note_ar: string;
  responsibility_note_en: string;
}

export interface SavedDocumentDraft {
  id: number;
  grant_id?: number | null;
  grant_title?: string | null;
  doc_type: DocTypeLiteral;
  language: DocLangLiteral;
  draft_text: string;
  facts_ledger: LedgerEntry[];
  flagged_claims: FlaggedClaim[];
  prompt_version?: string | null;
  created_at: string;
  updated_at: string;
}

export type ChecklistStatusLiteral = 'todo' | 'in_progress' | 'done';
export type PlanItemStatusLiteral = 'planned' | 'in_progress' | 'submitted' | 'archived';
export type UrgencyStatusLiteral = 'overdue' | 'due_today' | 'due_soon' | 'upcoming' | 'no_deadline';

export interface PlanChecklistItem {
  id: string;
  category: 'document' | 'application_step' | 'gap' | 'missing_official';
  label_ar: string;
  label_en: string;
  detail_ar?: string | null;
  detail_en?: string | null;
  evidence_quote?: string | null;
  official_url?: string | null;
  is_not_stated_officially: boolean;
  is_assumption: boolean;
  status: ChecklistStatusLiteral;
}

export interface PlanMilestone {
  offset_days: number;
  due_date: string;
  days_from_today: number;
  status: 'overdue' | 'due_today' | 'due_soon' | 'upcoming';
  label_ar: string;
  label_en: string;
  pacing_note_ar: string;
  pacing_note_en: string;
}

export interface DeadlineConflict {
  conflict_id: string;
  start_date: string;
  end_date: string;
  span_days: number;
  grant_ids: number[];
  grant_titles: string[];
  message_ar: string;
  message_en: string;
}

export interface PlanGrantItem {
  id: number;
  grant_id: number;
  title: string;
  official_url: string;
  host_country?: string | null;
  funding_type?: string | null;
  priority_rank: number;
  status: PlanItemStatusLiteral;
  eligible: boolean;
  ineligible_warning_ar?: string | null;
  ineligible_warning_en?: string | null;
  match_percentage: number;
  coverage_percentage: number;
  deadline?: string | null;
  days_remaining?: number | null;
  urgency: UrgencyStatusLiteral;
  progress_percentage: number;
  how_to_apply_text?: string | null;
  how_to_apply_evidence?: string | null;
  checklist: PlanChecklistItem[];
  milestones: PlanMilestone[];
  notes?: string | null;
}

export interface PlanSummaryResponse {
  summary_ar?: string | null;
  referenced_item_ids: number[];
  prompt_version?: string | null;
  available: boolean;
}

export interface PlanOverviewResponse {
  plan_id?: number | null;
  timezone: string;
  as_of_date: string;
  total_grants: number;
  overall_progress_percentage: number;
  conflicts: DeadlineConflict[];
  items: PlanGrantItem[];
  ai_summary?: PlanSummaryResponse | null;
}

export interface ExternalSearchStepLog {
  step_number: number;
  kind: string;
  target?: string | null;
  verdict: 'ok' | 'rejected' | 'skipped' | 'stopped';
  message_ar: string;
  message_en: string;
}

export interface ExternalSearchCandidateResult {
  title: string;
  official_url: string;
  content_hash: string;
  description?: string | null;
  eligibility: string[];
  criteria: string[];
  fields_of_study: string[];
  funding?: string | null;
  funding_type: string;
  required_documents: string[];
  deadline?: string | null;
  how_to_apply?: string | null;
  provider_name?: string | null;
  host_country?: string | null;
  allowed_degrees: string[];
  nationality_rule: Record<string, unknown>;
  eligibility_verdict: 'yes' | 'no' | 'unclear';
  nationality_evidence?: string | null;
  evidence: Record<string, string>;
  field_verification: Record<string, string>;
  match_result: GrantMatchResult;
  outside_platform_label_ar: string;
  outside_platform_label_en: string;
}

export interface ExternalSearchRunResponse {
  run_id: string;
  status: 'complete' | 'partial' | 'failed';
  stop_reason_ar: string;
  stop_reason_en: string;
  cached: boolean;
  queries_executed: number;
  pages_checked: number;
  steps_taken: number;
  tokens_used: number;
  elapsed_ms: number;
  excluded_platform_count?: number;
  step_log: ExternalSearchStepLog[];
  results: ExternalSearchCandidateResult[];
  disclaimer_ar: string;
  disclaimer_en: string;
}

export interface NotificationItem {
  id: number;
  grant_id?: number | null;
  kind: string;
  title: string;
  body: string;
  official_url?: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationsListResponse {
  unread_count: number;
  high_match_alerts_enabled: boolean;
  notifications: NotificationItem[];
}

export interface GrantChangeReviewItem {
  id: number;
  grant_id: number;
  grant_title?: string | null;
  update_log_id?: number | null;
  field_name: string;
  old_value?: string | null;
  new_value?: string | null;
  summary_ar: string;
  status: 'pending' | 'approved' | 'rejected';
  reviewed_at?: string | null;
  created_at: string;
}

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || '';

let unauthorizedHandler: (() => void) | null = null;

export function registerUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function hasUnsafeUrlChars(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code === 92 || code <= 31) return true;
  }
  return false;
}

export function safeHref(rawUrl: string | null | undefined): string {
  if (!rawUrl) return '#';
  const trimmed = rawUrl.trim();
  if (!trimmed || hasUnsafeUrlChars(trimmed)) return '#';
  try {
    const parsed = new URL(trimmed, window.location.origin);
    if (parsed.protocol === 'mailto:' || parsed.protocol === 'tel:') {
      return trimmed;
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return '#';
    }
    if (parsed.origin === window.location.origin) {
      return parsed.pathname + parsed.search + parsed.hash;
    }
    return trimmed.startsWith('/') ? '#' : parsed.href;
  } catch {
    return '#';
  }
}

export function safeSameOriginNext(rawNext: string | null | undefined): string {
  if (!rawNext) return '/admin';
  const trimmed = rawNext.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || hasUnsafeUrlChars(trimmed)) {
    return '/admin';
  }
  return trimmed;
}

async function request<T>(
  path: string,
  init?: RequestInit & { skipUnauthorizedRedirect?: boolean },
): Promise<T> {
  const { skipUnauthorizedRedirect, ...fetchInit } = init || {};
  const headers = new Headers(fetchInit.headers);
  headers.set('X-Lang', document.documentElement.lang === 'en' ? 'en' : 'ar');
  if (fetchInit.body && !(fetchInit.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...fetchInit,
    headers,
    credentials: 'include',
  });

  const body =
    res.status === 204
      ? null
      : ((await res.json().catch(() => null)) as {
          message?: string;
          detail?: string;
          code?: string;
        } | null);

  if (res.status === 401 && !skipUnauthorizedRedirect && unauthorizedHandler) {
    unauthorizedHandler();
  }

  if (!res.ok) {
    const message = body?.message || body?.detail || `تعذّر تنفيذ الطلب (رمز ${res.status}).`;
    throw new ApiError(message, res.status, body?.code);
  }
  return body as T;
}

export const api = {
  getAdminSession: () =>
    request<AdminSessionStatus>('/api/admin/session', { skipUnauthorizedRedirect: true }),
  adminLogin: (secret: string) =>
    request<AdminSessionStatus>('/api/admin/login', {
      method: 'POST',
      body: JSON.stringify({ secret }),
      skipUnauthorizedRedirect: true,
    }),
  adminLogout: () =>
    request<AdminSessionStatus>('/api/admin/logout', {
      method: 'POST',
      skipUnauthorizedRedirect: true,
    }),
  getSystemStatus: () => request<SystemStatus>('/api/system/status'),
  updateKeys: (payload: UpdateKeysPayload) =>
    request<SystemStatus>('/api/system/keys', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  fetchProviderModels: (payload: { llm_provider: LLMProviderLiteral; llm_api_key?: string }) =>
    request<FetchModelsResponse>('/api/system/models', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  testActiveKeys: () =>
    request<KeyTestResponse>('/api/system/test-keys', { method: 'POST' }),
  getTop10: () => request<Grant[]>('/api/grants/top10'),
  listGrants: (status?: string) =>
    request<GrantListResponse>(
      status && status !== 'all' ? `/api/grants?status=${encodeURIComponent(status)}` : '/api/grants',
    ),
  getGrant: (id: number) => request<Grant>(`/api/grants/${id}`),
  createManualGrant: (payload: ManualGrantCreatePayload) =>
    request<Grant>('/api/grants', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateGrant: (id: number, payload: ManualGrantUpdatePayload) =>
    request<Grant>(`/api/grants/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteGrant: (id: number) =>
    request<{ deleted: boolean; id: number }>(`/api/grants/${id}`, { method: 'DELETE' }),
  publishGrant: (id: number) => request<Grant>(`/api/grants/${id}/publish`, { method: 'POST' }),
  setFeaturedRank: (id: number, featured_rank: number | null) =>
    request<Grant>(`/api/grants/${id}/featured`, {
      method: 'PATCH',
      body: JSON.stringify({ featured_rank }),
    }),
  previewIngestUrl: (payload: { official_url: string }) =>
    request<GrantIngestPreviewResponse>('/api/agents/ingest/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  ingestUrl: (payload: { official_url: string }) =>
    request<Grant>('/api/agents/ingest', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  searchExternal: (payload: {
    major: string;
    degree_level: string;
    target_country?: string;
    max_steps?: number;
  }) =>
    request<ExternalSearchOutput>('/api/agents/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  runMonitor: () => request<MonitorSummary>('/api/agents/monitor/run', { method: 'POST' }),
  getMonitorLogs: () => request<UpdateLogItem[]>('/api/agents/monitor/logs'),
  getStudentStatus: () =>
    request<StudentSessionStatus>('/api/students/me', { skipUnauthorizedRedirect: true }),
  startStudentSession: (payload?: { consent_accepted?: boolean }) =>
    request<StudentSessionStatus>('/api/students/session', {
      method: 'POST',
      body: JSON.stringify(payload || {}),
      skipUnauthorizedRedirect: true,
    }),
  acceptStudentConsent: () =>
    request<StudentSessionStatus>('/api/students/consent', {
      method: 'POST',
      body: JSON.stringify({ accepted: true, consent_version: 'privacy-v1' }),
      skipUnauthorizedRedirect: true,
    }),
  getStudentProfile: () =>
    request<StudentProfile>('/api/students/profile', { skipUnauthorizedRedirect: true }),
  saveStudentProfile: (payload: StudentProfileUpsertPayload) =>
    request<StudentProfile>('/api/students/profile', {
      method: 'PUT',
      body: JSON.stringify(payload),
      skipUnauthorizedRedirect: true,
    }),
  exportStudentData: () =>
    request<Record<string, unknown>>('/api/students/export', { skipUnauthorizedRedirect: true }),
  deleteStudentData: () =>
    request<{ deleted: boolean; removed_counts: Record<string, number> }>('/api/students/data', {
      method: 'DELETE',
      skipUnauthorizedRedirect: true,
    }),
  getMatches: () =>
    request<MatchesListResponse>('/api/matches', { skipUnauthorizedRedirect: true }),
  runMatchesExternalSearch: (
    payload?: { limit?: 3 | 5; run_id?: string; use_cache?: boolean },
    signal?: AbortSignal,
  ) =>
    request<ExternalSearchRunResponse>('/api/matches/external', {
      method: 'POST',
      body: JSON.stringify(payload || { limit: 5 }),
      signal,
      skipUnauthorizedRedirect: true,
    }),
  runProfileAnalysis: () =>
    request<ProfileAnalysisResponse>('/api/profile/analysis', {
      method: 'POST',
      skipUnauthorizedRedirect: true,
    }),
  getAssistantStatus: () =>
    request<AssistantStatusResponse>('/api/assistant/status', {
      skipUnauthorizedRedirect: true,
    }),
  askAssistant: (messages: Array<{ role: 'user' | 'assistant'; content: string }>) =>
    request<AssistantChatResponse>('/api/assistant', {
      method: 'POST',
      body: JSON.stringify({ messages }),
      skipUnauthorizedRedirect: true,
    }),
  getStrengthening: (grantIds?: number[], documents?: StrengtheningDocumentInput[]) =>
    request<StrengtheningResponse>('/api/documents/strengthening', {
      method: 'POST',
      body: JSON.stringify({
        grant_ids: grantIds && grantIds.length ? grantIds : null,
        documents: documents && documents.length ? documents : null,
      }),
      skipUnauthorizedRedirect: true,
    }),
  extractDocumentFile: (payload: {
    doc_type: DocTypeLiteral;
    filename: string;
    content_base64: string;
  }) =>
    request<DocumentExtractFileResponse>('/api/documents/extract-file', {
      method: 'POST',
      body: JSON.stringify(payload),
      skipUnauthorizedRedirect: true,
    }),
  generateDocument: (payload: {
    grant_id?: number | null;
    doc_type: DocTypeLiteral;
    language: DocLangLiteral;
    source_text: string;
    target_instructions?: string;
  }) =>
    request<DocumentGenerateResponse>('/api/documents/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
      skipUnauthorizedRedirect: true,
    }),
  listSavedDocuments: () =>
    request<{ count: number; drafts: SavedDocumentDraft[] }>('/api/documents', {
      skipUnauthorizedRedirect: true,
    }),
  saveDocument: (payload: {
    grant_id?: number | null;
    doc_type: DocTypeLiteral;
    language: DocLangLiteral;
    draft_text: string;
    facts_ledger: LedgerEntry[];
    flagged_claims: FlaggedClaim[];
    prompt_version?: string;
  }) =>
    request<SavedDocumentDraft>('/api/documents', {
      method: 'POST',
      body: JSON.stringify(payload),
      skipUnauthorizedRedirect: true,
    }),
  updateSavedDocument: (
    draftId: number,
    payload: { draft_text?: string; flagged_claims?: FlaggedClaim[] },
  ) =>
    request<SavedDocumentDraft>(`/api/documents/${draftId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
      skipUnauthorizedRedirect: true,
    }),
  deleteSavedDocument: (draftId: number) =>
    request<{ deleted: boolean; id: number }>(`/api/documents/${draftId}`, {
      method: 'DELETE',
      skipUnauthorizedRedirect: true,
    }),
  exportDocumentUrl: (draftId: number) => `${API_BASE}/api/documents/${draftId}/export`,
  getPlan: () =>
    request<PlanOverviewResponse>('/api/plan', { skipUnauthorizedRedirect: true }),
  addPlanGrant: (grantId: number, options?: { allowIneligible?: boolean; notes?: string }) =>
    request<PlanOverviewResponse>('/api/plan/items', {
      method: 'POST',
      body: JSON.stringify({
        grant_id: grantId,
        allow_ineligible: Boolean(options?.allowIneligible),
        notes: options?.notes,
      }),
      skipUnauthorizedRedirect: true,
    }),
  updatePlanItem: (
    itemId: number,
    payload: {
      status?: PlanItemStatusLiteral;
      notes?: string | null;
      checklist_updates?: Array<{ id: string; status: ChecklistStatusLiteral }>;
    },
  ) =>
    request<PlanOverviewResponse>(`/api/plan/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
      skipUnauthorizedRedirect: true,
    }),
  removePlanItem: (itemId: number) =>
    request<PlanOverviewResponse>(`/api/plan/items/${itemId}`, {
      method: 'DELETE',
      skipUnauthorizedRedirect: true,
    }),
  summarizePlan: () =>
    request<PlanSummaryResponse>('/api/plan/summary', {
      method: 'POST',
      skipUnauthorizedRedirect: true,
    }),
  downloadPlanIcsUrl: () => `${API_BASE}/api/plan/calendar.ics`,
  runProfileExternalSearch: (
    payload: {
      run_id?: string;
      nationality: string;
      target_degree: 'high_school' | 'bachelor' | 'master' | 'phd';
      major: string;
      target_countries?: string[];
      target_fields?: string[];
      gpa_raw?: string | null;
      gpa_scale?: '4.0' | '5.0' | '100' | 'label' | null;
      languages?: StudentLanguageItem[];
      use_cache?: boolean;
    },
    signal?: AbortSignal,
  ) =>
    request<ExternalSearchRunResponse>('/api/search/external', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
      skipUnauthorizedRedirect: true,
    }),
  cancelProfileExternalSearch: (runId: string) =>
    request<{ cancelled: boolean; run_id: string }>(`/api/search/external/${runId}/cancel`, {
      method: 'POST',
      skipUnauthorizedRedirect: true,
    }),
  promoteExternalResult: (result: ExternalSearchCandidateResult) =>
    request<Grant>('/api/search/promote', {
      method: 'POST',
      body: JSON.stringify({
        title: result.title,
        official_url: result.official_url,
        description: result.description,
        eligibility: result.eligibility,
        criteria: result.criteria,
        fields_of_study: result.fields_of_study,
        funding: result.funding,
        required_documents: result.required_documents,
        deadline: result.deadline,
        how_to_apply: result.how_to_apply,
        provider_name: result.provider_name,
        host_country: result.host_country,
        allowed_degrees: result.allowed_degrees,
        funding_type: result.funding_type,
        nationality_rule: result.nationality_rule,
        evidence: result.evidence,
        content_hash: result.content_hash,
      }),
    }),
  getNotifications: () =>
    request<NotificationsListResponse>('/api/notifications', { skipUnauthorizedRedirect: true }),
  getUnreadNotificationCount: () =>
    request<{ unread_count: number }>('/api/notifications/unread-count', {
      skipUnauthorizedRedirect: true,
    }),
  markNotificationRead: (notificationId: number) =>
    request<{ ok: boolean }>(`/api/notifications/${notificationId}/read`, {
      method: 'POST',
      skipUnauthorizedRedirect: true,
    }),
  markAllNotificationsRead: () =>
    request<{ ok: boolean }>('/api/notifications/read-all', {
      method: 'POST',
      skipUnauthorizedRedirect: true,
    }),
  setHighMatchPreference: (highMatchAlerts: boolean) =>
    request<{ high_match_alerts: boolean }>('/api/notifications/preferences', {
      method: 'POST',
      body: JSON.stringify({ high_match_alerts: highMatchAlerts }),
      skipUnauthorizedRedirect: true,
    }),
  listMonitorReviews: (statusFilter?: string) =>
    request<{ count: number; reviews: GrantChangeReviewItem[] }>(
      `/api/admin/monitor/reviews${statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : ''}`,
    ),
  approveMonitorReview: (reviewId: number) =>
    request<GrantChangeReviewItem>(`/api/admin/monitor/reviews/${reviewId}/approve`, {
      method: 'POST',
    }),
  rejectMonitorReview: (reviewId: number) =>
    request<GrantChangeReviewItem>(`/api/admin/monitor/reviews/${reviewId}/reject`, {
      method: 'POST',
    }),
};
