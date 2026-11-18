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
import { api, type SystemStatus, type UpdateKeysPayload } from '../lib/api';
import { useLang } from '../lib/i18n';

interface ApiKeysFormProps {
  status: SystemStatus | null;
  onSaved: (updated: SystemStatus) => void;
}

const MODEL_PRESETS = [
  'gemini-2.0-flash',
  'gemini-1.5-flash',
  'gemini-1.5-pro',
  'gpt-4o-mini',
  'gpt-4o',
  'openrouter/google/gemini-2.0-flash-001',
];

export function ApiKeysForm({ status, onSaved }: ApiKeysFormProps) {
  const { t } = useLang();
  const toast = useToast();

  const [llmKey, setLlmKey] = useState('');
  const [llmModel, setLlmModel] = useState(status?.llm_model || 'gemini-2.0-flash');
  const [tavilyKey, setTavilyKey] = useState('');
  const [serperKey, setSerperKey] = useState('');
  const [tgId, setTgId] = useState('');
  const [tgHash, setTgHash] = useState('');
  const [tgChannels, setTgChannels] = useState(status?.telegram_channels || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const payload: UpdateKeysPayload = {
        llm_model: llmModel,
        telegram_channels: tgChannels,
      };
      if (llmKey.trim()) payload.llm_api_key = llmKey.trim();
      if (tavilyKey.trim()) payload.tavily_api_key = tavilyKey.trim();
      if (serperKey.trim()) payload.serper_api_key = serperKey.trim();
      if (tgId.trim()) payload.telegram_api_id = tgId.trim();
      if (tgHash.trim()) payload.telegram_api_hash = tgHash.trim();

      const updated = await api.updateKeys(payload);
      setLlmKey('');
      setTavilyKey('');
      setSerperKey('');
      setTgId('');
      setTgHash('');
      toast(t('keysSavedSuccess'));
      onSaved(updated);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const modelOptions = MODEL_PRESETS.includes(llmModel)
    ? MODEL_PRESETS
    : [llmModel, ...MODEL_PRESETS];

  return (
    <form className="form" onSubmit={handleSubmit}>
      <p className="muted" style={{ margin: 0 }}>
        {t('apiKeysSubtitle')}
      </p>

      <div className="form__row">
        <Field
          label={t('apiKeyLlm')}
          hint={
            status?.llm_key_hint
              ? `${t('readyYes')}: ${status.llm_key_hint} — ${t('apiKeyLlmHint')}`
              : t('apiKeyLlmHint')
          }
        >
          {(id) => (
            <PasswordInput
              id={id}
              autoComplete="off"
              placeholder={status?.llm_key_hint || 'AIzaSy... / sk-...'}
              value={llmKey}
              onChange={(e) => setLlmKey(e.target.value)}
            />
          )}
        </Field>

        <Field label={t('apiKeyModel')}>
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

      <div className="form__row">
        <Field label={t('apiKeyTgId')}>
          {(id) => (
            <TextInput
              id={id}
              dir="ltr"
              autoComplete="off"
              placeholder="12345678"
              value={tgId}
              onChange={(e) => setTgId(e.target.value)}
            />
          )}
        </Field>

        <Field label={t('apiKeyTgHash')}>
          {(id) => (
            <PasswordInput
              id={id}
              autoComplete="off"
              placeholder="Telegram API Hash"
              value={tgHash}
              onChange={(e) => setTgHash(e.target.value)}
            />
          )}
        </Field>
      </div>

      <Field label={t('apiKeyTgChannels')} hint={t('apiKeyTgChannelsHint')}>
        {(id) => (
          <TextInput
            id={id}
            dir="ltr"
            placeholder="@grants_ye, @yemen_scholarships"
            value={tgChannels}
            onChange={(e) => setTgChannels(e.target.value)}
          />
        )}
      </Field>

      <FormError error={error} />

      <div className="cluster">
        <Button type="submit" variant="primary" icon="checkCircle" loading={saving}>
          {t('btnSaveKeys')}
        </Button>
      </div>
    </form>
  );
}
