import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormError,
  PasswordInput,
  Segmented,
  Select,
  Skeleton,
  Swash,
  TextArea,
  TextInput,
  formatDate,
  useToast,
} from '../asaas-ui';
import { ApiKeysModal } from '../components/ApiKeysModal';
import { GrantModal } from '../components/GrantModal';
import {
  api,
  type Grant,
  type GrantCounts,
  type SystemStatus,
  type TelegramReport,
} from '../lib/api';
import { useLang } from '../lib/i18n';

type StatusTab = 'all' | 'draft' | 'published' | 'expired';

const SAMPLE_TELEGRAM_POST = `📢 عاجل للطلاب اليمنيين!
فُتح التقديم لمنحة الحكومة التركية عبر الرابط الرسمي:
https://www.turkiyeburslari.gov.tr/
ومنحة جديدة في ألمانيا: https://www.daad.de/en/study-and-research-in-germany/scholarships/phd-fellowship/
⚠️ روابط غير رسمية سيتم رفضها تلقائياً: https://scholarship-positions.com/fake-grant و https://t.me/yemen_scholarships`;

export default function AdminPage() {
  const { t } = useLang();
  const toast = useToast();

  // Grants list state
  const [tab, setTab] = useState<StatusTab>('all');
  const [grants, setGrants] = useState<Grant[]>([]);
  const [counts, setCounts] = useState<GrantCounts>({
    total: 0,
    published: 0,
    draft: 0,
    expired: 0,
    update_logs: 0,
  });
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Grant | null>(null);
  const [publishingId, setPublishingId] = useState<number | null>(null);

  // Ingestion form state (includes inline manual LLM key & model)
  const [ingestUrl, setIngestUrl] = useState('');
  const [llmKey, setLlmKey] = useState('');
  const [llmModel, setLlmModel] = useState('gemini-2.0-flash');
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<unknown>(null);

  // Telegram watcher state
  const [telegramText, setTelegramText] = useState('');
  const [scanningTg, setScanningTg] = useState(false);
  const [tgError, setTgError] = useState<unknown>(null);
  const [tgReport, setTgReport] = useState<TelegramReport | null>(null);

  // System readiness
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [showKeysModal, setShowKeysModal] = useState(false);

  const loadGrants = useCallback(async (statusFilter: StatusTab) => {
    setLoadingList(true);
    setListError(null);
    try {
      const [res, st] = await Promise.all([api.listGrants(statusFilter), api.getSystemStatus()]);
      setGrants(res.grants);
      setCounts(res.counts);
      setSysStatus(st);
    } catch (err) {
      setListError(err);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    void loadGrants(tab);
  }, [tab, loadGrants]);

  async function handleIngest(e: FormEvent) {
    e.preventDefault();
    setIngestError(null);
    setIngesting(true);
    try {
      const created = await api.ingestUrl({
        official_url: ingestUrl,
        llm_api_key: llmKey.trim() || undefined,
        llm_model: llmModel,
      });
      toast(`تم استخلاص "${created.title}" كمسودة للمراجعة`);
      setIngestUrl('');
      setLlmKey('');
      setSelected(created);
      await loadGrants(tab);
    } catch (err) {
      setIngestError(err);
    } finally {
      setIngesting(false);
    }
  }

  async function handlePublish(grantId: number) {
    setPublishingId(grantId);
    try {
      const updated = await api.publishGrant(grantId);
      toast(t('publishSuccess'));
      setSelected(updated);
      await loadGrants(tab);
    } catch (err) {
      toast(err instanceof Error ? err.message : 'تعذّر اعتماد المنحة، حاول مجدداً.', 'error');
    } finally {
      setPublishingId(null);
    }
  }

  async function handleTelegramScan(e: FormEvent) {
    e.preventDefault();
    const posts = telegramText
      .split(/\n{2,}/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (posts.length === 0) return;

    setTgError(null);
    setScanningTg(true);
    try {
      const report = await api.processTelegram(posts, !sysStatus?.llm_configured);
      setTgReport(report);
      toast(`تم فحص ${report.urls_extracted} رابطاً (${report.trusted_urls_found} رسمي)`);
      if (report.drafts_created.length > 0) {
        await loadGrants(tab);
      }
    } catch (err) {
      setTgError(err);
    } finally {
      setScanningTg(false);
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('adminTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('adminSubtitle')}
          </p>
        </div>
        <Button variant="glass" icon="vault" onClick={() => setShowKeysModal(true)}>
          {t('apiKeysBtn')}
        </Button>
      </div>

      <div className="grid grid--halves">
        {/* Agentic URL Scraper with inline manual LLM API Key entry */}
        <Card title={t('ingestCardTitle')} icon="sparkle">
          <form className="form" onSubmit={handleIngest}>
            <div className="form__row">
              <Field
                label={t('apiKeyLlm')}
                hint={
                  sysStatus?.llm_key_hint
                    ? `${t('readyYes')}: ${sysStatus.llm_key_hint}`
                    : t('apiKeyLlmHint')
                }
              >
                {(id) => (
                  <PasswordInput
                    id={id}
                    autoComplete="off"
                    placeholder={sysStatus?.llm_key_hint || 'AIzaSy... / sk-...'}
                    value={llmKey}
                    onChange={(e) => setLlmKey(e.target.value)}
                  />
                )}
              </Field>
              <Field label={t('apiKeyModel')}>
                {(id) => (
                  <Select id={id} value={llmModel} onChange={(e) => setLlmModel(e.target.value)}>
                    <option value="gemini-2.0-flash">gemini-2.0-flash</option>
                    <option value="gemini-1.5-flash">gemini-1.5-flash</option>
                    <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                    <option value="gpt-4o-mini">gpt-4o-mini</option>
                    <option value="gpt-4o">gpt-4o</option>
                    <option value="openrouter/google/gemini-2.0-flash-001">openrouter/gemini-2.0-flash</option>
                  </Select>
                )}
              </Field>
            </div>
            <Field label={t('fieldOfficialUrl')} hint={t('fieldOfficialUrlHint')}>
              {(id) => (
                <TextInput
                  id={id}
                  type="url"
                  required
                  placeholder="https://www.chevening.org/scholarships/"
                  value={ingestUrl}
                  onChange={(e) => setIngestUrl(e.target.value)}
                  dir="ltr"
                />
              )}
            </Field>
            <FormError error={ingestError} />
            <div className="cluster">
              <Button type="submit" variant="primary" icon="plus" loading={ingesting}>
                {t('btnIngest')}
              </Button>
            </div>
          </form>
        </Card>

        {/* Phase 8: Telegram Channel Watcher */}
        <Card
          title={t('telegramCardTitle')}
          icon="send"
          actions={
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setTelegramText(SAMPLE_TELEGRAM_POST)}
            >
              {t('telegramSampleBtn')}
            </Button>
          }
        >
          <form className="form" onSubmit={handleTelegramScan}>
            <Field label={t('telegramCardTitle')} hint={t('telegramHint')}>
              {(id) => (
                <TextArea
                  id={id}
                  rows={4}
                  required
                  value={telegramText}
                  onChange={(e) => setTelegramText(e.target.value)}
                  placeholder="https://..."
                />
              )}
            </Field>
            <FormError error={tgError} />
            <div className="cluster">
              <Button type="submit" variant="glass" icon="search" loading={scanningTg}>
                {t('btnTelegramScan')}
              </Button>
            </div>
          </form>

          {tgReport && (
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {tgReport.note && <div className="notice-banner">{tgReport.note}</div>}
              <div className="cluster">
                <span className="pill pill--paid">
                  رسمي: <span className="num">{tgReport.trusted_urls_found}</span>
                </span>
                <span className="pill pill--partial">
                  مسجّل مسبقاً: <span className="num">{tgReport.skipped_existing.length}</span>
                </span>
                <span className="pill pill--unpaid">
                  مرفوض غير رسمي: <span className="num">{tgReport.skipped_untrusted.length}</span>
                </span>
              </div>

              {tgReport.ready_for_ingest && tgReport.ready_for_ingest.length > 0 && (
                <div className="quote-box">
                  <strong>روابط رسمية جديدة جاهزة للاستخلاص:</strong>
                  <ul className="detail-list" style={{ marginTop: 6 }}>
                    {tgReport.ready_for_ingest.map((u) => (
                      <li key={u} dir="ltr">
                        {u}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {tgReport.skipped_untrusted.length > 0 && (
                <div className="subtle">
                  <strong>روابط مرفوضة:</strong>
                  {tgReport.skipped_untrusted.map((item, i) => (
                    <div key={i} dir="ltr">
                      ✗ {item.url} — {item.reason}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* Review & Publish Queue */}
      <Card
        title={t('reviewCardTitle')}
        icon="briefcase"
        actions={
          <Segmented
            label={t('reviewCardTitle')}
            value={tab}
            onChange={setTab}
            options={[
              { value: 'all', label: t('tabAll'), count: counts.total },
              { value: 'draft', label: t('tabDraft'), count: counts.draft },
              { value: 'published', label: t('tabPublished'), count: counts.published },
              { value: 'expired', label: t('tabExpired'), count: counts.expired },
            ]}
          />
        }
      >
        {loadingList && <Skeleton height={64} count={4} />}
        {!loadingList && listError ? (
          <ErrorState error={listError} onRetry={() => void loadGrants(tab)} />
        ) : null}

        {!loadingList && !listError && grants.length === 0 && (
          <EmptyState icon="file" title={t('noGrantsTitle')}>
            {t('noGrantsBody')}
          </EmptyState>
        )}

        {!loadingList && !listError && grants.length > 0 && (
          <div className="list">
            {grants.map((grant) => (
              <div key={grant.id} className="row row--stack">
                <div className="row__main">
                  <div className="row__title">{grant.title}</div>
                  <div className="row__meta row__meta--wrap">
                    <span
                      className={
                        grant.status === 'published'
                          ? 'pill pill--paid'
                          : grant.status === 'draft'
                            ? 'pill pill--partial'
                            : 'pill pill--unpaid'
                      }
                    >
                      {grant.status === 'published'
                        ? t('statusPublished')
                        : grant.status === 'draft'
                          ? t('statusDraft')
                          : t('statusExpired')}
                    </span>
                    <span className="subtle">
                      {t('deadlineLabel')}:{' '}
                      <span className="num">
                        {grant.deadline ? formatDate(grant.deadline) : t('rollingDeadline')}
                      </span>
                    </span>
                  </div>
                </div>
                <div className="row__actions">
                  <Button size="sm" variant="glass" onClick={() => setSelected(grant)}>
                    {t('viewDetails')}
                  </Button>
                  {grant.status === 'draft' && (
                    <Button
                      size="sm"
                      variant="primary"
                      icon="checkCircle"
                      loading={publishingId === grant.id}
                      onClick={() => void handlePublish(grant.id)}
                    >
                      {t('btnPublish')}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {selected && (
        <GrantModal
          grant={selected}
          onClose={() => setSelected(null)}
          onPublish={(id) => void handlePublish(id)}
          publishing={publishingId === selected.id}
        />
      )}

      {showKeysModal && (
        <ApiKeysModal
          status={sysStatus}
          onClose={() => setShowKeysModal(false)}
          onSaved={(updated) => setSysStatus(updated)}
        />
      )}
    </div>
  );
}
