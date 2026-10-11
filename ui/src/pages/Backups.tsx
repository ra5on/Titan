import { ManagementPanel } from '../management/Panel';
import { useApi } from '../lib';
import type { Share } from '../api';
import { SyncCard } from './Sync';

export function BackupsSection() {
  const shares = useApi<Share[]>('/api/managed-shares');
  const locations = useApi<{ items: { path: string; label: string; backup_eligible?: boolean; available: boolean }[] }>('/api/storage-locations');
  return <div className="space-y-4">
    <ManagementPanel feature="backups" />
    <SyncCard shares={shares.data || []} targets={(locations.data?.items || []).filter(item => item.available && item.backup_eligible)} />
  </div>;
}
