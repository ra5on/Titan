import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Pencil, Trash2, UsersRound } from 'lucide-react';
import { post, waitJob } from '../api';
import { message, useApi } from '../lib';
import { Button, Card, Field, IconButton, Input, Loading, Modal, Notice, Select, useToast } from '../ui';

type Rights = { applications?: Record<string, boolean>; shares?: Record<string, string> };
type Group = Rights & { name: string; description?: string; members: string[] };
type Policy = { schema: 1; groups: Group[]; users: Record<string, Rights> };
type Effective = Record<string, { applications: Record<string, { allowed: boolean; source: string; inherited: boolean }> }>;
type Identity = {
  policy: Policy;
  revision: string;
  applications: Record<string, string>;
  users: { name: string; role: string; enabled: boolean }[];
  effective: Effective;
};

type Choice = 'inherit' | 'allow' | 'deny';
const choiceOf = (value: boolean | undefined): Choice => (value === undefined ? 'inherit' : value ? 'allow' : 'deny');

function without<T extends Record<string, unknown>>(record: T, key: string) {
  const copy = { ...record };
  delete copy[key];
  return copy;
}

function GroupDialog({ group, identity, taken, onSave, onClose }: { group: Group | null; identity: Identity; taken: string[]; onSave: (group: Group) => void; onClose: () => void }) {
  const [name, setName] = useState(group?.name || '');
  const [members, setMembers] = useState<string[]>(group?.members || []);
  const [applications, setApplications] = useState<Record<string, boolean>>(group?.applications || {});
  const [error, setError] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!group && taken.includes(name)) return setError('Eine Gruppe mit diesem Namen gibt es schon.');
    onSave({ ...group, name, members, applications });
    onClose();
  };

  return (
    <Modal title={group ? `Gruppe „${group.name}“` : 'Neue Gruppe'} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name" help="Kleinbuchstaben, Ziffern, - und _; beginnt mit einem Buchstaben.">
          <Input value={name} onChange={event => setName(event.target.value)} disabled={Boolean(group)} required pattern="[a-z][a-z0-9_\-]{0,30}" autoCapitalize="none" spellCheck={false} />
        </Field>
        <fieldset>
          <legend className="mb-1 text-[13px] font-medium text-white/70">Mitglieder</legend>
          {identity.users.filter(user => user.role !== 'admin').map(user => (
            <label key={user.name} className="flex cursor-pointer items-center gap-3 py-1.5 text-sm">
              <input type="checkbox" className="size-4 accent-[var(--color-brand)]" checked={members.includes(user.name)} onChange={event => setMembers(event.target.checked ? [...members, user.name] : members.filter(item => item !== user.name))} />
              {user.name}
            </label>
          ))}
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-[13px] font-medium text-white/70">Rechte der Gruppe</legend>
          {Object.entries(identity.applications).map(([id, label]) => (
            <div key={id} className="flex items-center justify-between gap-3">
              <span className="text-sm">{label}</span>
              <Select
                aria-label={`${label} für die Gruppe`}
                className="h-9 w-40"
                value={choiceOf(applications[id])}
                onChange={event => setApplications(event.target.value === 'inherit' ? without(applications, id) : { ...applications, [id]: event.target.value === 'allow' })}
              >
                <option value="inherit">Nicht festgelegt</option>
                <option value="allow">Erlaubt</option>
                <option value="deny">Gesperrt</option>
              </Select>
            </div>
          ))}
        </fieldset>
        {error && <Notice>{error}</Notice>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary">Übernehmen</Button>
        </div>
      </form>
    </Modal>
  );
}

