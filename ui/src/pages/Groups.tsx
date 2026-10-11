import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Pencil, Trash2, UsersRound } from 'lucide-react';
import { post, waitJob } from '../api';
import { cx, message, useApi } from '../lib';
import { Button, Card, Field, IconButton, Input, Loading, Modal, Notice, useToast } from '../ui';

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

function Segmented({ label, value, inheritLabel, onChange }: { label: string; value: Choice; inheritLabel: string; onChange: (value: Choice) => void }) {
  const options: [Choice, string][] = [['inherit', inheritLabel], ['allow', 'Erlaubt'], ['deny', 'Gesperrt']];
  return (
    <div role="group" aria-label={label} className="inline-flex shrink-0 rounded-full bg-white/8 p-0.5">
      {options.map(([id, text]) => (
        <button
          key={id}
          type="button"
          aria-pressed={value === id}
          onClick={() => onChange(id)}
          className={cx(
            'h-8 rounded-full px-3 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-brand',
            value !== id && 'text-white/60 hover:text-white',
            value === id && id === 'allow' && 'bg-ok/25 font-medium text-ok',
            value === id && id === 'deny' && 'bg-bad/25 font-medium text-bad',
            value === id && id === 'inherit' && 'bg-white/16 font-medium text-white',
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
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
            <div key={id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm">{label}</span>
              <Segmented
                label={`${label} für die Gruppe`}
                inheritLabel="Offen"
                value={choiceOf(applications[id])}
                onChange={choice => setApplications(choice === 'inherit' ? without(applications, id) : { ...applications, [id]: choice === 'allow' })}
              />
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
        <p className="mt-0.5 text-sm text-white/50">Administratoren dürfen immer alles. „Wie Gruppe“ übernimmt die Rechte aus den Gruppen des Benutzers, sonst den Standard.</p>
        {people.length === 0 ? (
          <p className="mt-3 text-sm text-white/55">Es gibt noch keine Benutzer ohne Administratorrechte.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {people.map(user => (
              <li key={user.name} className="rounded-xl border border-white/8 p-3.5">
                <div className="mb-2 flex items-center gap-2.5">
                  <span className="flex size-7 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-600 text-xs font-semibold uppercase">{user.name.slice(0, 1)}</span>
                  <span className="text-sm font-semibold">{user.name}</span>
                </div>
                <div className="space-y-1.5">
                  {Object.entries(data.applications).map(([id, label]) => {
                    const effective = data.effective[user.name]?.applications[id];
                    const inherited = effective?.inherited ? (effective.allowed ? 'erlaubt' : 'gesperrt') : '';
                    return (
                      <div key={id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                        <span className="text-sm text-white/75">
                          {label}
                          {userChoice(user.name, id) === 'inherit' && inherited && <span className="ml-2 text-xs text-white/40">derzeit {inherited}</span>}
                        </span>
                        <Segmented label={`${label} für ${user.name}`} inheritLabel="Wie Gruppe" value={userChoice(user.name, id)} onChange={choice => setUser(user.name, id, choice)} />
                      </div>
                    );
                  })}
                </div>
              </li>
            ))}
          </ul>
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
