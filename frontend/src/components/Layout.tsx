import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { Button, Icon, SiteHeader, Swash, TabBar, useTheme } from '../asaas-ui';
import { useLang } from '../lib/i18n';

export function Layout({ children }: { children: ReactNode }) {
  const [theme, toggleTheme] = useTheme();
  const { t, toggleLang } = useLang();

  const brand = (
    <Link to="/" className="brand">
      <span className="brand__mark" aria-hidden="true" />
      <span>
        <span className="brand__name">
          <Swash>{t('brandName')}</Swash>
        </span>
        <span className="brand__tag hide-mobile">{t('brandTag')}</span>
      </span>
    </Link>
  );

  const nav = (
    <>
      <NavLink to="/" end>
        <Icon name="sparkle" />
        <span>{t('navTop10')}</span>
      </NavLink>
      <NavLink to="/search">
        <Icon name="search" />
        <span>{t('navSearch')}</span>
      </NavLink>
      <NavLink to="/admin">
        <Icon name="briefcase" />
        <span>{t('navAdmin')}</span>
      </NavLink>
      <NavLink to="/monitor">
        <Icon name="clock" />
        <span>{t('navMonitor')}</span>
      </NavLink>
    </>
  );

  const actions = (
    <>
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
      <SiteHeader brand={brand} nav={nav} actions={actions} />
      <main className="container" style={{ paddingBlock: '20px 36px' }}>
        {children}
      </main>
      <TabBar>
        <NavLink to="/" end>
          <Icon name="sparkle" />
          <span>{t('navTop10')}</span>
        </NavLink>
        <NavLink to="/search">
          <Icon name="search" />
          <span>{t('navSearch')}</span>
        </NavLink>
        <NavLink to="/admin">
          <Icon name="briefcase" />
          <span>{t('navAdmin')}</span>
        </NavLink>
        <NavLink to="/monitor">
          <Icon name="clock" />
          <span>{t('navMonitor')}</span>
        </NavLink>
      </TabBar>
    </>
  );
}
