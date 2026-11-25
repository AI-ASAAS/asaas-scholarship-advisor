import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  Button,
  Card,
  EmptyState,
  Field,
  FormError,
  Glass,
  Icon,
  Select,
  Swash,
  TextInput,
  useToast,
} from '../asaas-ui';
import { ApiKeysModal } from '../components/ApiKeysModal';
import {
  api,
  safeHref,
  type ExternalSearchCandidateResult,
  type ExternalSearchRunResponse,
  type StudentLanguageItem,
  type SystemStatus,
} from '../lib/api';
import { useLang } from '../lib/i18n';

const TARGET_COUNTRIES = [
  { value: 'Germany', ar: 'ألمانيا', en: 'Germany' },
  { value: 'Turkey', ar: 'تركيا', en: 'Turkey' },
  { value: 'United Kingdom', ar: 'بريطانيا', en: 'United Kingdom' },
  { value: 'United States', ar: 'الولايات المتحدة', en: 'United States' },
  { value: 'Hungary', ar: 'المجر', en: 'Hungary' },
  { value: 'France', ar: 'فرنسا', en: 'France' },
  { value: 'China', ar: 'الصين', en: 'China' },
  { value: 'Japan', ar: 'اليابان', en: 'Japan' },
  { value: 'Malaysia', ar: 'ماليزيا', en: 'Malaysia' },
  { value: 'Canada', ar: 'كندا', en: 'Canada' },
  { value: 'Saudi Arabia', ar: 'السعودية', en: 'Saudi Arabia' },
  { value: 'Qatar', ar: 'قطر', en: 'Qatar' },
];

type DegreeChoice = 'high_school' | 'bachelor' | 'master' | 'phd';
type GpaScaleChoice = '4.0' | '5.0' | '100' | 'label' | '';

