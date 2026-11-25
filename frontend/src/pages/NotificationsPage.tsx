import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Glass,
  Skeleton,
  Swash,
  formatDate,
  useToast,
} from '../asaas-ui';
import {
  api,
  safeHref,
  type NotificationItem,
  type NotificationsListResponse,
} from '../lib/api';
import { useLang } from '../lib/i18n';

export default function NotificationsPage() {
  const { t } = useLang();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [data, setData] = useState<NotificationsListResponse | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const [savingPref, setSavingPref] = useState(false);

  const loadNotifications = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getNotifications();
      setData(res);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadNotifications();
  }, [loadNotifications]);

  function notifyHeaderBadge() {
    window.dispatchEvent(new Event('asaas-notifications-updated'));
  }

  async function handleMarkRead(item: NotificationItem) {
    if (item.is_read) return;
    setBusyId(item.id);
    try {
      await api.markNotificationRead(item.id);
      setData((prev) =>
        prev
          ? {
              ...prev,
              unread_count: Math.max(0, prev.unread_count - 1),
              notifications: prev.notifications.map((n) =>
                n.id === item.id ? { ...n, is_read: true } : n,
              ),
            }
          : prev,
      );
      notifyHeaderBadge();
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setBusyId(null);
    }
  }

  async function handleMarkAllRead() {
    setMarkingAll(true);
    try {
      await api.markAllNotificationsRead();
      setData((prev) =>
        prev
          ? {
              ...prev,
              unread_count: 0,
              notifications: prev.notifications.map((n) => ({ ...n, is_read: true })),
            }
          : prev,
      );
      notifyHeaderBadge();
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setMarkingAll(false);
    }
  }

  async function handleToggleOptIn(nextValue: boolean) {
    setSavingPref(true);
    try {
      const res = await api.setHighMatchPreference(nextValue);
      setData((prev) =>
        prev ? { ...prev, high_match_alerts_enabled: res.high_match_alerts } : prev,
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setSavingPref(false);
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('notifPageTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('notifPageSubtitle')}
          </p>
        </div>
        {data && data.unread_count > 0 && (
          <Button
            variant="glass"
            icon="check"
            loading={markingAll}
            onClick={() => void handleMarkAllRead()}
          >
            {t('notifMarkAllReadBtn')}
          </Button>
        )}
      </div>

      {data && (
        <Card>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              cursor: savingPref ? 'wait' : 'pointer',
              fontSize: '0.94rem',
            }}
          >
            <input
              type="checkbox"
              checked={data.high_match_alerts_enabled}
              disabled={savingPref}
              onChange={(e) => void handleToggleOptIn(e.target.checked)}
            />
            <span>{t('notifOptInLabel')}</span>
          </label>
        </Card>
      )}

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Skeleton height={64} count={2} />
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={() => void loadNotifications()} />
      ) : !data || data.notifications.length === 0 ? (
        <EmptyState icon="alert" title={t('notifEmptyTitle')}>
          {t('notifEmptyBody')}
        </EmptyState>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {data.notifications.map((item) => (
            <Glass key={item.id} className="grant-card">
              <div className="grant-card__head">
                <div className="cluster" style={{ gap: 8 }}>
                  <h3 className="grant-card__title" style={{ margin: 0 }}>
                    {item.title}
                  </h3>
                  {!item.is_read && <span className="pill pill--partial">{t('notifUnreadBadge')}</span>}
                </div>
                <span className="subtle num">{formatDate(item.created_at)}</span>
              </div>

              <p style={{ margin: '8px 0 0', color: 'var(--text-2)', lineHeight: 1.6 }}>{item.body}</p>

              <div className="cluster" style={{ marginTop: 12 }}>
                {item.official_url && (
                  <a
                    className="btn btn--primary btn--sm"
                    href={safeHref(item.official_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t('officialPortal')}
                  </a>
                )}
                {!item.is_read && (
                  <Button
                    size="sm"
                    variant="glass"
                    icon="check"
                    loading={busyId === item.id}
                    onClick={() => void handleMarkRead(item)}
                  >
                    {t('notifMarkReadBtn')}
                  </Button>
                )}
              </div>
            </Glass>
          ))}
        </div>
      )}
    </div>
  );
}
