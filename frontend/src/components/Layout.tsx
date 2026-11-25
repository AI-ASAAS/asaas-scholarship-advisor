import { useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Button, Icon, SiteHeader, Swash, TabBar, useTheme } from '../asaas-ui';
import { AdvisorAssistant } from './AdvisorAssistant';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLang } from '../lib/i18n';

export function Layout({ children }: { children: ReactNode }) {
  const [theme, toggleTheme] = useTheme();
  const { t, toggleLang } = useLang();
  const { authenticated, logout } = useAuth();
  const location = useLocation();
  const [unreadCount, setUnreadCount] = useState(0);

  const isAdminArea =
    location.pathname.startsWith('/admin') ||
    location.pathname.startsWith('/monitor') ||
    location.pathname === '/login';

  useEffect(() => {
    if (isAdminArea) return;
    let cancelled = false;
    const refreshUnread = () => {
      void api
        .getUnreadNotificationCount()
        .then((res) => {
          if (!cancelled) setUnreadCount(res.unread_count || 0);
        })
        .catch(() => {
          if (!cancelled) setUnreadCount(0);
        });
    };
    refreshUnread();
    window.addEventListener('asaas-notifications-updated', refreshUnread);
    window.addEventListener('asaas-student-deleted', refreshUnread);
    return () => {
      cancelled = true;
      window.removeEventListener('asaas-notifications-updated', refreshUnread);
      window.removeEventListener('asaas-student-deleted', refreshUnread);
    };
  }, [isAdminArea]);

  const brand = (
    <Link to={isAdminArea ? '/admin' : '/'} className="brand">
      <span className="brand__mark" aria-hidden="true" />
      <span className="brand__text">
        <span className="brand__name">
          <Swash>{t('brandName')}</Swash>
        </span>{' '}
        <span className="brand__tag hide-mobile">{t('brandTag')}</span>
      </span>
    </Link>
  );

  const studentNav = (
    <>
      <NavLink to="/" end>
        <Icon name="sparkle" />
        <span>{t('navTop10')}</span>
      </NavLink>
      <NavLink to="/profile">
        <Icon name="users" />
        <span>{t('navProfile')}</span>
      </NavLink>
      <NavLink to="/matches">
        <Icon name="trend" />
        <span>{t('navMatches')}</span>
      </NavLink>
      <NavLink to="/documents">
        <Icon name="receipt" />
        <span>{t('navDocuments')}</span>
      </NavLink>
      <NavLink to="/plan">
        <Icon name="calendar" />
        <span>{t('navPlan')}</span>
      </NavLink>
      <NavLink to="/search">
        <Icon name="search" />
        <span>{t('navSearch')}</span>
      </NavLink>
    </>
  );

  const adminNav = authenticated ? (
    <>
      <NavLink to="/admin">
        <Icon name="briefcase" />
        <span>{t('navAdmin')}</span>
      </NavLink>
      <NavLink to="/monitor">
        <Icon name="clock" />
        <span>{t('navMonitor')}</span>
      </NavLink>
    </>
  ) : undefined;

  const activeNav = isAdminArea ? adminNav : studentNav;

  const actions = (
    <>
      {!isAdminArea && (
        <Link
          to="/notifications"
          className="btn btn--ghost btn--sm header-bell-btn"
          aria-label={
            unreadCount > 0 ? `${t('navNotifications')} (${unreadCount})` : t('navNotifications')
          }
        >
          <Icon name="alert" />
          {unreadCount > 0 && (
            <span className="header-bell-btn__badge num">{unreadCount > 99 ? '99+' : unreadCount}</span>
          )}
        </Link>
      )}
      {isAdminArea && authenticated && (
        <Button variant="ghost" size="sm" onClick={() => void logout()}>
          {t('btnLogout')}
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={toggleLang}>
        {t('langToggle')}
      </Button>
      <Button
        variant="ghost"
        size="sm"
        icon={theme === 'dark' ? 'sun' : 'moon'}
        label={t('themeToggle')}
        onClick={toggleTheme}
      />
    </>
  );

  return (
    <>
      <a className="skip-link" href="#main-content">
        {t('skipToContent')}
      </a>
      <SiteHeader brand={brand} nav={activeNav} actions={actions} />
      <main id="main-content" className="container" style={{ paddingBlock: '20px 36px' }}>
        {activeNav && (
          <nav className="body-nav" aria-label={t('brandName')}>
            {activeNav}
          </nav>
        )}
        {children}
      </main>
      <footer className="site-footer container">
        <div className="site-footer__inner">
          <span className="subtle">{t('footerNotice')}</span>
          <nav className="site-footer__links" aria-label={t('legalDraftBadge')}>
            <Link to="/privacy">{t('footerPrivacy')}</Link>
            <Link to="/terms">{t('footerTerms')}</Link>
          </nav>
        </div>
      </footer>
      {!isAdminArea && (
        <TabBar>
          <NavLink to="/" end>
            <Icon name="sparkle" />
            <span>{t('tabNavTop10')}</span>
          </NavLink>
          <NavLink to="/profile">
            <Icon name="users" />
            <span>{t('tabNavProfile')}</span>
          </NavLink>
          <NavLink to="/matches">
            <Icon name="trend" />
            <span>{t('tabNavMatches')}</span>
          </NavLink>
          <NavLink to="/documents">
            <Icon name="receipt" />
            <span>{t('tabNavDocuments')}</span>
          </NavLink>
          <NavLink to="/plan">
            <Icon name="calendar" />
            <span>{t('tabNavPlan')}</span>
          </NavLink>
        </TabBar>
      )}
      {isAdminArea && authenticated && (
        <TabBar>
          <NavLink to="/admin">
            <Icon name="briefcase" />
            <span>{t('tabNavAdmin')}</span>
          </NavLink>
          <NavLink to="/monitor">
            <Icon name="clock" />
            <span>{t('tabNavMonitor')}</span>
          </NavLink>
        </TabBar>
      )}
      {!isAdminArea && <AdvisorAssistant />}
    </>
  );
}
