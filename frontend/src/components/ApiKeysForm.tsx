import { useState, type FormEvent } from 'react';
import {
  Button,
  Field,
  FormError,
  PasswordInput,
  Select,
  TextInput,
  useToast,
} from '../asaas-ui';
import {
  api,
  type LLMProviderLiteral,
  type SystemStatus,
  type UpdateKeysPayload,
} from '../lib/api';
import { useLang } from '../lib/i18n';

interface ApiKeysFormProps {
  status: SystemStatus | null;
  onSaved: (updated: SystemStatus) => void;
}

const PROVIDER_LABELS: Array<{ id: LLMProviderLiteral; label: string }> = [
  { id: 'gemini', label: 'Google Gemini (AIza... / AQ....)' },
  { id: 'openai', label: 'OpenAI (sk-...)' },
  { id: 'openrouter', label: 'OpenRouter (sk-or-...)' },
  { id: 'groq', label: 'Groq (gsk_...)' },
];

const PROVIDER_PRESETS: Record<LLMProviderLiteral, string[]> = {
  gemini: [
    'gemini-flash-lite-latest',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-3.1-flash-lite-preview',
    'gemini-2.0-flash',
  ],
  openai: ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1'],
  openrouter: [
    'google/gemma-4-26b-a4b-it:free',
    'google/gemini-2.0-flash-001',
    'openai/gpt-4o-mini',
    'anthropic/claude-3.5-sonnet',
  ],
  groq: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
};

function normalizeProvider(raw?: string | null): LLMProviderLiteral {
  if (raw === 'gemini' || raw === 'openai' || raw === 'openrouter' || raw === 'groq') {
    return raw;
  }
  return 'gemini';
}

function detectProviderFromKey(key: string): LLMProviderLiteral | null {
  const k = key.trim();
  if (!k) return null;
  if (k.startsWith('AIza') || k.startsWith('AQ.')) return 'gemini';
  if (k.startsWith('sk-or-')) return 'openrouter';
  if (k.startsWith('gsk_')) return 'groq';
  if (k.startsWith('sk-')) return 'openai';
  return null;
}

