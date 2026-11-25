import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Glass,
  Icon,
  ProgressBar,
  Select,
  Skeleton,
  Stat,
  Swash,
  formatDate,
  useToast,
} from '../asaas-ui';
import {
  ApiError,
  api,
  safeHref,
  type ChecklistStatusLiteral,
  type PlanGrantItem,
  type PlanOverviewResponse,
  type PlanSummaryResponse,
} from '../lib/api';
import { useLang } from '../lib/i18n';

export default function PlanPage() {
  const { t, lang } = useLang();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [missingProfile, setMissingProfile] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [plan, setPlan] = useState<PlanOverviewResponse | null>(null);

  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({});
  const [expandedMilestones, setExpandedMilestones] = useState<Record<number, boolean>>({});
  const [summary, setSummary] = useState<PlanSummaryResponse | null>(null);
  const [summarizing, setSummarizing] = useState(false);

  const syncPlanState = useCallback((res: PlanOverviewResponse) => {
    setPlan(res);
    const nextNotes: Record<number, string> = {};
    for (const it of res.items) {
      nextNotes[it.id] = it.notes || '';
    }
    setNotesDraft(nextNotes);
  }, []);

  const loadPlan = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMissingProfile(false);
    try {
      const res = await api.getPlan();
      syncPlanState(res);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
        setMissingProfile(true);
      } else {
        setError(err);
      }
    } finally {
      setLoading(false);
    }
  }, [syncPlanState]);

  useEffect(() => {
    void loadPlan();
  }, [loadPlan]);

  async function handleChecklistStatus(item: PlanGrantItem, checkId: string, status: ChecklistStatusLiteral) {
    try {
      const updated = await api.updatePlanItem(item.id, {
        checklist_updates: [{ id: checkId, status }],
      });
      syncPlanState(updated);
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    }
  }

  async function handleSaveNotes(itemId: number) {
    try {
      const updated = await api.updatePlanItem(itemId, {
        notes: notesDraft[itemId] ?? '',
      });
      syncPlanState(updated);
      toast(t('planNotesSavedToast'));
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    }
  }

  async function handleRemoveGrant(itemId: number) {
    try {
      const updated = await api.removePlanItem(itemId);
      syncPlanState(updated);
      toast(t('planRemovedToast'));
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    }
  }

  async function handleSummarize() {
    setSummarizing(true);
    try {
      const res = await api.summarizePlan();
      setSummary(res);
    } catch {
      setSummary(null);
    } finally {
      setSummarizing(false);
    }
  }

  function renderCountdownPill(item: PlanGrantItem) {
    if (!item.deadline || item.days_remaining === null || item.days_remaining === undefined) {
      return (
        <span className="pill pill--neutral">
          <Icon name="clock" />
          {t('rollingDeadline')}
        </span>
      );
    }
    if (item.urgency === 'overdue') {
      return (
        <span className="pill pill--unpaid">
          <Icon name="alert" />
          {t('planCountdownOverdue')} {Math.abs(item.days_remaining)} {t('planDaysUnit')}
        </span>
      );
    }
    if (item.urgency === 'due_today') {
      return (
        <span className="pill pill--unpaid">
          <Icon name="alert" />
          {t('planCountdownToday')}
        </span>
      );
    }
    if (item.urgency === 'due_soon') {
      return (
        <span className="pill pill--late">
          <Icon name="clock" />
          {t('planCountdownSoon')} {item.days_remaining} {t('planDaysUnit')}
        </span>
      );
    }
    return (
      <span className="pill pill--paid">
        <Icon name="calendar" />
        {t('planCountdownDays')} {item.days_remaining} {t('planDaysUnit')}
      </span>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('planPageTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('planPageSubtitle')}
          </p>
        </div>
        {plan && plan.total_grants > 0 && (
          <div className="cluster">
            <a className="btn btn--glass" href={api.downloadPlanIcsUrl()}>
              <Icon name="calendar" />
              {t('planDownloadIcs')}
            </a>
            <Button
              variant="primary"
              size="sm"
              icon="sparkle"
              loading={summarizing}
              onClick={() => void handleSummarize()}
            >
              {t('planAiSummaryBtn')}
            </Button>
          </div>
        )}
      </div>

      {loading && <Skeleton height={160} count={3} />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void loadPlan()} /> : null}

      {!loading && !error && missingProfile && (
        <EmptyState icon="users" title={t('docsNeedProfileTitle')}>
          <p style={{ margin: '0 0 12px' }}>{t('docsNeedProfileBody')}</p>
          <Link to="/profile" className="btn btn--primary">
            {t('docsGoToProfile')}
          </Link>
        </EmptyState>
      )}

      {!loading && !error && !missingProfile && plan && plan.total_grants === 0 && (
        <EmptyState icon="calendar" title={t('planEmptyTitle')}>
          <p style={{ margin: '0 0 12px' }}>{t('planEmptyBody')}</p>
          <Link to="/matches" className="btn btn--primary">
            <Icon name="trend" />
            {t('planGoToMatches')}
          </Link>
        </EmptyState>
      )}

      {!loading && !error && !missingProfile && plan && plan.total_grants > 0 && (
        <>
          <div className="grid-stats">
            <Stat label={t('planTotalGrants')} amount={plan.total_grants} unit="" icon="briefcase" />
            <Stat
              label={t('planOverallProgress')}
              amount={plan.overall_progress_percentage}
              unit="%"
              icon="checkCircle"
            />
          </div>

          {summary?.available && summary.summary_ar && (
            <Card title={t('planAiSummaryTitle')} icon="sparkle">
              <p style={{ margin: 0 }}>{summary.summary_ar}</p>
            </Card>
          )}

          {plan.conflicts.length > 0 && (
            <Card title={t('planConflictsTitle')} icon="alert">
              <div style={{ display: 'grid', gap: 8 }}>
                {plan.conflicts.map((cf) => (
                  <div key={cf.conflict_id} className="quote-box">
                    <div className="cluster" style={{ gap: 8 }}>
                      <Icon name="alert" />
                      <strong>{lang === 'en' ? cf.message_en : cf.message_ar}</strong>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Phone-first Timeline View (cards instead of horizontal tables) */}
          <Card title={t('planTimelineTitle')} icon="calendar">
            <div style={{ display: 'grid', gap: 10 }}>
              {plan.items.map((item) => {
                const openMs = Boolean(expandedMilestones[item.id]);
                return (
                  <div key={`tl-${item.id}`} className="quote-box" style={{ display: 'grid', gap: 8 }}>
                    <div className="cluster" style={{ justifyContent: 'space-between' }}>
                      <strong>
                        #{item.priority_rank} {item.title}
                      </strong>
                      {renderCountdownPill(item)}
                    </div>
                    <div className="cluster" style={{ justifyContent: 'space-between', fontSize: '0.88rem' }}>
                      <span className="muted num">
                        {t('deadlineLabel')}: {item.deadline ? formatDate(item.deadline) : t('rollingDeadline')}
                      </span>
                      {item.milestones.length > 0 && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            setExpandedMilestones((prev) => ({ ...prev, [item.id]: !openMs }))
                          }
                        >
                          {t('planMilestonesToggle')} ({item.milestones.length})
                        </Button>
                      )}
                    </div>

                    {openMs && item.milestones.length > 0 && (
                      <div style={{ display: 'grid', gap: 6, paddingTop: 4 }}>
                        <span className="pill pill--partial" style={{ width: 'fit-content' }}>
                          <Icon name="clock" />
                          {t('planPacingBadge')}
                        </span>
                        {item.milestones.map((m, mi) => (
                          <div
                            key={mi}
                            style={{
                              display: 'flex',
                              flexWrap: 'wrap',
                              justifyContent: 'space-between',
                              gap: 6,
                              padding: '6px 10px',
                              borderRadius: 'var(--radius-sm)',
                              background: 'var(--surface-2, rgba(255,255,255,0.04))',
                            }}
                          >
                            <span style={{ fontSize: '0.88rem' }}>
                              {lang === 'en' ? m.label_en : m.label_ar}
                            </span>
                            <span className="pill pill--neutral num">{m.due_date}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Ranked Grants Checklist Cards */}
          <div style={{ display: 'grid', gap: 14 }}>
            {plan.items.map((item) => (
              <Glass key={item.id} className="grant-card">
                <div className="grant-card__head">
                  <div>
                    <h3 className="grant-card__title" style={{ margin: 0 }}>
                      #{item.priority_rank} — {item.title}
                    </h3>
                    <span className="subtle num" style={{ fontSize: '0.86rem' }}>
                      {t('matchScoreLabel')}: {item.match_percentage}%
                    </span>
                  </div>
                  {renderCountdownPill(item)}
                </div>

                {!item.eligible && (
                  <div className="quote-box" style={{ marginBlock: 8 }}>
                    <div className="cluster" style={{ gap: 8 }}>
                      <span className="pill pill--unpaid">
                        <Icon name="alert" />
                        {t('ineligibleBadge')}
                      </span>
                      <span style={{ fontSize: '0.88rem' }}>
                        {lang === 'en' ? item.ineligible_warning_en : item.ineligible_warning_ar}
                      </span>
                    </div>
                  </div>
                )}

                <div style={{ display: 'grid', gap: 6 }}>
                  <div className="cluster" style={{ justifyContent: 'space-between', fontSize: '0.88rem' }}>
                    <span>{t('planOverallProgress')}</span>
                    <strong className="num">{item.progress_percentage}%</strong>
                  </div>
                  <ProgressBar value={item.progress_percentage} max={100} />
                </div>

                <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
                  <strong>{t('planChecklistTitle')}</strong>
                  {item.checklist.map((chk) => (
                    <div
                      key={chk.id}
                      className="quote-box"
                      style={{ display: 'grid', gap: 6 }}
                    >
                      <div className="cluster" style={{ justifyContent: 'space-between' }}>
                        <span style={{ fontSize: '0.92rem', fontWeight: 500 }}>
                          {lang === 'en' ? chk.label_en : chk.label_ar}
                        </span>
                        {chk.is_not_stated_officially ? (
                          <span className="pill pill--partial">{t('planNotStatedBadge')}</span>
                        ) : (
                          <Select
                            aria-label={lang === 'en' ? chk.label_en : chk.label_ar}
                            value={chk.status}
                            onChange={(e) =>
                              void handleChecklistStatus(
                                item,
                                chk.id,
                                e.target.value as ChecklistStatusLiteral,
                              )
                            }
                            style={{ width: 'auto', minWidth: 112 }}
                          >
                            <option value="todo">{t('planItemStatusTodo')}</option>
                            <option value="in_progress">{t('planItemStatusProgress')}</option>
                            <option value="done">{t('planItemStatusDone')}</option>
                          </Select>
                        )}
                      </div>
                      {(chk.detail_ar || chk.detail_en) && (
                        <p className="muted" style={{ margin: 0, fontSize: '0.84rem' }}>
                          {lang === 'en' ? chk.detail_en : chk.detail_ar}
                        </p>
                      )}
                      {chk.evidence_quote && (
                        <p className="subtle" style={{ margin: 0, fontSize: '0.82rem' }}>
                          “{chk.evidence_quote}”
                        </p>
                      )}
                      {chk.is_assumption && (
                        <span className="pill pill--late" style={{ width: 'fit-content' }}>
                          {t('strengthenAssumptionTag')}
                        </span>
                      )}
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
                  <Field label={t('planNotesLabel')}>
                    {(id) => (
                      <textarea
                        id={id}
                        className="input"
                        rows={2}
                        maxLength={2000}
                        value={notesDraft[item.id] ?? ''}
                        onChange={(e) =>
                          setNotesDraft((prev) => ({ ...prev, [item.id]: e.target.value }))
                        }
                        style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
                      />
                    )}
                  </Field>
                  <div className="cluster" style={{ justifyContent: 'space-between' }}>
                    <div className="cluster">
                      <Button
                        size="sm"
                        variant="glass"
                        icon="check"
                        onClick={() => void handleSaveNotes(item.id)}
                      >
                        {t('planSaveNotesBtn')}
                      </Button>
                      <a
                        className="btn btn--glass btn--sm"
                        href={safeHref(item.official_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t('officialPortal')}
                      </a>
                    </div>
                    <Button
                      size="sm"
                      variant="danger"
                      icon="trash"
                      onClick={() => void handleRemoveGrant(item.id)}
                    >
                      {t('planRemoveGrantBtn')}
                    </Button>
                  </div>
                </div>
              </Glass>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
