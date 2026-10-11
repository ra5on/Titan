import { useState } from 'react';
import type { FormEvent } from 'react';
import { Pencil, UserPlus } from 'lucide-react';
import { post, waitJob } from '../api';
import type { Users } from '../api';
import { message, useApi } from '../lib';
import { Button, Card, Field, IconButton, Input, Loading, Modal, Notice, Select, useToast } from '../ui';

type WebUser = Users['web'][number];

/** Account changes run as background jobs; wait for the result before reporting success. */
async function job(path: string, body: Record<string, unknown>) {
  const { job: id } = await post<{ job: string }>(path, body);
  return waitJob(id);
}

function AddUser({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ name: '', password: '', role: 'user' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await job('/api/users', form);
      toast(`Benutzer „${form.name}“ angelegt.`);
      onDone();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  return (
    <Modal title="Benutzer anlegen" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Benutzername" help="Kleinbuchstaben, Ziffern, - und _; beginnt mit einem Buchstaben.">
          <Input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} autoCapitalize="none" spellCheck={false} required pattern="[a-z][a-z0-9_\-]{0,30}" />
        </Field>
        <Field label="Passwort">
          <Input type="password" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} autoComplete="new-password" required />
        </Field>
        <Field label="Rolle">
          <Select value={form.role} onChange={event => setForm({ ...form, role: event.target.value })}>
            <option value="user">Benutzer</option>
            <option value="admin">Administrator</option>
          </Select>
        </Field>
        {error && <Notice>{error}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" busy={busy}>Anlegen</Button>
        </div>
      </form>
    </Modal>
  );
}

