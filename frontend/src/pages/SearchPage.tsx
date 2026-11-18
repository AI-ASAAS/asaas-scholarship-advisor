import { useEffect, useState, type FormEvent } from 'react';
import {
  Button,
  Card,
  EmptyState,
  Field,
  FormError,
  Glass,
  PasswordInput,
  Select,
  Swash,
  TextInput,
  useToast,
} from '../asaas-ui';
import { ApiKeysModal } from '../components/ApiKeysModal';
import { api, safeHref, type ExternalSearchOutput, type SystemStatus } from '../lib/api';
import { useLang } from '../lib/i18n';

const TARGET_COUNTRIES = [
  { value: 'Germany', ar: 'ألمانيا', en: 'Germany' },
  { value: 'Turkey', ar: 'تركيا', en: 'Turkey' },
  { value: 'United Kingdom', ar: 'بريطانيا', en: 'United Kingdom' },
  { value: 'United States', ar: 'الولايات المتحدة', en: 'United States' },
  { value: 'Hungary', ar: 'المجر', en: 'Hungary' },
  { value: 'France', ar: 'فرنسا', en: 'France' },
  { value: 'China', ar: 'الصين', en: 'China' },
  { value: 'Russia', ar: 'روسيا', en: 'Russia' },
  { value: 'Romania', ar: 'رومانيا', en: 'Romania' },
  { value: 'Malaysia', ar: 'ماليزيا', en: 'Malaysia' },
  { value: 'Japan', ar: 'اليابان', en: 'Japan' },
  { value: 'South Korea', ar: 'كوريا الجنوبية', en: 'South Korea' },
  { value: 'Canada', ar: 'كندا', en: 'Canada' },
  { value: 'Australia', ar: 'أستراليا', en: 'Australia' },
  { value: 'Netherlands', ar: 'هولندا', en: 'Netherlands' },
  { value: 'Italy', ar: 'إيطاليا', en: 'Italy' },
  { value: 'Sweden', ar: 'السويد', en: 'Sweden' },
  { value: 'Saudi Arabia', ar: 'السعودية', en: 'Saudi Arabia' },
  { value: 'Qatar', ar: 'قطر', en: 'Qatar' },
  { value: 'United Arab Emirates', ar: 'الإمارات', en: 'United Arab Emirates' },
  { value: 'Egypt', ar: 'مصر', en: 'Egypt' },
  { value: 'Jordan', ar: 'الأردن', en: 'Jordan' },
];

