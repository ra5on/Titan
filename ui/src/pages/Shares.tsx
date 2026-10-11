import { useState } from 'react';
import type { FormEvent } from 'react';
import { FolderOpen, FolderPlus, KeyRound, Trash2 } from 'lucide-react';
import { action } from '../api';
import type { Share } from '../api';
import { bytes, go, message, useApi } from '../lib';
import { Button, Card, Confirm, Empty, Field, IconButton, Input, Loading, Modal, Notice, Select, useToast } from '../ui';

type Locations = { resources: { id: string; label: string; available: boolean; free_bytes: number }[]; default_storage: string };
type Accounts = { system: { name: string; enabled: boolean }[] };
type Access = { host_addresses: { address: string; scope: string }[]; service_active: boolean };
type Right = 'none' | 'read' | 'write';

const SERVICE_USER = 'titan-files';

function RightsList({ users, rights, onChange }: { users: { name: string }[]; rights: Record<string, Right>; onChange: (rights: Record<string, Right>) => void }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-[13px] font-medium text-white/70">Zugriff</legend>
      <ul className="divide-y divide-white/6 rounded-xl border border-white/10">
        {users.map(user => (
          <li key={user.name} className="flex items-center justify-between gap-3 px-3.5 py-2">
            <span className="truncate text-sm">{user.name}</span>
            <Select aria-label={'Zugriff für ' + user.name} className="h-9 w-44" value={rights[user.name] || 'none'} onChange={event => onChange({ ...rights, [user.name]: event.target.value as Right })}>
              <option value="none">Kein Zugriff</option>
              <option value="read">Nur lesen</option>
              <option value="write">Lesen und schreiben</option>
            </Select>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

const rightOf = (share: Share, user: string): Right => (share.writers.includes(user) ? 'write' : share.readers.includes(user) ? 'read' : 'none');

function EditRights({ share, onClose, onDone }: { share: Share; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const accounts = useApi<Accounts>('/api/users');
  const [rights, setRights] = useState<Record<string, Right>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const users = (accounts.data?.system || []).filter(user => user.name !== SERVICE_USER && (user.enabled || rightOf(share, user.name) !== 'none'));
  const value = (user: string) => rights[user] ?? rightOf(share, user);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const changed = users.filter(user => value(user.name) !== rightOf(share, user.name));
    if (!changed.length) return onClose();
    setBusy(true);
    setError('');
    try {
      // One user at a time: the agent patches a single identity per call.
      for (const user of changed) await action('share_user_permission', { name: share.name, user: user.name, permission: value(user.name) });
      toast('Zugriff auf „' + share.name + '“ geändert.');
      onDone();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
      onDone();
    }
  };

  return (
    <Modal title={'Zugriff auf „' + share.name + '“'} onClose={onClose}>
      {accounts.loading ? (
        <Loading />
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <RightsList users={users} rights={Object.fromEntries(users.map(user => [user.name, value(user.name)]))} onChange={setRights} />
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" busy={busy}>Speichern</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function CreateShare({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const locations = useApi<Locations>('/api/storage-locations');
  const accounts = useApi<Accounts>('/api/users');
  const [name, setName] = useState('');
  const [storage, setStorage] = useState('');
  const [rights, setRights] = useState<Record<string, Right>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const users = (accounts.data?.system || []).filter(user => user.enabled && user.name !== SERVICE_USER);
  const targets = (locations.data?.resources || []).filter(item => item.available);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const readers = users.filter(user => rights[user.name] === 'read').map(user => user.name);
    const writers = users.filter(user => (rights[user.name] || 'none') === 'write').map(user => user.name);
    if (!readers.length && !writers.length) return setError('Mindestens einem Benutzer Zugriff geben.');
    const target = storage || locations.data?.default_storage || 'system';
    setBusy(true);
    setError('');
    try {
      await action('share_create', { name, storage: target, volume: target.startsWith('volume:') ? target.slice(7) : null, readers, writers });
      toast(`Freigabe „${name}“ angelegt.`);
      onCreated();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Neue Freigabe" onClose={onClose}>
      {locations.loading || accounts.loading ? (
        <Loading />
      ) : !users.length ? (
        <Notice tone="info">Lege zuerst unter „Benutzer“ ein Konto an. Eine Freigabe braucht mindestens einen Benutzer mit Zugriff.</Notice>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="Name" help="Kleinbuchstaben, Ziffern, - und _; beginnt mit einem Buchstaben. Unter diesem Namen erscheint die Freigabe im Netzwerk.">
            <Input value={name} onChange={event => setName(event.target.value)} required pattern="[a-z][a-z0-9_\-]{0,30}" autoCapitalize="none" spellCheck={false} />
          </Field>
          <Field label="Speicherort">
            <Select value={storage || locations.data?.default_storage} onChange={event => setStorage(event.target.value)}>
              {targets.map(item => (
                <option key={item.id} value={item.id}>
                  {item.label} · {bytes(item.free_bytes)} frei
                </option>
              ))}
            </Select>
          </Field>
          <RightsList users={users} rights={rights} onChange={setRights} />
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" busy={busy}>Anlegen</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}

export function SharesSection() {
  const toast = useToast();
  const shares = useApi<Share[]>('/api/managed-shares');
  const access = useApi<Access>('/api/shares/access');
  const [creating, setCreating] = useState(false);
  const [removing, setRemoving] = useState<Share | null>(null);
  const [editing, setEditing] = useState<Share | null>(null);

  if (shares.loading) return <Loading />;
  if (shares.error && !shares.data) return <Notice>{shares.error}</Notice>;
  const address = access.data?.host_addresses.find(item => item.scope === 'lan')?.address;
  const people = (share: Share) => {
    const writers = share.writers.filter(user => user !== SERVICE_USER);
    const readers = share.readers.filter(user => user !== SERVICE_USER);
    return [writers.length && `Schreiben: ${writers.join(', ')}`, readers.length && `Lesen: ${readers.join(', ')}`].filter(Boolean).join(' · ') || 'Kein Benutzer';
  };

  return (
    <div className="space-y-4">
      {access.data && !access.data.service_active && <Notice tone="warn">Der Freigabedienst (SMB) läuft nicht. Freigaben sind im Netzwerk gerade nicht erreichbar.</Notice>}
      {shares.data!.length === 0 ? (
        <Card>
          <Empty title="Noch keine Freigabe">Eine Freigabe ist ein Ordner auf dem NAS, den du im Netzwerk und im Dateimanager nutzt.</Empty>
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-white/6">
            {shares.data!.map(share => (
              <li key={share.name} className="flex items-center gap-3 py-3">
                <FolderOpen className="size-5 shrink-0 text-amber-300" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{share.name}</div>
                  <div className="truncate text-xs text-white/45">{people(share)}</div>
                  {address && <div className="truncate font-mono text-xs text-white/35">\\{address}\{share.name}</div>}
                </div>
                <Button size="sm" variant="ghost" onClick={() => go('files')}>Öffnen</Button>
                <IconButton label={`Zugriff auf ${share.name} ändern`} onClick={() => setEditing(share)}>
                  <KeyRound className="size-4" />
                </IconButton>
                <IconButton label={`Freigabe ${share.name} entfernen`} onClick={() => setRemoving(share)}>
                  <Trash2 className="size-4" />
                </IconButton>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => setCreating(true)}>
          <FolderPlus className="size-4" /> Neue Freigabe
        </Button>
      </div>
      {editing && <EditRights share={editing} onClose={() => setEditing(null)} onDone={shares.reload} />}
      {creating && <CreateShare onClose={() => setCreating(false)} onCreated={shares.reload} />}
      {removing && (
        <Confirm
          title={`Freigabe „${removing.name}“ entfernen?`}
          text="Die Freigabe verschwindet aus dem Netzwerk und dem Dateimanager. Die Dateien im Ordner bleiben auf dem Datenträger erhalten."
          confirmLabel="Entfernen"
          danger
          onClose={() => setRemoving(null)}
          onConfirm={async () => {
            try {
              await action('share_remove', { name: removing.name });
              toast(`Freigabe „${removing.name}“ entfernt.`);
            } catch (reason) {
              toast(message(reason), true);
            }
            await shares.reload();
          }}
        />
      )}
    </div>
  );
}
