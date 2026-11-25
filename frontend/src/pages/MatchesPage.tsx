import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Glass,
  Icon,
  ProgressBar,
  Segmented,
  Skeleton,
  Swash,
  formatDate,
  useToast,
} from '../asaas-ui';
import {
  ApiError,
  api,
  safeHref,
  type CriterionBreakdown,
  type ExternalSearchRunResponse,
  type MatchesListResponse,
  type ProfileAnalysisResponse,
} from '../lib/api';
import { useLang } from '../lib/i18n';

function makeExternalRunId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `matches-ext-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export default function MatchesPage() {
  const { t, lang } = useLang();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [missingProfile, setMissingProfile] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [data, setData] = useState<MatchesListResponse | null>(null);
  const [expandedIds, setExpandedIds] = useState<Record<number, boolean>>({});

  const [analyzing, setAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<unknown>(null);
  const [analysis, setAnalysis] = useState<ProfileAnalysisResponse | null>(null);
  const [plannedGrantIds, setPlannedGrantIds] = useState<Set<number>>(new Set());
  const [addingGrantId, setAddingGrantId] = useState<number | null>(null);

  // Integrated outside-ASAAS external deep search state
  const [extLimit, setExtLimit] = useState<3 | 5>(5);
  const [extRunning, setExtRunning] = useState(false);
  const [extRunId, setExtRunId] = useState<string | null>(null);
  const extAbortRef = useRef<AbortController | null>(null);
  const [extError, setExtError] = useState<unknown>(null);
  const [extData, setExtData] = useState<ExternalSearchRunResponse | null>(null);
  const [extLastLimit, setExtLastLimit] = useState<3 | 5 | null>(null);
  const [extExpandedUrls, setExtExpandedUrls] = useState<Record<string, boolean>>({});
  const [showExtLog, setShowExtLog] = useState(false);

  const loadMatches = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMissingProfile(false);
    try {
      const [res, planRes] = await Promise.all([
        api.getMatches(),
        api.getPlan().catch(() => null),
      ]);
      setData(res);
      if (planRes?.items) {
        setPlannedGrantIds(new Set(planRes.items.map((it) => it.grant_id)));
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
        setMissingProfile(true);
      } else {
        setError(err);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  async function handleAddToPlan(grantId: number, allowIneligible = false) {
    setAddingGrantId(grantId);
    try {
      const planRes = await api.addPlanGrant(grantId, { allowIneligible });
      setPlannedGrantIds(new Set(planRes.items.map((it) => it.grant_id)));
      toast(t('planAddedToast'));
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setAddingGrantId(null);
    }
  }

  useEffect(() => {
    void loadMatches();
  }, [loadMatches]);

  async function handleRunAnalysis() {
    setAnalyzing(true);
    setAnalysisError(null);
    try {
      const res = await api.runProfileAnalysis();
      setAnalysis(res);
      if (res.analysis_mode === 'deterministic_fallback') {
        toast(lang === 'en' ? res.fallback_notice_en || t('analysisModeFallback') : res.fallback_notice_ar || t('analysisModeFallback'));
      }
    } catch (err) {
      setAnalysisError(err);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleRunExternalMatches(limitOverride?: 3 | 5) {
    const targetLimit = limitOverride ?? extLimit;
    const runId = makeExternalRunId();
    const controller = new AbortController();
    extAbortRef.current = controller;
    setExtRunId(runId);
    setExtRunning(true);
    setExtError(null);
    const shouldUseCache = !(extData && extLastLimit === targetLimit);
    try {
      const res = await api.runMatchesExternalSearch(
        { limit: targetLimit, run_id: runId, use_cache: shouldUseCache },
        controller.signal,
      );
      setExtData(res);
      setExtLastLimit(targetLimit);
      toast(lang === 'en' ? res.stop_reason_en : res.stop_reason_ar);
    } catch (err) {
      if ((err as Error)?.name !== 'AbortError') {
        setExtError(err);
      }
    } finally {
      extAbortRef.current = null;
      setExtRunId(null);
      setExtRunning(false);
    }
  }

  async function handleCancelExternalMatches() {
    if (extRunId) {
      void api.cancelProfileExternalSearch(extRunId).catch(() => null);
    }
    extAbortRef.current?.abort();
    setExtRunning(false);
    setExtRunId(null);
  }

  function criterionLabel(key: string): string {
    const map: Record<string, string> = {
      nationality: t('critNationality'),
      degree_level: t('critDegree'),
      gpa: t('critGpa'),
      language: t('critLanguage'),
      field_of_study: t('critField'),
      work_experience: t('critWork'),
      age: t('critAge'),
    };
    return map[key] || key;
  }

  function renderCriterionPill(status: CriterionBreakdown['status']) {
    if (status === 'met') {
      return (
        <span className="pill pill--paid">
          <Icon name="checkCircle" />
          {t('statusMet')}
        </span>
      );
    }
    if (status === 'not_met') {
      return (
        <span className="pill pill--unpaid">
          <Icon name="alert" />
          {t('statusNotMet')}
        </span>
      );
    }
    if (status === 'unknown') {
      return (
        <span className="pill pill--partial">
          <Icon name="clock" />
          {t('statusUnknown')}
        </span>
      );
    }
    return <span className="pill pill--neutral">{t('statusNA')}</span>;
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('matchesTitle')}</Swash>
          </h1>
        </div>
        <div className="cluster">
          <Link to="/profile" className="btn btn--glass">
            <Icon name="edit" />
            {t('navProfile')}
          </Link>
        </div>
      </div>

      {loading && <Skeleton height={160} count={3} />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void loadMatches()} /> : null}

      {!loading && !error && missingProfile && (
        <EmptyState icon="users" title={t('matchesEmptyTitle')}>
          <p>{t('matchesEmptyBody')}</p>
          <div style={{ marginTop: 12 }}>
            <Link to="/profile" className="btn btn--primary">
              <Icon name="users" />
              {t('ctaBuildProfileBtn')}
            </Link>
          </div>
        </EmptyState>
      )}

      {!loading && !error && !missingProfile && data && (
        <>
          <div className="notice-banner">
            <Icon name="alert" />
            <span>{lang === 'en' ? data.disclaimer_en : data.disclaimer_ar}</span>
          </div>

          {/* Profile Analysis Card */}
          <Card
            title={t('analysisCardTitle')}
            icon="sparkle"
            actions={
              <Button
                variant="primary"
                size="sm"
                icon="sparkle"
                loading={analyzing}
                onClick={() => void handleRunAnalysis()}
              >
                {t('btnRunAnalysis')}
              </Button>
            }
          >
            {analysisError ? (
              <ErrorState error={analysisError} onRetry={() => void handleRunAnalysis()} />
            ) : null}

            {!analysis && !analysisError && (
              <p className="muted" style={{ margin: 0 }}>
                {lang === 'en'
                  ? 'Click "Analyze My Profile" to view strengths, weaknesses, and missing documents across your top matches.'
                  : 'اضغط "تحليل ملفي الشخصي الآن" لعرض نقاط القوة والضعف والفجوات والوثائق المطلوبة بناءً على نتائجك.'}
              </p>
            )}

            {analysis && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div className="cluster">
                  <span
                    className={
                      analysis.analysis_mode === 'llm_grounded'
                        ? 'pill pill--paid'
                        : 'pill pill--partial'
                    }
                  >
                    <Icon name={analysis.analysis_mode === 'llm_grounded' ? 'checkCircle' : 'alert'} />
                    {analysis.analysis_mode === 'llm_grounded'
                      ? t('analysisModeAi')
                      : t('analysisModeFallback')}
                  </span>
                </div>

                {analysis.analysis_mode === 'deterministic_fallback' &&
                  (analysis.fallback_notice_ar || analysis.fallback_notice_en) && (
                    <div className="notice-banner">
                      <Icon name="clock" />
                      <span>
                        {lang === 'en' ? analysis.fallback_notice_en : analysis.fallback_notice_ar}
                      </span>
                    </div>
                  )}

                <p className="prose" style={{ margin: 0 }}>
                  {analysis.summary_ar}
                </p>

                {analysis.strengths.length > 0 && (
                  <div className="detail-section">
                    <h4>{t('analysisStrengths')}</h4>
                    <ul className="detail-list">
                      {analysis.strengths.map((s, i) => (
                        <li key={i}>
                          {s.text_ar}{' '}
                          <span className="subtle num">[{s.finding_ids.join(', ')}]</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {analysis.weaknesses.length > 0 && (
                  <div className="detail-section">
                    <h4>{t('analysisWeaknesses')}</h4>
                    <ul className="detail-list">
                      {analysis.weaknesses.map((s, i) => (
                        <li key={i}>
                          {s.text_ar}{' '}
                          <span className="subtle num">[{s.finding_ids.join(', ')}]</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {analysis.improvement_areas.length > 0 && (
                  <div className="detail-section">
                    <h4>{t('analysisImprovements')}</h4>
                    <ul className="detail-list">
                      {analysis.improvement_areas.map((s, i) => (
                        <li key={i}>
                          {s.text_ar}{' '}
                          <span className="subtle num">[{s.finding_ids.join(', ')}]</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Eligible Grants */}
          <div className="detail-section">
            <h2 style={{ margin: 0 }}>{t('eligibleSectionTitle')}</h2>
            {data.eligible_grants.length === 0 ? (
              <EmptyState icon="search" title={t('noGrantsTitle')}>
                {t('noGrantsBody')}
              </EmptyState>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {data.eligible_grants.map((item) => {
                  const isExpanded = Boolean(expandedIds[item.grant_id]);
                  return (
                    <Glass key={item.grant_id} className="grant-card">
                      <div className="grant-card__head">
                        <h3 className="grant-card__title" style={{ margin: 0 }}>
                          {item.title}
                        </h3>
                        <span
                          className="pill pill--paid"
                          aria-label={`${t('ariaEligibilityLabel')}: ${t('eligibleBadge')}`}
                        >
                          <Icon name="checkCircle" />
                          {t('eligibleBadge')}
                        </span>
                      </div>

                      <div className="match-card__scores">
                        <div
                          className="score-box"
                          aria-label={`${t('ariaMatchLabel')}: ${item.match_percentage}%`}
                        >
                          <span className="subtle">{t('matchScoreLabel')}</span>
                          <strong className="num" style={{ fontSize: '1.15rem' }}>
                            {item.match_percentage}%
                          </strong>
                          <ProgressBar value={item.match_percentage} max={100} />
                        </div>
                        <div className="score-box">
                          <span className="subtle">{t('coverageLabel')}</span>
                          <strong className="num" style={{ fontSize: '1.15rem' }}>
                            {item.coverage_percentage}%
                          </strong>
                          <ProgressBar value={item.coverage_percentage} max={100} />
                        </div>
                      </div>

                      {item.missing_info_hints.length > 0 && (
                        <div className="quote-box">
                          <strong>{t('missingInfoTitle')}</strong>
                          <ul className="detail-list" style={{ marginTop: 6 }}>
                            {item.missing_info_hints.map((hint, hi) => (
                              <li key={hi}>{hint}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      <div className="grant-card__foot">
                        <span className="grant-deadline">
                          <Icon name="calendar" />
                          {t('deadlineLabel')}:{' '}
                          <span className="num">
                            {item.deadline ? formatDate(item.deadline) : t('rollingDeadline')}
                          </span>
                        </span>
                        <div className="cluster">
                          <Button
                            size="sm"
                            variant="glass"
                            aria-expanded={isExpanded}
                            onClick={() =>
                              setExpandedIds((prev) => ({
                                ...prev,
                                [item.grant_id]: !isExpanded,
                              }))
                            }
                          >
                            {isExpanded ? t('hideWhyBtn') : t('whyScoreBtn')}
                          </Button>
                          {plannedGrantIds.has(item.grant_id) ? (
                            <Link to="/plan" className="pill pill--paid" style={{ textDecoration: 'none' }}>
                              <Icon name="checkCircle" />
                              {t('planInPlanBadge')}
                            </Link>
                          ) : (
                            <Button
                              size="sm"
                              variant="primary"
                              icon="calendar"
                              loading={addingGrantId === item.grant_id}
                              onClick={() => void handleAddToPlan(item.grant_id, false)}
                            >
                              {t('planAddBtn')}
                            </Button>
                          )}
                          <a
                            className="btn btn--glass btn--sm"
                            href={safeHref(item.official_url)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {t('officialPortal')}
                          </a>
                        </div>
                      </div>

                      {isExpanded && (
                        <div className="table-wrap" style={{ marginTop: 10 }}>
                          <table className="table">
                            <thead>
                              <tr>
                                <th>{t('colCriterion')}</th>
                                <th>{t('colStatus')}</th>
                                <th>{t('colGrantReq')}</th>
                                <th>{t('colYourValue')}</th>
                                <th>{t('colEvidence')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {item.criteria.map((c) => (
                                <tr key={c.key}>
                                  <td>{criterionLabel(c.key)}</td>
                                  <td>{renderCriterionPill(c.status)}</td>
                                  <td>{c.grant_value || '—'}</td>
                                  <td>{c.student_value || '—'}</td>
                                  <td className="subtle">{c.evidence_quote ? `“${c.evidence_quote}”` : '—'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </Glass>
                  );
                })}
              </div>
            )}
          </div>

          {/* Outside ASAAS External Matching Card (Top 3 or Top 5) */}
          <Card
            title={t('extMatchesTitle')}
            icon="search"
            actions={
              <div className="cluster">
                <Segmented
                  label={t('extMatchesLimitLabel')}
                  value={String(extLimit)}
                  onChange={(val) => setExtLimit(val === '3' ? 3 : 5)}
                  options={[
                    { value: '3', label: t('extMatchesTop3') },
                    { value: '5', label: t('extMatchesTop5') },
                  ]}
                />
                {extRunning ? (
                  <Button
                    size="sm"
                    variant="danger"
                    icon="alert"
                    onClick={() => void handleCancelExternalMatches()}
                  >
                    {t('extMatchesCancelBtn')}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="primary"
                    icon="search"
                    loading={extRunning}
                    onClick={() => void handleRunExternalMatches()}
                  >
                    {extData ? t('extMatchesRefreshBtn') : t('extMatchesBtn')}
                  </Button>
                )}
              </div>
            }
          >
            {!extData && !extRunning && !extError && (
              <p className="muted" style={{ margin: 0 }}>
                {t('extMatchesSubtitle')}
              </p>
            )}

            {extRunning && <Skeleton height={120} count={2} />}

            {extError ? (
              <ErrorState error={extError} onRetry={() => void handleRunExternalMatches()} />
            ) : null}

            {extData && !extRunning && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div className="notice-banner">
                  <Icon name="alert" />
                  <span>{lang === 'en' ? extData.disclaimer_en : extData.disclaimer_ar}</span>
                </div>

                <div className="cluster">
                  <span className="pill pill--neutral">
                    {lang === 'en'
                      ? `Pages verified: ${extData.pages_checked}`
                      : `الصفحات المفحوصة: ${extData.pages_checked}`}
                  </span>
                  <span className="pill pill--paid">
                    {lang === 'en'
                      ? `Matches outside ASAAS: ${extData.results.length}`
                      : `نتائج مطابقة خارج أساس: ${extData.results.length}`}
                  </span>
                  {(extData.excluded_platform_count || 0) > 0 && (
                    <span className="pill pill--partial">
                      {lang === 'en'
                        ? `Skipped in ASAAS: ${extData.excluded_platform_count}`
                        : `مستبعد لتكراره في أساس: ${extData.excluded_platform_count}`}
                    </span>
                  )}
                </div>

                {extData.results.length === 0 ? (
                  <EmptyState icon="search" title={t('extMatchesEmptyTitle')}>
                    {t('extMatchesEmptyBody')}
                  </EmptyState>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    {extData.results.map((item) => {
                      const isExpanded = Boolean(extExpandedUrls[item.official_url]);
                      const m = item.match_result;
                      return (
                        <Glass key={item.official_url} className="grant-card">
                          <div className="grant-card__head">
                            <h3 className="grant-card__title" style={{ margin: 0 }}>
                              {item.title}
                            </h3>
                            <div className="cluster">
                              <span className="pill pill--partial">
                                {lang === 'en'
                                  ? item.outside_platform_label_en
                                  : item.outside_platform_label_ar}
                              </span>
                              <span className="pill pill--paid">
                                <Icon name="checkCircle" />
                                {t('eligibleBadge')}
                              </span>
                            </div>
                          </div>

                          <div className="match-card__scores">
                            <div className="score-box">
                              <span className="subtle">{t('matchScoreLabel')}</span>
                              <strong className="num" style={{ fontSize: '1.15rem' }}>
                                {m.match_percentage}%
                              </strong>
                              <ProgressBar value={m.match_percentage} max={100} />
                            </div>
                            <div className="score-box">
                              <span className="subtle">{t('coverageLabel')}</span>
                              <strong className="num" style={{ fontSize: '1.15rem' }}>
                                {m.coverage_percentage}%
                              </strong>
                              <ProgressBar value={m.coverage_percentage} max={100} />
                            </div>
                          </div>

                          {item.description && (
                            <p className="muted" style={{ margin: 0 }}>
                              {item.description}
                            </p>
                          )}

                          {item.nationality_evidence && (
                            <div className="quote-box">
                              <strong>
                                {lang === 'en'
                                  ? 'Nationality Eligibility Evidence:'
                                  : 'دليل أهلية الجنسية من الموقع الرسمي:'}
                              </strong>
                              <div className="subtle" style={{ marginTop: 4 }}>
                                “{item.nationality_evidence}”
                              </div>
                            </div>
                          )}

                          <div className="grant-card__foot">
                            <span className="grant-deadline">
                              <Icon name="calendar" />
                              {t('deadlineLabel')}:{' '}
                              <span className="num">
                                {item.deadline ? formatDate(item.deadline) : t('rollingDeadline')}
                              </span>
                            </span>
                            <div className="cluster">
                              <Button
                                size="sm"
                                variant="glass"
                                aria-expanded={isExpanded}
                                onClick={() =>
                                  setExtExpandedUrls((prev) => ({
                                    ...prev,
                                    [item.official_url]: !isExpanded,
                                  }))
                                }
                              >
                                {isExpanded ? t('hideWhyBtn') : t('whyScoreBtn')}
                              </Button>
                              <a
                                className="btn btn--primary btn--sm"
                                href={safeHref(item.official_url)}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {t('officialPortal')}
                              </a>
                            </div>
                          </div>

                          {isExpanded && (
                            <div className="table-wrap" style={{ marginTop: 10 }}>
                              <table className="table">
                                <thead>
                                  <tr>
                                    <th>{t('colCriterion')}</th>
                                    <th>{t('colStatus')}</th>
                                    <th>{t('colGrantReq')}</th>
                                    <th>{t('colYourValue')}</th>
                                    <th>{t('colEvidence')}</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {m.criteria.map((c) => (
                                    <tr key={c.key}>
                                      <td>{criterionLabel(c.key)}</td>
                                      <td>{renderCriterionPill(c.status)}</td>
                                      <td>{c.grant_value || '—'}</td>
                                      <td>{c.student_value || '—'}</td>
                                      <td className="subtle">
                                        {c.evidence_quote ? `“${c.evidence_quote}”` : '—'}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </Glass>
                      );
                    })}
                  </div>
                )}

                {extData.step_log.length > 0 && (
                  <div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowExtLog((prev) => !prev)}
                    >
                      {t('extMatchesStepLogTitle')} ({extData.step_log.length})
                    </Button>
                    {showExtLog && (
                      <ul className="detail-list" style={{ marginTop: 8 }}>
                        {extData.step_log.map((step, si) => (
                          <li key={si} className="subtle">
                            <strong>[{step.verdict}]</strong>{' '}
                            {lang === 'en' ? step.message_en : step.message_ar}
                            {step.target ? ` (${step.target})` : ''}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Ineligible Grants (Hard Gates) */}
          {data.ineligible_grants.length > 0 && (
            <Card title={t('ineligibleSectionTitle')} icon="alert">
              <div className="list">
                {data.ineligible_grants.map((item) => (
                  <div key={item.grant_id} className="row row--stack">
                    <div className="row__main">
                      <div className="row__title">{item.title}</div>
                      <div className="row__meta row__meta--wrap">
                        <span className="pill pill--unpaid">
                          <Icon name="alert" />
                          {t('ineligibleBadge')}
                        </span>
                      </div>
                      <ul className="detail-list" style={{ marginTop: 8 }}>
                        {item.disqualifiers.map((d, di) => (
                          <li key={di}>
                            {lang === 'en' ? d.reason_en : d.reason_ar}
                            {d.evidence_quote ? ` — “${d.evidence_quote}”` : ''}
                          </li>
                        ))}
                      </ul>
                      <div style={{ marginTop: 10 }}>
                        {plannedGrantIds.has(item.grant_id) ? (
                          <Link to="/plan" className="pill pill--paid" style={{ textDecoration: 'none' }}>
                            <Icon name="checkCircle" />
                            {t('planInPlanBadge')}
                          </Link>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon="calendar"
                            loading={addingGrantId === item.grant_id}
                            onClick={() => void handleAddToPlan(item.grant_id, true)}
                          >
                            {t('planAddAnywayBtn')}
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
