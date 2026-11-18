import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Skeleton } from './asaas-ui';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Layout } from './components/Layout';

const Top10Page = lazy(() => import('./pages/Top10Page'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const MonitorPage = lazy(() => import('./pages/MonitorPage'));

export default function App() {
  return (
    <ErrorBoundary>
      <Layout>
        <Suspense fallback={<Skeleton height={140} count={3} />}>
          <Routes>
            <Route path="/" element={<Top10Page />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/monitor" element={<MonitorPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Layout>
    </ErrorBoundary>
  );
}