function EditUser({ user, self, onClose, onDone }: { user: WebUser; self: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [role, setRole] = useState(user.role);
  const [enabled, setEnabled] = useState(user.enabled);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError('');
    try {
      await work();
      toast(done);
      onDone();
      onClose();
    } catch (reason) {
      setError(message(reason));
      setBusy(false);
    }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const changes: Record<string, unknown> = {};
    if (role !== user.role) changes.role = role;
    if (enabled !== user.enabled) changes.enabled = enabled;
    if (password) changes.password = password;
    if (!Object.keys(changes).length) return onClose();
    void run(() => job('/api/users/update', { name: user.name, ...changes }), `Benutzer „${user.name}“ geändert.`);
  };

  if (deleting) {
    return (
      <Modal title={`Benutzer „${user.name}“ löschen?`} onClose={onClose}>
        <form
          className="space-y-4"
          onSubmit={event => {
            event.preventDefault();
            void run(() => job('/api/users/remove', { name: user.name, confirmation }), `Benutzer „${user.name}“ gelöscht.`);
          }}
        >
          <p className="text-sm leading-relaxed text-white/70">Das Konto und seine Anmeldung werden entfernt. Das lässt sich nicht rückgängig machen. Dateien in Freigaben bleiben erhalten.</p>
          <Field label={`Zur Bestätigung „${user.name}“ eingeben`}>
            <Input value={confirmation} onChange={event => setConfirmation(event.target.value)} autoCapitalize="none" spellCheck={false} required />
          </Field>
          {error && <Notice>{error}</Notice>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeleting(false)}>Zurück</Button>
            <Button type="submit" variant="danger" busy={busy} disabled={confirmation !== user.name}>Endgültig löschen</Button>
          </div>
        </form>
      </Modal>
    );
  }

  return (
    <Modal title={`Benutzer „${user.name}“`} onClose={onClose}>
      <form onSubmit={save} className="space-y-4">
        <Field label="Rolle" help={self ? 'Die eigene Rolle kann nur ein anderer Administrator ändern.' : undefined}>
          <Select value={role} onChange={event => setRole(event.target.value)} disabled={self}>
            <option value="user">Benutzer</option>
            <option value="admin">Administrator</option>
          </Select>
        </Field>
        <Field label="Anmeldung" help={self ? 'Das eigene Konto kann nicht gesperrt werden.' : 'Ein gesperrtes Konto kann sich nicht anmelden; Daten und Rechte bleiben erhalten.'}>
          <Select value={enabled ? 'on' : 'off'} onChange={event => setEnabled(event.target.value === 'on')} disabled={self}>
            <option value="on">Erlaubt</option>
            <option value="off">Gesperrt</option>
          </Select>
        </Field>
        {!self && (
          <Field label="Neues Passwort (optional)" help="Leer lassen, um das Passwort nicht zu ändern.">
            <Input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="new-password" />
          </Field>
        )}
        {error && <Notice>{error}</Notice>}
        <div className="flex items-center justify-between gap-2">
          {self ? <span /> : <Button variant="danger" onClick={() => setDeleting(true)}>Löschen</Button>}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" busy={busy}>Speichern</Button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

export function UsersSection({ current }: { current: string }) {
  const users = useApi<Users>('/api/users');
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<WebUser | null>(null);

  if (users.loading) return <Loading />;
  if (users.error && !users.data) return <Notice>{users.error}</Notice>;
  return (
    <div className="space-y-4">
      <Card>
        <ul className="divide-y divide-white/6">
          {users.data!.web.map(user => (
            <li key={user.name} className="flex items-center gap-3 py-2.5">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-600 text-sm font-semibold uppercase">{user.name.slice(0, 1)}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {user.display_name || user.name}
                  {user.name === current && <span className="ml-2 text-xs font-normal text-white/40">Du</span>}
                </span>
                <span className="block text-xs text-white/45">
                  {user.role === 'admin' ? 'Administrator' : 'Benutzer'}
                  {!user.enabled && ' · gesperrt'}
                </span>
              </span>
              <IconButton label={`Benutzer ${user.name} bearbeiten`} onClick={() => setEditing(user)}>
                <Pencil className="size-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      </Card>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => setAdding(true)}>
          <UserPlus className="size-4" /> Benutzer anlegen
        </Button>
        <Button onClick={() => window.open('/classic#users', '_blank', 'noopener')}>Gruppen und App-Rechte</Button>
      </div>
      {adding && <AddUser onClose={() => setAdding(false)} onDone={users.reload} />}
      {editing && <EditUser user={editing} self={editing.name === current} onClose={() => setEditing(null)} onDone={users.reload} />}
    </div>
  );
}

export function AccountSection({ name, onChanged }: { name: string; onChanged: () => Promise<void> }) {
  const toast = useToast();
  const [form, setForm] = useState({ current: '', next: '', repeat: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (form.next !== form.repeat) return setError('Die beiden neuen Passwörter stimmen nicht überein.');
    setBusy(true);
    setError('');
    try {
      await job('/api/password', { current_password: form.current, password: form.next });
      toast('Passwort geändert.');
      setForm({ current: '', next: '', repeat: '' });
      // Other sessions of this account may have been signed out; re-read ours.
      await onChanged();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <h2 className="text-sm font-semibold">Passwort ändern</h2>
      <p className="mt-0.5 text-sm text-white/50">Konto: {name}</p>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <Field label="Aktuelles Passwort">
          <Input type="password" value={form.current} onChange={event => setForm({ ...form, current: event.target.value })} autoComplete="current-password" required />
        </Field>
        <Field label="Neues Passwort">
          <Input type="password" value={form.next} onChange={event => setForm({ ...form, next: event.target.value })} autoComplete="new-password" required />
        </Field>
        <Field label="Neues Passwort wiederholen">
          <Input type="password" value={form.repeat} onChange={event => setForm({ ...form, repeat: event.target.value })} autoComplete="new-password" required />
        </Field>
        {error && <Notice>{error}</Notice>}
        <Button type="submit" variant="primary" busy={busy}>Passwort ändern</Button>
      </form>
    </Card>
  );
}
