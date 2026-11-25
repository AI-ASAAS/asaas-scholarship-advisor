import { useState, type FormEvent } from 'react';
import {
  Button,
  Field,
  FormError,
  Select,
  TextArea,
  TextInput,
  useToast,
} from '../asaas-ui';
import {
  api,
  type Grant,
  type ManualGrantCreatePayload,
  type ManualGrantUpdatePayload,
} from '../lib/api';
import { useLang } from '../lib/i18n';

interface ManualGrantFormProps {
  mode: 'create' | 'edit';
  initialGrant?: Grant | null;
  submitLabel?: string;
  onSaved: (grant: Grant) => Promise<void> | void;
  onCancel?: () => void;
}

const DEGREE_CHOICES = ['high_school', 'bachelor', 'master', 'phd'] as const;

function splitLines(raw: string): string[] {
  return raw
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean);
}

function splitComma(raw: string): string[] {
  return raw
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
}

export function ManualGrantForm({ mode, initialGrant, submitLabel, onSaved, onCancel }: ManualGrantFormProps) {
  const { t } = useLang();
  const toast = useToast();

  const [title, setTitle] = useState(initialGrant?.title || '');
  const [officialUrl, setOfficialUrl] = useState(initialGrant?.official_url || '');
  const [providerName, setProviderName] = useState(initialGrant?.provider_name || '');
  const [hostCountry, setHostCountry] = useState(initialGrant?.host_country || '');
  const [deadline, setDeadline] = useState(initialGrant?.deadline || '');
  const [acceptsYemeni, setAcceptsYemeni] = useState<'yes' | 'no' | 'unclear'>(
    initialGrant?.accepts_yemeni || 'yes',
  );
  const [fundingType, setFundingType] = useState(initialGrant?.funding_type || 'full');
  const [funding, setFunding] = useState(initialGrant?.funding || '');
  const [allowedDegrees, setAllowedDegrees] = useState<string[]>(
    initialGrant ? (initialGrant.allowed_degrees || []) : ['master'],
  );
  const [minGpaValue, setMinGpaValue] = useState(
    initialGrant?.min_gpa_value != null ? String(initialGrant.min_gpa_value) : '',
  );
  const [minGpaScale, setMinGpaScale] = useState<'4.0' | '5.0' | '100' | 'label'>(
    (initialGrant?.min_gpa_scale as '4.0' | '5.0' | '100' | 'label') || '4.0',
  );
  const [fieldsText, setFieldsText] = useState((initialGrant?.fields_of_study || []).join(', '));
  const [eligibilityText, setEligibilityText] = useState(
    (initialGrant?.eligibility || []).join('\n'),
  );
  const [criteriaText, setCriteriaText] = useState((initialGrant?.criteria || []).join('\n'));
  const [docsText, setDocsText] = useState((initialGrant?.required_documents || []).join('\n'));
  const [howToApply, setHowToApply] = useState(initialGrant?.how_to_apply || '');
  const [description, setDescription] = useState(initialGrant?.description || '');
  const [featuredRank, setFeaturedRank] = useState(
    initialGrant?.featured_rank != null ? String(initialGrant.featured_rank) : '',
  );
  const [publishNow, setPublishNow] = useState(true);
  const [statusVal, setStatusVal] = useState<'draft' | 'published' | 'expired'>(
    initialGrant?.status || 'draft',
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function toggleDegree(deg: string) {
    setAllowedDegrees((prev) =>
      prev.includes(deg) ? prev.filter((item) => item !== deg) : [...prev, deg],
    );
  }

  function degreeLabel(deg: string): string {
    if (deg === 'high_school') return t('degreeHighSchool');
    if (deg === 'bachelor') return t('degreeBachelor');
    if (deg === 'master') return t('degreeMaster');
    return t('degreePhd');
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const parsedGpa = minGpaValue.trim() ? Number(minGpaValue.trim()) : null;
      const commonFields = {
        title: title.trim(),
        official_url: officialUrl.trim(),
        provider_name: providerName.trim() || null,
        host_country: hostCountry.trim() || null,
        deadline: deadline.trim() || null,
        accepts_yemeni: acceptsYemeni,
        funding_type: fundingType || null,
        funding: funding.trim() || null,
        allowed_degrees: allowedDegrees.length ? allowedDegrees : null,
        min_gpa_value: parsedGpa !== null && !Number.isNaN(parsedGpa) ? parsedGpa : null,
        min_gpa_scale: parsedGpa !== null && !Number.isNaN(parsedGpa) ? minGpaScale : null,
        fields_of_study: splitComma(fieldsText),
        eligibility: splitLines(eligibilityText),
        criteria: splitLines(criteriaText),
        required_documents: splitLines(docsText),
        how_to_apply: howToApply.trim() || null,
        description: description.trim() || null,
        featured_rank: featuredRank ? Number(featuredRank) : null,
        ...(initialGrant?.evidence && Object.keys(initialGrant.evidence).length
          ? { evidence: initialGrant.evidence }
          : {}),
      };

      let saved: Grant;
      if (mode === 'create') {
        const createPayload: ManualGrantCreatePayload = {
          ...commonFields,
          publish_immediately: publishNow,
        };
        saved = await api.createManualGrant(createPayload);
        toast(t('manualGrantCreatedToast'));
      } else if (initialGrant) {
        const updatePayload: ManualGrantUpdatePayload = {
          ...commonFields,
          status: statusVal,
        };
        saved = await api.updateGrant(initialGrant.id, updatePayload);
        toast(t('manualGrantUpdatedToast'));
      } else {
        return;
      }

      if (mode === 'create') {
        setTitle('');
        setOfficialUrl('');
        setProviderName('');
        setHostCountry('');
        setDeadline('');
        setFunding('');
        setFieldsText('');
        setEligibilityText('');
        setCriteriaText('');
        setDocsText('');
        setHowToApply('');
        setDescription('');
        setFeaturedRank('');
        setMinGpaValue('');
      }
      await onSaved(saved);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form" onSubmit={(e) => void handleSubmit(e)}>
      <div className="form__row">
        <Field label={t('manualGrantTitleLabel')}>
          {(id) => (
            <TextInput
              id={id}
              required
              minLength={3}
              maxLength={300}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('manualGrantTitlePh')}
            />
          )}
        </Field>

        <Field label={t('fieldOfficialUrl')}>
          {(id) => (
            <TextInput
              id={id}
              type="url"
              required
              dir="ltr"
              value={officialUrl}
              onChange={(e) => setOfficialUrl(e.target.value)}
              placeholder="https://example.edu/scholarship"
            />
          )}
        </Field>
      </div>

      <div className="form__row">
        <Field label={t('manualGrantProviderLabel')}>
          {(id) => (
            <TextInput
              id={id}
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              placeholder="DAAD / Chevening / University"
            />
          )}
        </Field>

        <Field label={t('hostCountryLabel')}>
          {(id) => (
            <TextInput
              id={id}
              value={hostCountry}
              onChange={(e) => setHostCountry(e.target.value)}
              placeholder="DE / GB / TR / Hungary"
            />
          )}
        </Field>

        <Field label={t('deadlineLabel')} hint={t('manualGrantDeadlineHint')}>
          {(id) => (
            <TextInput
              id={id}
              type="date"
              dir="ltr"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
            />
          )}
        </Field>
      </div>

      <div className="form__row">
        <Field label={t('manualGrantYemenLabel')}>
          {(id) => (
            <Select
              id={id}
              value={acceptsYemeni}
              onChange={(e) => setAcceptsYemeni(e.target.value as 'yes' | 'no' | 'unclear')}
            >
              <option value="yes">{t('yemenYes')}</option>
              <option value="no">{t('yemenNo')}</option>
              <option value="unclear">{t('yemenUnclear')}</option>
            </Select>
          )}
        </Field>

        <Field label={t('fundingTypeLabel')}>
          {(id) => (
            <Select id={id} value={fundingType} onChange={(e) => setFundingType(e.target.value)}>
              <option value="full">{t('fundingFull')}</option>
              <option value="partial">{t('fundingPartial')}</option>
              <option value="tuition">Tuition Waiver</option>
              <option value="stipend">Monthly Stipend</option>
              <option value="unknown">—</option>
            </Select>
          )}
        </Field>

        <Field label={t('featuredRankLabel')}>
          {(id) => (
            <Select id={id} value={featuredRank} onChange={(e) => setFeaturedRank(e.target.value)}>
              <option value="">{t('featuredAuto')}</option>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((rank) => (
                <option key={rank} value={String(rank)}>
                  #{rank}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      <div className="form__row">
        <Field label={t('minGpaLabel')}>
          {(id) => (
            <TextInput
              id={id}
              type="number"
              step="0.01"
              min={0}
              max={100}
              value={minGpaValue}
              onChange={(e) => setMinGpaValue(e.target.value)}
              placeholder="3.0"
            />
          )}
        </Field>

        <Field label={t('gpaScaleLabel')}>
          {(id) => (
            <Select
              id={id}
              value={minGpaScale}
              onChange={(e) => setMinGpaScale(e.target.value as '4.0' | '5.0' | '100' | 'label')}
            >
              <option value="4.0">4.0</option>
              <option value="5.0">5.0</option>
              <option value="100">100%</option>
            </Select>
          )}
        </Field>

        <Field label={t('modalFields')}>
          {(id) => (
            <TextInput
              id={id}
              value={fieldsText}
              onChange={(e) => setFieldsText(e.target.value)}
              placeholder="Computer Science, Engineering, Public Policy"
            />
          )}
        </Field>
      </div>

      <Field label={t('degreesLabel')}>
        {() => (
          <div className="cluster">
            {DEGREE_CHOICES.map((deg) => {
              const checked = allowedDegrees.includes(deg);
              return (
                <button
                  key={deg}
                  type="button"
                  className={checked ? 'pill pill--paid' : 'pill pill--neutral'}
                  style={{ cursor: 'pointer', border: 0 }}
                  onClick={() => toggleDegree(deg)}
                >
                  {checked ? '✓ ' : ''}
                  {degreeLabel(deg)}
                </button>
              );
            })}
          </div>
        )}
      </Field>

      <Field label={t('modalDescription')}>
        {(id) => (
          <TextArea
            id={id}
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('manualGrantDescPh')}
          />
        )}
      </Field>

      <div className="form__row">
        <Field label={t('modalFunding')}>
          {(id) => (
            <TextInput
              id={id}
              value={funding}
              onChange={(e) => setFunding(e.target.value)}
              placeholder={t('manualGrantFundingPh')}
            />
          )}
        </Field>

        <Field label={t('modalHowToApply')}>
          {(id) => (
            <TextInput
              id={id}
              value={howToApply}
              onChange={(e) => setHowToApply(e.target.value)}
              placeholder={t('manualGrantHowToPh')}
            />
          )}
        </Field>
      </div>

      <div className="form__row">
        <Field label={t('modalEligibility')} hint={t('manualGrantOnePerLine')}>
          {(id) => (
            <TextArea
              id={id}
              rows={3}
              value={eligibilityText}
              onChange={(e) => setEligibilityText(e.target.value)}
              placeholder={t('manualGrantEligPh')}
            />
          )}
        </Field>

        <Field label={t('modalDocuments')} hint={t('manualGrantOnePerLine')}>
          {(id) => (
            <TextArea
              id={id}
              rows={3}
              value={docsText}
              onChange={(e) => setDocsText(e.target.value)}
              placeholder="CV&#10;Motivation Letter&#10;Official Transcript"
            />
          )}
        </Field>
      </div>

      <Field label={t('manualGrantCriteriaLabel')} hint={t('manualGrantOnePerLine')}>
        {(id) => (
          <TextArea
            id={id}
            rows={2}
            value={criteriaText}
            onChange={(e) => setCriteriaText(e.target.value)}
            placeholder={t('manualGrantCriteriaPh')}
          />
        )}
      </Field>

      {mode === 'create' ? (
        <label className="cluster" style={{ cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={publishNow}
            onChange={(e) => setPublishNow(e.target.checked)}
          />
          <span>{t('manualGrantPublishNowLabel')}</span>
        </label>
      ) : (
        <Field label={t('colStatus')}>
          {(id) => (
            <Select
              id={id}
              value={statusVal}
              onChange={(e) => setStatusVal(e.target.value as 'draft' | 'published' | 'expired')}
            >
              <option value="draft">{t('statusDraft')}</option>
              <option value="published">{t('statusPublished')}</option>
              <option value="expired">{t('statusExpired')}</option>
            </Select>
          )}
        </Field>
      )}

      <FormError error={error} />

      <div className="cluster">
        <Button type="submit" variant="primary" icon="checkCircle" loading={saving}>
          {submitLabel || (mode === 'create' ? t('btnCreateManualGrant') : t('btnSaveGrantEdits'))}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t('btnCancelAddLanguage')}
          </Button>
        )}
      </div>
    </form>
  );
}