export default function SearchPage() {
  const { lang, t } = useLang();
  const toast = useToast();

  const [major, setMajor] = useState('Computer Science');
  const [degreeLevel, setDegreeLevel] = useState('Master');
  const [targetCountry, setTargetCountry] = useState('');
  const [tavilyKey, setTavilyKey] = useState('');
  const [serperKey, setSerperKey] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [output, setOutput] = useState<ExternalSearchOutput | null>(null);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [showKeysModal, setShowKeysModal] = useState(false);

  useEffect(() => {
    void api.getSystemStatus().then(setSysStatus).catch(() => null);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setRunning(true);
    try {
      const res = await api.searchExternal({
        major,
        degree_level: degreeLevel,
        target_country: targetCountry.trim() || undefined,
        max_steps: 5,
        tavily_api_key: tavilyKey.trim() || undefined,
        serper_api_key: serperKey.trim() || undefined,
      });
      setOutput(res);
      setTavilyKey('');
      setSerperKey('');
      void api.getSystemStatus().then(setSysStatus).catch(() => null);
      toast(res.reason);
    } catch (err) {
      setError(err);
    } finally {
      setRunning(false);
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
        <Button variant="glass" icon="vault" onClick={() => setShowKeysModal(true)}>
          {t('apiKeysBtn')}
        </Button>
      </div>

      <Card title={t('searchTitle')} icon="search">
        <form className="form" onSubmit={onSubmit}>
          <div className="form__row">
            <Field
              label={t('apiKeyTavily')}
              hint={
                sysStatus?.tavily_key_hint
                  ? `${t('readyYes')}: ${sysStatus.tavily_key_hint}`
                  : t('apiKeyTavilyHint')
              }
            >
              {(id) => (
                <PasswordInput
                  id={id}
                  autoComplete="off"
                  placeholder={sysStatus?.tavily_key_hint || 'tvly-...'}
                  value={tavilyKey}
                  onChange={(e) => setTavilyKey(e.target.value)}
                />
              )}
            </Field>
            <Field
              label={t('apiKeySerper')}
              hint={
                sysStatus?.serper_key_hint
                  ? `${t('readyYes')}: ${sysStatus.serper_key_hint}`
                  : t('apiKeySerperHint')
              }
            >
              {(id) => (
                <PasswordInput
                  id={id}
                  autoComplete="off"
                  placeholder={sysStatus?.serper_key_hint || 'Serper API Key'}
                  value={serperKey}
                  onChange={(e) => setSerperKey(e.target.value)}
                />
              )}
            </Field>
          </div>

          <div className="form__row">
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
            <Field label={t('fieldDegree')}>
              {(id) => (
                <Select id={id} value={degreeLevel} onChange={(e) => setDegreeLevel(e.target.value)}>
                  <option value="Bachelor">Bachelor / بكالوريوس</option>
                  <option value="Master">Master / ماجستير</option>
                  <option value="PhD">PhD / دكتوراه</option>
                </Select>
              )}
            </Field>
          </div>

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

          <FormError error={error} />

          <div className="cluster">
            <Button type="submit" variant="primary" icon="search" loading={running}>
              {t('btnRunSearch')}
            </Button>
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
            <p className="muted" style={{ marginTop: 0 }}>
              {output.reason}
            </p>
            {output.results.length === 0 ? (
              <EmptyState icon="search" title={t('noGrantsTitle')}>
                {output.reason}
              </EmptyState>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {output.results.map((item, idx) => (
                  <Glass key={idx} className="grant-card">
                    <div className="grant-card__head">
                      <h3 className="grant-card__title">{item.title}</h3>
                      <span
                        className={
                          item.accepts_yemeni === 'yes'
                            ? 'pill pill--paid'
                            : item.accepts_yemeni === 'no'
                              ? 'pill pill--unpaid'
                              : 'pill pill--partial'
                        }
                      >
                        {item.accepts_yemeni === 'yes'
                          ? t('yemenYes')
                          : item.accepts_yemeni === 'no'
                            ? t('yemenNo')
                            : t('yemenUnclear')}
                      </span>
                    </div>
                    <p className="muted" style={{ margin: 0 }}>
                      {item.match_reason}
                    </p>
                    <div className="quote-box">“{item.evidence_quote}”</div>
                    {item.yemen_evidence && (
                      <div className="subtle">
                        <strong>{lang === 'en' ? 'Yemen eligibility:' : 'دليل قبول اليمنيين:'}</strong> “{item.yemen_evidence}”
                      </div>
                    )}
                    <div className="cluster">
                      <a
                        className="btn btn--primary btn--sm"
                        href={safeHref(item.official_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t('officialPortal')}
                      </a>
                    </div>
                  </Glass>
                ))}
              </div>
            )}
          </Card>

          <Card title={`${t('reactTraceTitle')} (${output.steps_taken}/5)`} icon="list">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {output.trace.map((step) => (
                <div key={step.step_number} className="trace-step">
                  <div className="trace-step__head">
                    <span className="pill pill--neutral">
                      {t('stepLabel')} <span className="num">{step.step_number}</span>
                    </span>
                    <code className="subtle">{step.action}</code>
                  </div>
                  <div className="subtle">
                    <strong>{t('thoughtLabel')}:</strong> {step.thought}
                  </div>
                  <div style={{ fontSize: '0.88rem', color: 'var(--text-2)' }}>
                    <strong>{t('observationLabel')}:</strong> {step.observation}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
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
