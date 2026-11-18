import { Button, Icon, Modal, formatDate } from '../asaas-ui';
import { type Grant, safeHref } from '../lib/api';
import { useLang } from '../lib/i18n';

interface GrantModalProps {
  grant: Grant;
  onClose: () => void;
  onPublish?: (grantId: number) => void;
  publishing?: boolean;
}

export function GrantModal({ grant, onClose, onPublish, publishing }: GrantModalProps) {
  const { t } = useLang();
  const evidenceEntries = Object.entries(grant.evidence || {});

  const yemenBadgeClass =
    grant.accepts_yemeni === 'yes'
      ? 'pill pill--paid'
      : grant.accepts_yemeni === 'no'
        ? 'pill pill--unpaid'
        : 'pill pill--partial';

  const yemenLabel =
    grant.accepts_yemeni === 'yes'
      ? t('yemenYes')
      : grant.accepts_yemeni === 'no'
        ? t('yemenNo')
        : t('yemenUnclear');

  const statusBadgeClass =
    grant.status === 'published'
      ? 'pill pill--paid'
      : grant.status === 'draft'
        ? 'pill pill--partial'
        : 'pill pill--unpaid';

  const statusLabel =
    grant.status === 'published'
      ? t('statusPublished')
      : grant.status === 'draft'
        ? t('statusDraft')
        : t('statusExpired');

  return (
    <Modal
      wide
      title={grant.title}
      onClose={onClose}
      footer={
        <div className="cluster" style={{ justifyContent: 'space-between', width: '100%' }}>
          <div className="cluster">
            <a
              className="btn btn--primary"
              href={safeHref(grant.official_url)}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Icon name="chevronLeft" />
              {t('officialPortal')}
            </a>
            {grant.status === 'draft' && onPublish && (
              <Button
                variant="glass"
                icon="checkCircle"
                loading={publishing}
                onClick={() => onPublish(grant.id)}
              >
                {t('btnPublish')}
              </Button>
            )}
          </div>
          <Button variant="ghost" onClick={onClose}>
            {t('modalClose')}
          </Button>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div className="grant-meta">
          <span className={statusBadgeClass}>{statusLabel}</span>
          <span className={yemenBadgeClass}>{yemenLabel}</span>
          <span className="pill pill--neutral">
            <Icon name="calendar" />
            <span>
              {t('deadlineLabel')}:{' '}
              <span className="num">{grant.deadline ? formatDate(grant.deadline) : t('rollingDeadline')}</span>
            </span>
          </span>
        </div>

        {grant.description && (
          <div className="detail-section">
            <h4>{t('modalDescription')}</h4>
            <p className="prose" style={{ margin: 0, color: 'var(--text-2)' }}>
              {grant.description}
            </p>
          </div>
        )}

        {grant.funding && (
          <div className="detail-section">
            <h4>{t('modalFunding')}</h4>
            <div className="grant-card__funding">{grant.funding}</div>
          </div>
        )}

        {grant.eligibility && grant.eligibility.length > 0 && (
          <div className="detail-section">
            <h4>{t('modalEligibility')}</h4>
            <ul className="detail-list">
              {grant.eligibility.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {grant.fields_of_study && grant.fields_of_study.length > 0 && (
          <div className="detail-section">
            <h4>{t('modalFields')}</h4>
            <div className="cluster">
              {grant.fields_of_study.map((f, i) => (
                <span key={i} className="pill pill--neutral">
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}

        {grant.required_documents && grant.required_documents.length > 0 && (
          <div className="detail-section">
            <h4>{t('modalDocuments')}</h4>
            <ul className="detail-list">
              {grant.required_documents.map((doc, i) => (
                <li key={i}>{doc}</li>
              ))}
            </ul>
          </div>
        )}

        {grant.how_to_apply && (
          <div className="detail-section">
            <h4>{t('modalHowToApply')}</h4>
            <p className="prose" style={{ margin: 0, color: 'var(--text-2)' }}>
              {grant.how_to_apply}
            </p>
          </div>
        )}

        {evidenceEntries.length > 0 && (
          <div className="detail-section">
            <h4>{t('modalEvidenceTitle')}</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {evidenceEntries.map(([field, quote]) => {
                const isVerified = grant.field_verification?.[field] === 'verified';
                return (
                  <div key={field} className="quote-box">
                    <div className="cluster" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                      <strong style={{ fontSize: '0.84rem', color: 'var(--text)' }}>{field}</strong>
                      <span className={isVerified ? 'pill pill--paid' : 'pill pill--unpaid'}>
                        <Icon name={isVerified ? 'checkCircle' : 'alert'} />
                        {isVerified ? t('modalVerified') : t('modalUnverified')}
                      </span>
                    </div>
                    <span>“{quote}”</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
