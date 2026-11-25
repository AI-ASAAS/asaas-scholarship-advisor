import type { ReactNode } from 'react';
import { Skeleton } from '../asaas-ui';
import { useAuth } from '../lib/auth';
import AdminLoginPage from '../pages/AdminLoginPage';

export function AdminGuard({ children }: { children: ReactNode }) {
  const { authenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="page">
        <Skeleton height={140} count={3} />
      </div>
    );
  }

  if (!authenticated) {
    return <AdminLoginPage inline />;
  }

  return <>{children}</>;
}
