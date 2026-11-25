import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Skeleton } from './asaas-ui';
import { AdminGuard } from './components/AdminGuard';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Layout } from './components/Layout';

const Top10Page = lazy(() => import('./pages/Top10Page'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const MatchesPage = lazy(() => import('./pages/MatchesPage'));
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'));
const PlanPage = lazy(() => import('./pages/PlanPage'));
const NotificationsPage = lazy(() => import('./pages/NotificationsPage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const PrivacyPage = lazy(() => import('./pages/PrivacyPage'));
const TermsPage = lazy(() => import('./pages/TermsPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const MonitorPage = lazy(() => import('./pages/MonitorPage'));
const AdminLoginPage = lazy(() => import('./pages/AdminLoginPage'));

export default function App() {
  return (
    <ErrorBoundary>
      <Layout>
        <Suspense fallback={<Skeleton height={140} count={3} />}>
          <Routes>
            <Route path="/" element={<Top10Page />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/matches" element={<MatchesPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/plan" element={<PlanPage />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/login" element={<AdminLoginPage />} />
            <Route
              path="/admin"
              element={
                <AdminGuard>
                  <AdminPage />
                </AdminGuard>
              }
            />
            <Route
              path="/monitor"
              element={
                <AdminGuard>
                  <MonitorPage />
                </AdminGuard>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Layout>
    </ErrorBoundary>
  );
}
