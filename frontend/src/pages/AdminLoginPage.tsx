import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, Card, Field, FormError, PasswordInput, Swash, useToast } from '../asaas-ui';
import { safeSameOriginNext } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLang } from '../lib/i18n';

export default function AdminLoginPage({ inline = false }: { inline?: boolean }) {
  const { t } = useLang();
  const { authenticated, loading, login } = useAuth();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [secret, setSecret] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const nextPath = safeSameOriginNext(searchParams.get('next'));

  if (!inline && !loading && authenticated) {
    return <Navigate to={nextPath} replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(secret);
      setSecret('');
      toast(t('loginSuccess'));
      if (!inline) {
        navigate(nextPath, { replace: true });
      }
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 480, marginInline: 'auto' }}>
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('loginTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('loginSubtitle')}
          </p>
        </div>
      </div>

      <Card title={t('loginCardTitle')} icon="vault">
        <form className="form" onSubmit={handleSubmit}>
          <Field label={t('loginSecretLabel')} hint={t('loginSecretHint')}>
            {(id) => (
              <PasswordInput
                id={id}
                required
                autoComplete="current-password"
                placeholder="••••••••••••"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
            )}
          </Field>

          <FormError error={error} />

          <div className="cluster">
            <Button type="submit" variant="primary" icon="checkCircle" loading={submitting}>
              {t('btnLogin')}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