export function ApiKeysForm({ status, onSaved }: ApiKeysFormProps) {
  const { t } = useLang();
  const toast = useToast();

  const initialProvider = normalizeProvider(status?.llm_provider);
  const [provider, setProvider] = useState<LLMProviderLiteral>(initialProvider);
  const [llmKey, setLlmKey] = useState('');
  const [llmModel, setLlmModel] = useState(
    status?.llm_model || PROVIDER_PRESETS[initialProvider][0],
  );
  const [customModel, setCustomModel] = useState('');
  const [fetchedModels, setFetchedModels] = useState<string[] | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [modelsNote, setModelsNote] = useState<string | null>(null);

  const [tavilyKey, setTavilyKey] = useState('');
  const [serperKey, setSerperKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function handleProviderChange(nextProvider: LLMProviderLiteral) {
    setProvider(nextProvider);
    setFetchedModels(null);
    setModelsNote(null);
    const presets = PROVIDER_PRESETS[nextProvider];
    if (presets.length > 0) {
      setLlmModel(presets[0]);
    }
  }

  function handleKeyChange(nextVal: string) {
    setLlmKey(nextVal);
    const detected = detectProviderFromKey(nextVal);
    if (detected && detected !== provider) {
      handleProviderChange(detected);
    }
  }

  async function handleFetchModels() {
    setFetchingModels(true);
    setModelsNote(null);
    try {
      const res = await api.fetchProviderModels({
        llm_provider: provider,
        llm_api_key: llmKey.trim() || undefined,
      });
      if (res.models.length > 0) {
        setFetchedModels(res.models);
        if (!res.models.includes(llmModel)) {
          setLlmModel(res.models[0]);
        }
      }
      if (res.note) setModelsNote(res.note);
    } catch (err) {
      setModelsNote(err instanceof Error ? err.message : t('docsGenericError'));
    } finally {
      setFetchingModels(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const effectiveModel = customModel.trim() || llmModel;
      const payload: UpdateKeysPayload = {
        llm_provider: provider,
        llm_model: effectiveModel,
      };
      if (llmKey.trim()) payload.llm_api_key = llmKey.trim();
      if (tavilyKey.trim()) payload.tavily_api_key = tavilyKey.trim();
      if (serperKey.trim()) payload.serper_api_key = serperKey.trim();

      const updated = await api.updateKeys(payload);
      setLlmKey('');
      setTavilyKey('');
      setSerperKey('');
      setCustomModel('');
      setLlmModel(updated.llm_model);
      toast(t('keysSavedSuccess'));
      onSaved(updated);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const baseList = fetchedModels || PROVIDER_PRESETS[provider];
  const modelOptions = baseList.includes(llmModel) ? baseList : [llmModel, ...baseList];

  return (
    <form className="form" onSubmit={(e) => void handleSubmit(e)}>
      {(status?.llm_configured || status?.search_configured) && (
        <div className="quote-box" style={{ display: 'grid', gap: 6 }}>
          <strong>{t('apiKeyActiveBanner')}</strong>
          <div className="cluster">
            {status.llm_configured && (
              <span className="pill pill--paid">
                {status.llm_provider || provider} · <span dir="ltr">{status.llm_model}</span> ·{' '}
                <span dir="ltr">{status.llm_key_hint}</span>
              </span>
            )}
            {status.search_configured && (
              <span className="pill pill--paid">
                {t('navSearch')}: {status.search_provider} ·{' '}
                <span dir="ltr">{status.tavily_key_hint || status.serper_key_hint}</span>
              </span>
            )}
            {status.llm_models && status.llm_models.length > 1 && (
              <span className="subtle num" dir="ltr">
                (Fallback: {status.llm_models.slice(1).join(', ')})
              </span>
            )}
          </div>
          <span className="subtle">{t('apiKeyKeepHint')}</span>
        </div>
      )}

      <p className="muted" style={{ margin: 0 }}>
        {t('apiKeysSubtitle')}
      </p>

      <div className="form__row">
        <Field label={t('apiKeyProviderLabel')}>
          {(id) => (
            <Select
              id={id}
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value as LLMProviderLiteral)}
            >
              {PROVIDER_LABELS.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field
          label={t('apiKeyLlm')}
          hint={
            status?.llm_key_hint
              ? `${t('readyYes')}: ${status.llm_key_hint} — ${t('apiKeyKeepHint')}`
              : t('apiKeyLlmHint')
          }
        >
          {(id) => (
            <PasswordInput
              id={id}
              autoComplete="off"
              placeholder={
                status?.llm_configured ? t('apiKeyReplacePlaceholder') : 'AIzaSy... / AQ.... / sk-... / sk-or-...'
              }
              value={llmKey}
              onChange={(e) => handleKeyChange(e.target.value)}
            />
          )}
        </Field>
      </div>

      <div className="form__row">
        <Field label={t('apiKeyModel')} hint={modelsNote || undefined}>
          {(id) => (
            <Select id={id} value={llmModel} onChange={(e) => setLlmModel(e.target.value)}>
              {modelOptions.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field label={t('apiKeyCustomModelLabel')}>
          {(id) => (
            <TextInput
              id={id}
              dir="ltr"
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder="e.g. gemini-2.5-flash"
            />
          )}
        </Field>
      </div>

      <div className="cluster">
        <Button
          type="button"
          variant="glass"
          size="sm"
          icon="sparkle"
          loading={fetchingModels}
          onClick={() => void handleFetchModels()}
        >
          {t('apiKeyFetchModelsBtn')}
        </Button>
      </div>

      <div className="notice-banner">
        <span className="subtle">{t('apiKeySearchExplain')}</span>
      </div>

      <div className="form__row">
        <Field
          label={t('apiKeyTavily')}
          hint={
            status?.tavily_key_hint
              ? `${t('readyYes')}: ${status.tavily_key_hint}`
              : t('apiKeyTavilyHint')
          }
        >
          {(id) => (
            <PasswordInput
              id={id}
              autoComplete="off"
              placeholder={status?.tavily_key_hint || 'tvly-...'}
              value={tavilyKey}
              onChange={(e) => setTavilyKey(e.target.value)}
            />
          )}
        </Field>

        <Field
          label={t('apiKeySerper')}
          hint={
            status?.serper_key_hint
              ? `${t('readyYes')}: ${status.serper_key_hint}`
              : t('apiKeySerperHint')
          }
        >
          {(id) => (
            <PasswordInput
              id={id}
              autoComplete="off"
              placeholder={status?.serper_key_hint || 'Serper API Key'}
              value={serperKey}
              onChange={(e) => setSerperKey(e.target.value)}
            />
          )}
        </Field>
      </div>

      <FormError error={error} />

      <div className="cluster">
        <Button type="submit" variant="primary" icon="checkCircle" loading={saving}>
          {t('btnSaveKeys')}
        </Button>
      </div>
    </form>
  );
}
