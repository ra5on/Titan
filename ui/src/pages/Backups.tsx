import { ManagementPanel } from '../management/Panel';
import { useApi } from '../lib';
import type { Session, Share } from '../api';
import { SyncCard } from './Sync';

export function BackupsSection({ session }: { session: Session }) {
  const admin = session.user?.role === 'admin';
  const shares = useApi<Share[]>(admin ? '/api/managed-shares' : null);
  const locations = useApi<{ items: { path: string; label: string; backup_eligible?: boolean; available: boolean }[] }>(admin ? '/api/storage-locations' : null);
  return <div className="space-y-4">
    <ManagementPanel feature="backups" session={session} />
    {admin && <SyncCard shares={shares.data || []} targets={(locations.data?.items || []).filter(item => item.available && item.backup_eligible)} />}
  </div>;
}
