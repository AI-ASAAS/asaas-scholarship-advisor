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
            <h3>{t('modalDescription')}</h3>
            <p className="prose" style={{ margin: 0, color: 'var(--text-2)' }}>
              {grant.description}
            </p>
          </div>
        )}

        {(grant.host_country ||
          (grant.allowed_degrees && grant.allowed_degrees.length > 0) ||
          grant.min_gpa_value != null ||
          grant.min_work_years != null ||
          grant.max_age != null ||
          (grant.language_requirements && grant.language_requirements.length > 0) ||
          (grant.funding_type && grant.funding_type !== 'unknown') ||
          (grant.nationality_rule && grant.nationality_rule.mode !== 'unclear')) && (
          <div className="detail-section">
            <h3>{t('structuredConditionsTitle')}</h3>
            <div className="cluster">
              {grant.host_country && (
                <span className="pill pill--neutral">
                  {t('hostCountryLabel')}: <strong>{grant.host_country}</strong>
                </span>
              )}
              {grant.allowed_degrees && grant.allowed_degrees.length > 0 && (
                <span className="pill pill--neutral">
                  {t('degreesLabel')}: <strong>{grant.allowed_degrees.join(', ')}</strong>
                </span>
              )}
              {grant.min_gpa_value != null && (
                <span className="pill pill--neutral">
                  {t('minGpaLabel')}:{' '}
                  <strong className="num">
                    {grant.min_gpa_value} ({grant.min_gpa_scale || ''})
                  </strong>
                </span>
              )}
              {grant.min_work_years != null && (
                <span className="pill pill--neutral">
                  {t('workYearsLabel')}: <strong className="num">{grant.min_work_years}</strong>
                </span>
              )}
              {grant.max_age != null && (
                <span className="pill pill--neutral">
                  {t('maxAgeLabel')}: <strong className="num">{grant.max_age}</strong>
                </span>
              )}
              {grant.language_requirements && grant.language_requirements.length > 0 && (
                <span className="pill pill--neutral">
                  {t('languagesLabel')}:{' '}
                  <strong>
                    {grant.language_requirements
                      .map((l) => [l.language, l.test, l.min_score, l.cefr].filter(Boolean).join(' '))
                      .join(' · ')}
                  </strong>
                </span>
              )}
              {grant.funding_type && grant.funding_type !== 'unknown' && (
                <span className="pill pill--neutral">
                  {t('fundingTypeLabel')}: <strong>{grant.funding_type}</strong>
                </span>
              )}
              {grant.nationality_rule && grant.nationality_rule.mode !== 'unclear' && (
                <span className="pill pill--neutral">
                  {t('nationalityRuleLabel')}: <strong>{grant.nationality_rule.mode}</strong>
                </span>
              )}
            </div>
          </div>
        )}

        {grant.funding && (
          <div className="detail-section">
            <h3>{t('modalFunding')}</h3>
            <div className="grant-card__funding">{grant.funding}</div>
          </div>
        )}

        {grant.eligibility && grant.eligibility.length > 0 && (
          <div className="detail-section">
            <h3>{t('modalEligibility')}</h3>
            <ul className="detail-list">
              {grant.eligibility.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {grant.fields_of_study && grant.fields_of_study.length > 0 && (
          <div className="detail-section">
            <h3>{t('modalFields')}</h3>
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
            <h3>{t('modalDocuments')}</h3>
            <ul className="detail-list">
              {grant.required_documents.map((doc, i) => (
                <li key={i}>{doc}</li>
              ))}
            </ul>
          </div>
        )}

        {grant.how_to_apply && (
          <div className="detail-section">
            <h3>{t('modalHowToApply')}</h3>
            <p className="prose" style={{ margin: 0, color: 'var(--text-2)' }}>
              {grant.how_to_apply}
            </p>
          </div>
        )}

        {evidenceEntries.length > 0 && (
          <div className="detail-section">
            <h3>{t('modalEvidenceTitle')}</h3>
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
