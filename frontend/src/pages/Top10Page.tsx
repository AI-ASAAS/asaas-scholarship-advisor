import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Glass,
  Icon,
  Skeleton,
  Stat,
  Swash,
  TextInput,
  formatDate,
} from '../asaas-ui';
import { GrantModal } from '../components/GrantModal';
import { api, safeHref, type Grant, type SystemStatus } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLang } from '../lib/i18n';

function computeDaysLeft(deadline: string | null): number | null {
  if (!deadline) return null;
  const target = new Date(`${deadline}T00:00:00`);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const diff = Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  return Number.isNaN(diff) ? null : diff;
}

export default function Top10Page() {
  const { t } = useLang();
  const { authenticated } = useAuth();
  const [grants, setGrants] = useState<Grant[]>([]);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Grant | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const top10 = await api.getTop10();
      setGrants(top10);
      if (authenticated) {
        const status = await api.getSystemStatus().catch(() => null);
        setSysStatus(status);
      } else {
        setSysStatus(null);
      }
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [authenticated]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return grants;
    return grants.filter((g) => {
      const haystack = [
        g.title,
        g.description || '',
        g.funding || '',
        ...(g.fields_of_study || []),
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [grants, query]);

  const yemenCount = useMemo(
    () => grants.filter((g) => g.accepts_yemeni === 'yes').length,
    [grants],
  );

  const totalVerifiedQuotes = useMemo(
    () =>
      grants.reduce(
        (acc, g) =>
          acc + Object.values(g.field_verification || {}).filter((v) => v === 'verified').length,
        0,
      ),
    [grants],
  );

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('top10Title')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('top10Subtitle')}
          </p>
        </div>
        <Button variant="glass" icon="sparkle" onClick={() => void loadData()} loading={loading}>
          {t('navTop10')}
        </Button>
      </div>

      <Card className="advisor-cta-card">
        <div className="advisor-cta">
          <div className="advisor-cta__copy">
            <strong>{t('ctaProfileTitle')}</strong>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              {t('ctaProfileBody')}
            </p>
          </div>
          <div className="cluster">
            <Link to="/profile" className="btn btn--primary">
              <Icon name="users" />
              {t('ctaBuildProfileBtn')}
            </Link>
            <Link to="/matches" className="btn btn--glass">
              <Icon name="trend" />
              {t('ctaViewMatchesBtn')}
            </Link>
          </div>
        </div>
      </Card>

      {sysStatus ? (
        <div className="grid grid--stats grid--stats--4">
          <Stat
            label={t('statPublished')}
            icon="checkCircle"
            amount={sysStatus.counts.published}
            unit={t('unitGrant')}
          />
          <Stat
            label={t('statYemenReady')}
            icon="sparkle"
            amount={yemenCount}
            unit={t('unitGrant')}
          />
          <Stat
            label={t('statDrafts')}
            icon="file"
            amount={sysStatus.counts.draft}
            unit={t('unitGrant')}
          />
          <Stat
            label={t('statLogs')}
            icon="clock"
            amount={sysStatus.counts.update_logs}
            unit={t('unitLog')}
          />
        </div>
      ) : (
        grants.length > 0 && (
          <div className="grid grid--stats">
            <Stat
              label={t('statPublished')}
              icon="checkCircle"
              amount={grants.length}
              unit={t('unitGrant')}
            />
            <Stat
              label={t('statYemenReady')}
              icon="sparkle"
              amount={yemenCount}
              unit={t('unitGrant')}
            />
            <Stat
              label={t('statVerifiedQuotes')}
              icon="check"
              amount={totalVerifiedQuotes}
              unit={t('verifiedFields')}
            />
          </div>
        )
      )}

      <div className="search-box">
        <Icon name="search" size={17} className="search-box__icon" />
        <TextInput
          type="search"
          placeholder={t('filterPlaceholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t('filterPlaceholder')}
        />
      </div>

      {loading && <Skeleton height={160} count={3} />}
      {!loading && error ? <ErrorState error={error} onRetry={() => void loadData()} /> : null}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState icon="search" title={t('noGrantsTitle')}>
          {t('noGrantsBody')}
        </EmptyState>
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="grant-grid">
          {filtered.map((grant, idx) => {
            const days = computeDaysLeft(grant.deadline);
            const verifiedCount = Object.values(grant.field_verification || {}).filter(
              (v) => v === 'verified',
            ).length;

            return (
              <Glass key={grant.id} className="grant-card">
                <div className="grant-card__head">
                  <h2 className="grant-card__title">
                    <span className="grant-card__rank num">#{idx + 1}</span>
                    <span>{grant.title}</span>
                  </h2>
                </div>

                <div className="grant-meta">
                  {grant.featured_rank != null && (
                    <span className="pill pill--paid">
                      <Icon name="sparkle" />
                      {t('featuredBadge')} <span className="num">#{grant.featured_rank}</span>
                    </span>
                  )}
                  <span
                    className={
                      grant.accepts_yemeni === 'yes'
                        ? 'pill pill--paid'
                        : grant.accepts_yemeni === 'no'
                          ? 'pill pill--unpaid'
                          : 'pill pill--partial'
                    }
                  >
                    <Icon name={grant.accepts_yemeni === 'yes' ? 'checkCircle' : 'alert'} />
                    {grant.accepts_yemeni === 'yes'
                      ? t('yemenYes')
                      : grant.accepts_yemeni === 'no'
                        ? t('yemenNo')
                        : t('yemenUnclear')}
                  </span>
                  <span className="pill pill--neutral">
                    <Icon name="check" />
                    <span className="num">{verifiedCount}</span> {t('verifiedFields')}
                  </span>
                </div>

                {grant.description && <p className="grant-card__desc">{grant.description}</p>}

                {grant.funding && <div className="grant-card__funding">{grant.funding}</div>}

                <div className="grant-card__foot">
                  <div className="grant-deadline">
                    <Icon name="calendar" size={15} />
                    <span>{t('deadlineLabel')}:</span>
                    <strong className="num" style={{ color: 'var(--text)' }}>
                      {grant.deadline ? formatDate(grant.deadline) : t('rollingDeadline')}
                    </strong>
                    {days !== null && days >= 0 && (
                      <span>
                        (<span className="num">{days}</span> {t('daysLeft')})
                      </span>
                    )}
                  </div>

                  <div className="cluster">
                    <Button size="sm" variant="glass" onClick={() => setSelected(grant)}>
                      {t('viewDetails')}
                    </Button>
                    <a
                      className="btn btn--primary btn--sm"
                      href={safeHref(grant.official_url)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('officialPortal')}
                    </a>
                  </div>
                </div>
              </Glass>
            );
          })}
        </div>
      )}

      {selected && <GrantModal grant={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
