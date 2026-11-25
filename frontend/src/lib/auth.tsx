import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, registerUnauthorizedHandler } from './api';

interface AuthContextValue {
  authenticated: boolean;
  loading: boolean;
  login: (secret: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getAdminSession();
      setAuthenticated(Boolean(res.authenticated));
    } catch {
      setAuthenticated(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      setAuthenticated(false);
      if (
        location.pathname !== '/login' &&
        !location.pathname.startsWith('/admin') &&
        !location.pathname.startsWith('/monitor')
      ) {
        const next = encodeURIComponent(location.pathname + location.search);
        navigate(`/login?next=${next}`, { replace: true });
      }
    });
    return () => registerUnauthorizedHandler(null);
  }, [navigate, location.pathname, location.search]);

  const login = useCallback(async (secret: string) => {
    const res = await api.adminLogin(secret);
    setAuthenticated(Boolean(res.authenticated));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.adminLogout();
    } finally {
      setAuthenticated(false);
      navigate('/', { replace: true });
    }
  }, [navigate]);

  return (
    <AuthContext.Provider value={{ authenticated, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