export function GroupsSection() {
  const toast = useToast();
  const identity = useApi<Identity>('/api/identity');
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [dialog, setDialog] = useState<{ group: Group | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const revision = identity.data?.revision;
  useEffect(() => {
    if (identity.data) setPolicy(identity.data.policy);
  }, [revision]); // eslint-disable-line react-hooks/exhaustive-deps

  if (identity.loading || !policy || !identity.data) return identity.error ? <Notice>{identity.error}</Notice> : <Loading />;
  const data = identity.data;
  const dirty = JSON.stringify(policy) !== JSON.stringify(data.policy);
  const people = data.users.filter(user => user.role !== 'admin');

  const userChoice = (user: string, application: string) => choiceOf(policy.users[user]?.applications?.[application]);
  const setUser = (user: string, application: string, choice: Choice) => {
    const current = policy.users[user]?.applications || {};
    const applications = choice === 'inherit' ? without(current, application) : { ...current, [application]: choice === 'allow' };
    setPolicy({ ...policy, users: { ...policy.users, [user]: { ...policy.users[user], applications } } });
  };

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      const { job } = await post<{ job: string }>('/api/identity', { ...policy, expected_revision: data.revision });
      await waitJob(job);
      toast('Gruppen und Rechte gespeichert.');
      await identity.reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-sm font-semibold">Was Benutzer verwenden dürfen</h2>
        <p className="mt-0.5 text-sm text-white/50">Administratoren dürfen immer alles. „Wie Gruppe“ übernimmt die Gruppenrechte oder den Standard.</p>
        {people.length === 0 ? (
          <p className="mt-3 text-sm text-white/55">Es gibt noch keine Benutzer ohne Administratorrechte.</p>
        ) : (
          <div className="scroll-area mt-3 overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <thead>
                <tr className="text-left text-xs text-white/45">
                  <th className="py-2 pr-3 font-medium">Benutzer</th>
                  {Object.values(data.applications).map(label => (
                    <th key={label} className="px-1.5 py-2 font-medium">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/6">
                {people.map(user => (
                  <tr key={user.name}>
                    <td className="py-2 pr-3 font-medium">{user.name}</td>
                    {Object.entries(data.applications).map(([id, label]) => {
                      const effective = data.effective[user.name]?.applications[id];
                      return (
                        <td key={id} className="px-1.5 py-2">
                          <Select aria-label={`${label} für ${user.name}`} className="h-9 min-w-28 px-2.5" value={userChoice(user.name, id)} onChange={event => setUser(user.name, id, event.target.value as Choice)}>
                            <option value="inherit">Wie Gruppe{effective?.inherited ? ` (${effective.allowed ? 'erlaubt' : 'gesperrt'})` : ''}</option>
                            <option value="allow">Erlaubt</option>
                            <option value="deny">Gesperrt</option>
                          </Select>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <UsersRound className="size-4 text-white/50" aria-hidden /> Gruppen
          </h2>
          <Button size="sm" onClick={() => setDialog({ group: null })}>Neue Gruppe</Button>
        </div>
        {policy.groups.length === 0 ? (
          <p className="mt-3 text-sm text-white/55">Noch keine Gruppe. Gruppen vergeben Rechte an mehrere Benutzer auf einmal.</p>
        ) : (
          <ul className="mt-2 divide-y divide-white/6">
            {policy.groups.map(group => (
              <li key={group.name} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{group.name}</div>
                  <div className="truncate text-xs text-white/45">{group.members.length ? group.members.join(', ') : 'Keine Mitglieder'}</div>
                </div>
                <IconButton label={`Gruppe ${group.name} bearbeiten`} onClick={() => setDialog({ group })}>
                  <Pencil className="size-4" />
                </IconButton>
                <IconButton label={`Gruppe ${group.name} löschen`} onClick={() => setPolicy({ ...policy, groups: policy.groups.filter(item => item.name !== group.name) })}>
                  <Trash2 className="size-4" />
                </IconButton>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {error && <Notice>{error}</Notice>}
      <div className="flex gap-2">
        <Button variant="primary" busy={busy} disabled={!dirty} onClick={save}>Änderungen speichern</Button>
        {dirty && <Button variant="ghost" disabled={busy} onClick={() => setPolicy(data.policy)}>Verwerfen</Button>}
      </div>

      {dialog && (
        <GroupDialog
          group={dialog.group}
          identity={data}
          taken={policy.groups.map(group => group.name)}
          onClose={() => setDialog(null)}
          onSave={group => setPolicy({ ...policy, groups: dialog.group ? policy.groups.map(item => (item.name === group.name ? group : item)) : [...policy.groups, group] })}
        />
      )}
    </div>
  );
}
