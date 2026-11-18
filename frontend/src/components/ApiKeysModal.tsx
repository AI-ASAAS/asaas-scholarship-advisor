import { Modal } from '../asaas-ui';
import type { SystemStatus } from '../lib/api';
import { useLang } from '../lib/i18n';
import { ApiKeysForm } from './ApiKeysForm';

interface ApiKeysModalProps {
  status: SystemStatus | null;
  onClose: () => void;
  onSaved: (updated: SystemStatus) => void;
}

export function ApiKeysModal({ status, onClose, onSaved }: ApiKeysModalProps) {
  const { t } = useLang();

  return (
    <Modal wide title={t('apiKeysTitle')} onClose={onClose}>
      <ApiKeysForm
        status={status}
        onSaved={(updated) => {
          onSaved(updated);
          onClose();
        }}
      />
    </Modal>
  );
}
