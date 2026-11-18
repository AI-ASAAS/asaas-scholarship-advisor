import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Icon,
  Skeleton,
  Stat,
  Swash,
  useToast,
} from '../asaas-ui';
import { api, type MonitorSummary, type SystemStatus, type UpdateLogItem } from '../lib/api';
import { useLang } from '../lib/i18n';

export default function MonitorPage() {
  const { t } = useLang();
  const toast = useToast();

  const [logs, setLogs] = useState<UpdateLogItem[]>([]);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [lastSummary, setLastSummary] = useState<MonitorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [logRows, st] = await Promise.all([api.getMonitorLogs(), api.getSystemStatus()]);
      setLogs(logRows);
      setSysStatus(st);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  async function handleRunMonitor() {
    setRunning(true);
    try {
      const summary = await api.runMonitor();
      setLastSummary(summary);
      toast(
        `${t('monitorSuccess')} (${summary.total_published_checked} منحة | ${summary.content_modifications_found} تغيير)`,
      );
      await loadData();
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Monitor failed', 'error');
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('monitorTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('monitorSubtitle')}
          </p>
        </div>
        <Button variant="primary" icon="clock" loading={running} onClick={() => void handleRunMonitor()}>
          {t('btnRunMonitor')}
        </Button>
      </div>

      {lastSummary && (
        <div className="grid grid--stats">
          <Stat
            label={t('statPublished')}
            icon="checkCircle"
            amount={lastSummary.total_published_checked}
            unit={t('unitGrant')}
          />
          <Stat
            label="تغييرات مرصودة"
            icon="trend"
            amount={lastSummary.content_modifications_found}
            unit={t('unitLog')}
          />
          <Stat
            label="تنبيهات الإغلاق"
            icon="alert"
            amount={lastSummary.deadline_alerts_issued}
            unit={t('unitLog')}
            tone={lastSummary.deadline_alerts_issued > 0 ? 'negative' : 'default'}
          />
        </div>
      )}

      {sysStatus && (
        <Card title={t('readinessCardTitle')} icon="dashboard">
          <div className="list">
            <div className="row">
              <div className="row__main">
                <div className="row__title">LLM Extraction (`LLM_API_KEY`)</div>
                <div className="row__meta">Model: {sysStatus.llm_model}</div>
              </div>
              <span className={sysStatus.llm_configured ? 'pill pill--paid' : 'pill pill--partial'}>
                <Icon name={sysStatus.llm_configured ? 'checkCircle' : 'alert'} />
                {sysStatus.llm_configured ? t('readyYes') : t('readyNo')}
              </span>
            </div>

            <div className="row">
              <div className="row__main">
                <div className="row__title">ReAct Search (`TAVILY_API_KEY` / `SERPER_API_KEY`)</div>
                <div className="row__meta">
                  Provider: {sysStatus.search_provider ?? 'Not configured'}
                </div>
              </div>
              <span className={sysStatus.search_configured ? 'pill pill--paid' : 'pill pill--partial'}>
                <Icon name={sysStatus.search_configured ? 'checkCircle' : 'alert'} />
                {sysStatus.search_configured ? t('readyYes') : t('readyNo')}
              </span>
            </div>

            <div className="row">
              <div className="row__main">
                <div className="row__title">Telegram Watcher (`TELEGRAM_API_ID` / `HASH`)</div>
                <div className="row__meta">Telethon live channel reader</div>
              </div>
              <span className={sysStatus.telegram_configured ? 'pill pill--paid' : 'pill pill--partial'}>
                <Icon name={sysStatus.telegram_configured ? 'checkCircle' : 'alert'} />
                {sysStatus.telegram_configured ? t('readyYes') : t('readyNo')}
              </span>
            </div>
          </div>
        </Card>
      )}

      <Card title={t('logsCardTitle')} icon="list">
        {loading && <Skeleton height={56} count={4} />}
        {!loading && error ? <ErrorState error={error} onRetry={() => void loadData()} /> : null}

        {!loading && !error && logs.length === 0 && (
          <EmptyState icon="clock" title={t('noLogsTitle')}>
            {t('noLogsBody')}
          </EmptyState>
        )}

        {!loading && !error && logs.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('colGrant')}</th>
                  <th>{t('colField')}</th>
                  <th>{t('colOld')}</th>
                  <th>{t('colNew')}</th>
                  <th>{t('colDate')}</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.grant_title || `#${row.grant_id}`}</strong>
                    </td>
                    <td>
                      <span className="pill pill--neutral">{row.field_name}</span>
                    </td>
                    <td>
                      <span className="mono-truncate" title={row.old_value || ''}>
                        {row.old_value || '—'}
                      </span>
                    </td>
                    <td>
                      <span className="mono-truncate" title={row.new_value || ''}>
                        {row.new_value || '—'}
                      </span>
                    </td>
                    <td className="num subtle">
                      {row.detected_at ? row.detected_at.slice(0, 19).replace('T', ' ') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