function makeRunId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `run-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export default function SearchPage() {
  const { lang, t } = useLang();
  const toast = useToast();

  const [nationality, setNationality] = useState('Yemen');
  const [major, setMajor] = useState('Computer Science');
  const [degreeLevel, setDegreeLevel] = useState<DegreeChoice>('master');
  const [targetCountry, setTargetCountry] = useState('');
  const [gpaRaw, setGpaRaw] = useState('');
  const [gpaScale, setGpaScale] = useState<GpaScaleChoice>('');
  const [languages, setLanguages] = useState<StudentLanguageItem[]>([]);

  const [running, setRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [error, setError] = useState<unknown>(null);
  const [output, setOutput] = useState<ExternalSearchRunResponse | null>(null);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [promotingUrl, setPromotingUrl] = useState<string | null>(null);
  const [showKeysModal, setShowKeysModal] = useState(false);

  useEffect(() => {
    void api
      .getAdminSession()
      .then((res) => {
        const authed = Boolean(res.authenticated);
        setIsAdmin(authed);
        if (authed) {
          return api.getSystemStatus().then(setSysStatus).catch(() => null);
        }
        return null;
      })
      .catch(() => null);
    void api
      .getStudentProfile()
      .then((profile) => {
        if (profile.nationality) setNationality(profile.nationality);
        if (profile.major) setMajor(profile.major);
        if (
          profile.target_degree === 'high_school' ||
          profile.target_degree === 'bachelor' ||
          profile.target_degree === 'master' ||
          profile.target_degree === 'phd'
        ) {
          setDegreeLevel(profile.target_degree);
        }
        if (profile.target_countries && profile.target_countries.length > 0) {
          setTargetCountry(profile.target_countries[0]);
        }
        if (profile.gpa_raw) setGpaRaw(profile.gpa_raw);
        if (profile.gpa_scale) setGpaScale(profile.gpa_scale);
        if (profile.languages) setLanguages(profile.languages);
      })
      .catch(() => null);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const runId = makeRunId();
    const controller = new AbortController();
    abortRef.current = controller;
    setActiveRunId(runId);
    setRunning(true);
    try {
      const st = await api.getStudentStatus().catch(() => null);
      if (!st?.authenticated) {
        await api.startStudentSession();
      }
      const res = await api.runProfileExternalSearch(
        {
          run_id: runId,
          nationality: nationality.trim() || 'Yemen',
          target_degree: degreeLevel,
          major: major.trim(),
          target_countries: targetCountry.trim() ? [targetCountry.trim()] : [],
          target_fields: major.trim() ? [major.trim()] : [],
          gpa_raw: gpaRaw.trim() || null,
          gpa_scale: gpaScale ? gpaScale : null,
          languages,
          use_cache: true,
        },
        controller.signal,
      );
      setOutput(res);
      toast(lang === 'en' ? res.stop_reason_en : res.stop_reason_ar);
    } catch (err) {
      if ((err as Error)?.name !== 'AbortError') {
        setError(err);
      }
    } finally {
      abortRef.current = null;
      setActiveRunId(null);
      setRunning(false);
    }
  }

  async function onCancel() {
    if (activeRunId) {
      void api.cancelProfileExternalSearch(activeRunId).catch(() => null);
    }
    abortRef.current?.abort();
    setRunning(false);
    setActiveRunId(null);
  }

  async function onPromote(item: ExternalSearchCandidateResult) {
    setPromotingUrl(item.official_url);
    try {
      await api.promoteExternalResult(item);
      toast(t('extSearchPromotedToast'));
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setPromotingUrl(null);
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('searchTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('searchSubtitle')}
          </p>
        </div>
        {sysStatus && (
          <div className="cluster">
            <span className={sysStatus.search_configured ? 'pill pill--paid' : 'pill pill--partial'}>
              <Icon name={sysStatus.search_configured ? 'checkCircle' : 'alert'} />
              {t('navSearch')}: {sysStatus.search_provider ?? t('readyNo')}
              {sysStatus.tavily_key_hint
                ? ` (${sysStatus.tavily_key_hint})`
                : sysStatus.serper_key_hint
                  ? ` (${sysStatus.serper_key_hint})`
                  : ''}
            </span>
            {sysStatus.dev_keys_enabled && (
              <Button variant="glass" icon="vault" onClick={() => setShowKeysModal(true)}>
                {t('apiKeysBtn')}
              </Button>
            )}
          </div>
        )}
      </div>

      <Card title={t('searchTitle')} icon="search">
        <form className="form" onSubmit={onSubmit}>
          <div className="form__row">
            <Field label={t('extSearchNationalityLabel')}>
              {(id) => (
                <TextInput
                  id={id}
                  required
                  value={nationality}
                  placeholder={lang === 'en' ? 'e.g. Yemen, Sudan, Syria' : 'مثال: اليمن، السودان، سوريا'}
                  onChange={(e) => setNationality(e.target.value)}
                />
              )}
            </Field>
            <Field label={t('fieldMajor')}>
              {(id) => (
                <TextInput
                  id={id}
                  required
                  value={major}
                  placeholder={t('fieldMajorPh')}
                  onChange={(e) => setMajor(e.target.value)}
                />
              )}
            </Field>
          </div>

          <div className="form__row">
            <Field label={t('fieldDegree')}>
              {(id) => (
                <Select
                  id={id}
                  value={degreeLevel}
                  onChange={(e) => setDegreeLevel(e.target.value as DegreeChoice)}
                >
                  <option value="high_school">{lang === 'en' ? 'High School' : 'ثانوية عامة'}</option>
                  <option value="bachelor">{lang === 'en' ? 'Bachelor' : 'بكالوريوس'}</option>
                  <option value="master">{lang === 'en' ? 'Master' : 'ماجستير'}</option>
                  <option value="phd">{lang === 'en' ? 'PhD' : 'دكتوراه'}</option>
                </Select>
              )}
            </Field>
            <Field label={t('fieldCountry')}>
              {(id) => (
                <Select id={id} value={targetCountry} onChange={(e) => setTargetCountry(e.target.value)}>
                  <option value="">
                    {lang === 'en' ? 'Any Country (All Destinations)' : 'أي دولة (جميع الوجهات)'}
                  </option>
                  {TARGET_COUNTRIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {lang === 'en' ? c.en : `${c.ar} (${c.en})`}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>

          <div className="form__row">
            <Field label={lang === 'en' ? 'GPA / Grade (Optional)' : 'المعدل الأكاديمي (اختياري)'}>
              {(id) => (
                <TextInput
                  id={id}
                  value={gpaRaw}
                  placeholder={lang === 'en' ? 'e.g. 3.6 or 88' : 'مثال: 3.6 أو 88'}
                  onChange={(e) => setGpaRaw(e.target.value)}
                />
              )}
            </Field>
            <Field label={lang === 'en' ? 'GPA Scale' : 'نظام المعدل'}>
              {(id) => (
                <Select id={id} value={gpaScale} onChange={(e) => setGpaScale(e.target.value as GpaScaleChoice)}>
                  <option value="">{lang === 'en' ? 'Not specified' : 'غير محدد'}</option>
                  <option value="4.0">4.0</option>
                  <option value="5.0">5.0</option>
                  <option value="100">100%</option>
                  <option value="label">{lang === 'en' ? 'Grade Label' : 'تقدير لفظي'}</option>
                </Select>
              )}
            </Field>
          </div>

          <FormError error={error} />

          <div className="cluster">
            <Button type="submit" variant="primary" icon="search" loading={running}>
              {t('btnRunSearch')}
            </Button>
            {running && (
              <Button type="button" variant="glass" icon="pause" onClick={() => void onCancel()}>
                {t('extSearchCancelBtn')}
              </Button>
            )}
          </div>
        </form>
      </Card>

      {!output ? (
        <EmptyState icon="sparkle" title={t('reactResultsTitle')}>
          {t('reactNoResults')}
        </EmptyState>
      ) : (
        <div className="grid grid--main">
          <Card title={`${t('reactResultsTitle')} (${output.results.length})`} icon="checkCircle">
            <div className="cluster" style={{ marginBottom: 10 }}>
              <span
                className={
                  output.status === 'complete'
                    ? 'pill pill--paid'
                    : output.status === 'partial'
                      ? 'pill pill--partial'
                      : 'pill pill--unpaid'
                }
              >
                {output.status === 'complete'
                  ? t('extSearchStatusComplete')
                  : output.status === 'partial'
                    ? t('extSearchStatusPartial')
                    : t('extSearchStatusFailed')}
              </span>
              <span className="subtle num">
                {lang === 'en'
                  ? `${output.queries_executed} queries · ${output.pages_checked} pages`
                  : `${output.queries_executed} استعلامات · ${output.pages_checked} صفحات`}
              </span>
              {output.cached && (
                <span className="pill pill--neutral">{lang === 'en' ? 'Cached (24h)' : 'من الذاكرة (24س)'}</span>
              )}
            </div>

            <p className="muted" style={{ marginTop: 0 }}>
              {lang === 'en' ? output.disclaimer_en : output.disclaimer_ar}
            </p>

            {output.results.length === 0 ? (
              <EmptyState icon="search" title={t('noGrantsTitle')}>
                {lang === 'en' ? output.stop_reason_en : output.stop_reason_ar}
              </EmptyState>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {output.results.map((item, idx) => (
                  <Glass key={idx} className="grant-card">
                    <div className="grant-card__head">
                      <h3 className="grant-card__title">{item.title}</h3>
                      <div className="cluster" style={{ gap: 6 }}>
                        <span className="pill pill--neutral">{t('extSearchOutsideBadge')}</span>
                        <span
                          aria-label={`${t('ariaMatchLabel')}: ${Math.round(item.match_result.match_percentage)}% (${
                            item.match_result.eligible ? t('eligibleBadge') : t('ineligibleBadge')
                          })`}
                          className={
                            item.match_result.eligible
                              ? 'pill pill--paid'
                              : item.match_result.status === 'ineligible'
                                ? 'pill pill--unpaid'
                                : 'pill pill--partial'
                          }
                        >
                          <span className="num">{Math.round(item.match_result.match_percentage)}%</span>
                        </span>
                      </div>
                    </div>

                    {item.description && (
                      <p className="muted" style={{ margin: '6px 0 0' }}>
                        {item.description}
                      </p>
                    )}

                    <div className="subtle" style={{ marginTop: 6 }}>
                      <strong>{t('deadlineLabel')}:</strong>{' '}
                      <span className="num">{item.deadline || t('rollingDeadline')}</span>
                      {item.host_country ? ` · ${item.host_country}` : ''}
                    </div>

                    {Object.entries(item.evidence || {}).slice(0, 3).map(([fieldKey, quote]) => (
                      <div key={fieldKey} className="quote-box" style={{ marginTop: 6 }}>
                        <strong>{fieldKey}:</strong> “{quote}”
                      </div>
                    ))}

                    {item.nationality_evidence && (
                      <div className="subtle" style={{ marginTop: 6 }}>
                        <strong>{lang === 'en' ? 'Nationality evidence:' : 'دليل الجنسية:'}</strong> “
                        {item.nationality_evidence}”
                      </div>
                    )}

                    <div className="cluster" style={{ marginTop: 10 }}>
                      <a
                        className="btn btn--primary btn--sm"
                        href={safeHref(item.official_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t('officialPortal')}
                      </a>
                      {isAdmin && (
                        <Button
                          size="sm"
                          variant="glass"
                          icon="plus"
                          loading={promotingUrl === item.official_url}
                          onClick={() => void onPromote(item)}
                        >
                          {t('extSearchPromoteBtn')}
                        </Button>
                      )}
                    </div>
                  </Glass>
                ))}
              </div>
            )}
          </Card>

          <Card title={`${t('reactTraceTitle')} (${output.steps_taken})`} icon="list">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {output.step_log.map((step) => (
                <div key={step.step_number} className="trace-step">
                  <div className="trace-step__head">
                    <span className="pill pill--neutral">
                      {t('stepLabel')} <span className="num">{step.step_number}</span>
                    </span>
                    <span
                      className={
                        step.verdict === 'ok'
                          ? 'pill pill--paid'
                          : step.verdict === 'rejected'
                            ? 'pill pill--unpaid'
                            : 'pill pill--partial'
                      }
                    >
                      {step.kind}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.88rem', color: 'var(--text-2)', marginTop: 4 }}>
                    {lang === 'en' ? step.message_en : step.message_ar}
                  </div>
                  {step.target && (
                    <code className="subtle" style={{ wordBreak: 'break-all' }}>
                      {step.target}
                    </code>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
      {showKeysModal && sysStatus?.dev_keys_enabled && (
        <ApiKeysModal
          status={sysStatus}
          onClose={() => setShowKeysModal(false)}
          onSaved={(updated) => setSysStatus(updated)}
        />
      )}
    </div>
  );
}
