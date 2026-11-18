/**
 * Typed API client for the Autonomous Discovery & Web Research Sub-Agent backend.
 * Reads standardized ASAAS error payloads (`{"message": "..."}`).
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

export interface SystemStatus {
  llm_configured: boolean;
  llm_model: string;
  llm_key_hint: string | null;
  search_configured: boolean;
  search_provider: string | null;
  tavily_key_hint: string | null;
  serper_key_hint: string | null;
  telegram_configured: boolean;
  telegram_channels: string;
  counts: GrantCounts;
}

export interface UpdateKeysPayload {
  llm_api_key?: string;
  llm_model?: string;
  tavily_api_key?: string;
  serper_api_key?: string;
  telegram_api_id?: string;
  telegram_api_hash?: string;
  telegram_channels?: string;
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

export interface TelegramReport {
  mode?: string;
  posts_processed: number;
  urls_extracted: number;
  trusted_urls_found: number;
  ready_for_ingest?: string[];
  drafts_created: Array<{ grant_id: number; title: string; official_url: string; status: string }>;
  skipped_existing: string[];
  skipped_untrusted: Array<{ url: string; reason: string }>;
  errors: Array<{ url: string; error: string }>;
  note?: string;
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || '';

export function safeHref(rawUrl: string | null | undefined): string {
  if (!rawUrl) return '#';
  const trimmed = rawUrl.trim();
  if (trimmed.startsWith('/')) return trimmed;
  try {
    const parsed = new URL(trimmed);
    if (['http:', 'https:', 'mailto:', 'tel:'].includes(parsed.protocol)) {
      return parsed.toString();
    }
  } catch {
    return '#';
  }
  return '#';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { message?: string; detail?: string };
      message = body.message || body.detail || message;
    } catch {
      // keep default message
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export const api = {
  getSystemStatus: () => request<SystemStatus>('/api/system/status'),
  updateKeys: (payload: UpdateKeysPayload) =>
    request<SystemStatus>('/api/system/keys', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getTop10: () => request<Grant[]>('/api/grants/top10'),
  listGrants: (status?: string) =>
    request<GrantListResponse>(status && status !== 'all' ? `/api/grants?status=${encodeURIComponent(status)}` : '/api/grants'),
  getGrant: (id: number) => request<Grant>(`/api/grants/${id}`),
  publishGrant: (id: number) => request<Grant>(`/api/grants/${id}/publish`, { method: 'POST' }),
  ingestUrl: (payload: { official_url: string; llm_api_key?: string; llm_model?: string }) =>
    request<Grant>('/api/agents/ingest', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  searchExternal: (payload: {
    major: string;
    degree_level: string;
    target_country?: string;
    max_steps?: number;
    tavily_api_key?: string;
    serper_api_key?: string;
  }) =>
    request<ExternalSearchOutput>('/api/agents/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  runMonitor: () => request<MonitorSummary>('/api/agents/monitor/run', { method: 'POST' }),
  getMonitorLogs: () => request<UpdateLogItem[]>('/api/agents/monitor/logs'),
  processTelegram: (posts: string[], dry_run = false) =>
    request<TelegramReport>('/api/agents/telegram/process', {
      method: 'POST',
      body: JSON.stringify({ posts, dry_run }),
    }),
};
