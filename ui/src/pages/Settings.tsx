import { useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { BellRing, CheckCircle2, Download, HardDrive, Info, LogOut, Power, RefreshCw, UserPlus, Users as UsersIcon } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { action, post, waitJob } from '../api';
import type { Monitoring, Session, Status, Storage, Updates, Users } from '../api';
import { bytes, cx, duration, go, message, percent, useApi } from '../lib';
import { Button, Card, Confirm, Field, Input, Loading, Meter, Modal, Notice, Select, Sheet, useToast } from '../ui';

type Section = { id: string; label: string; icon: LucideIcon; admin?: boolean };
const SECTIONS: Section[] = [
  { id: 'system', label: 'System', icon: Info },
  { id: 'storage', label: 'Speicher', icon: HardDrive, admin: true },
  { id: 'users', label: 'Benutzer', icon: UsersIcon, admin: true },
  { id: 'updates', label: 'Updates', icon: Download, admin: true },
];

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 text-sm">
      <span className="text-white/55">{label}</span>
      <span className="min-w-0 truncate text-right font-medium">{children}</span>
    </div>
  );
}

function SystemSection({ session, admin }: { session: Session; admin: boolean }) {
  const toast = useToast();
  const status = useApi<Status>('/api/status', 5000);
  const monitoring = useApi<Monitoring>(admin ? '/api/monitoring' : null, 60000);
  const [shutdown, setShutdown] = useState(false);
  const s = status.data;
  const alerts = (monitoring.data?.alerts || []).filter(alert => alert.active && !alert.acknowledged);

  return (
    <div className="space-y-4">
      {alerts.map(alert => (
        <Notice key={alert.id} tone={alert.severity === 'critical' ? 'bad' : 'warn'}>
          <span className="font-medium">{alert.title}</span>
          <span className="block opacity-80">{alert.detail}</span>
        </Notice>
      ))}
      <Card>
        <div className="flex items-center gap-4">
          <img src="/logo.svg" alt="" className="size-14 rounded-2xl bg-white p-2 shadow-lg shadow-black/30" />
          <div>
            <div className="text-lg font-semibold">{s?.hostname || 'Titan'}</div>
            <div className="text-sm text-white/50">
              Titan {session.version}
              {session.demo && ' · Demo'}
            </div>
          </div>
        </div>
        {s && (
          <div className="mt-4 divide-y divide-white/6">
            <Row label="Laufzeit">{duration(s.uptime)}</Row>
            <Row label="Prozessor">
              {s.cpus} Kerne · {Math.round(s.cpu_percent)} %
              {s.temperature_available && s.cpu_temperature ? ` · ${Math.round(s.cpu_temperature)} °C` : ''}
            </Row>
            <div className="py-3">
              <div className="mb-2 flex justify-between text-sm">
                <span className="text-white/55">Arbeitsspeicher</span>
                <span className="font-medium tabular-nums">
                  {bytes(s.memory_used)} von {bytes(s.memory_total)}
                </span>
              </div>
              <Meter value={percent(s.memory_used, s.memory_total)} />
            </div>
          </div>
        )}
        {status.error && !s && <p className="mt-4 text-sm text-white/50">Systemwerte sind für dieses Konto nicht freigegeben.</p>}
      </Card>
      {monitoring.data && (
        <Card>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <BellRing className="size-4 text-white/50" /> Dienste
          </h2>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(monitoring.data.services).filter(([, service]) => service.installed).map(([name, service]) => (
              <div key={name} className="flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm">
                <span className={cx('size-2 rounded-full', service.active ? 'bg-ok' : 'bg-bad')} aria-hidden />
                <span className="capitalize">{name}</span>
                <span className="sr-only">{service.active ? 'aktiv' : 'inaktiv'}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
      {admin && (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">NAS ausschalten</h2>
            <p className="mt-0.5 text-sm text-white/50">Virtuelle Maschinen müssen vorher heruntergefahren sein.</p>
          </div>
          <Button variant="danger" onClick={() => setShutdown(true)}>
            <Power className="size-4" /> Ausschalten
          </Button>
        </Card>
      )}
      {shutdown && (
        <Confirm
          title="NAS ausschalten?"
          text="Titan fährt in etwa einer Minute herunter. Apps und Freigaben sind danach nicht mehr erreichbar, bis das Gerät wieder eingeschaltet wird."
          confirmLabel="Ausschalten"
          danger
          onClose={() => setShutdown(false)}
          onConfirm={async () => {
            try {
              const result = await action('system_shutdown', { confirmation: true });
              toast(String(result.message || 'Das NAS wird ausgeschaltet.'));
            } catch (reason) {
              toast(message(reason), true);
            }
          }}
        />
      )}
    </div>
  );
}

function StorageSection() {
  const storage = useApi<Storage>('/api/storage', 30000);
  if (storage.loading) return <Loading />;
  if (storage.error && !storage.data) return <Notice>{storage.error}</Notice>;
  const data = storage.data!;
  return (
    <div className="space-y-4">
      {data.pools.length === 0 && <Notice tone="info">Noch kein Speicherbereich eingerichtet.</Notice>}
      {data.pools.map(pool => (
        <Card key={pool.name}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <HardDrive className="size-5 text-white/50" aria-hidden />
              <span className="font-semibold">{pool.name}</span>
            </div>
            <span className={cx('rounded-full px-2.5 py-0.5 text-xs font-medium', pool.health === 'ONLINE' ? 'bg-ok/15 text-ok' : 'bg-bad/15 text-bad')}>
              {pool.health === 'ONLINE' ? 'In Ordnung' : pool.health}
            </span>
          </div>
          <div className="mb-2 mt-4 flex justify-between text-sm">
            <span className="text-white/55">{bytes(pool.used)} belegt</span>
            <span className="tabular-nums text-white/55">{bytes(pool.free)} frei von {bytes(pool.size)}</span>
          </div>
          <Meter value={percent(pool.used, pool.size)} />
        </Card>
      ))}
      <Card>
        <h2 className="text-sm font-semibold">Laufwerke</h2>
        <ul className="mt-2 divide-y divide-white/6">
          {data.disks.map(disk => (
            <li key={disk.name} className="flex items-center justify-between gap-4 py-2.5 text-sm">
              <span className="min-w-0 truncate">
                <span className="font-medium">{disk.model || 'Laufwerk'}</span> <span className="text-white/45">{disk.name}</span>
              </span>
              <span className="shrink-0 tabular-nums text-white/65">
                {bytes(disk.size)} · {disk.fstype ? 'in Verwendung' : 'frei'}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Button onClick={() => window.open('/classic#storage', '_blank', 'noopener')}>Speicherbereiche und Freigaben verwalten</Button>
    </div>
  );
}

function UsersSection({ current }: { current: string }) {
  const toast = useToast();
  const users = useApi<Users>('/api/users');
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: '', password: '', role: 'user' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { job } = await post<{ job: string }>('/api/users', form);
      await waitJob(job);
      toast(`Benutzer „${form.name}“ angelegt.`);
      setAdding(false);
      setForm({ name: '', password: '', role: 'user' });
      await users.reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  if (users.loading) return <Loading />;
  if (users.error && !users.data) return <Notice>{users.error}</Notice>;
  return (
    <div className="space-y-4">
      <Card>
        <ul className="divide-y divide-white/6">
          {users.data!.web.map(user => (
            <li key={user.name} className="flex items-center gap-3 py-2.5">
              <span className="flex size-9 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-600 text-sm font-semibold uppercase">{user.name.slice(0, 1)}</span>
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
            </li>
          ))}
        </ul>
      </Card>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => setAdding(true)}>
          <UserPlus className="size-4" /> Benutzer anlegen
        </Button>
        <Button onClick={() => window.open('/classic#users', '_blank', 'noopener')}>Rechte und Gruppen verwalten</Button>
      </div>
      {adding && (
        <Modal title="Benutzer anlegen" onClose={() => setAdding(false)}>
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
              <Button variant="ghost" onClick={() => setAdding(false)}>Abbrechen</Button>
              <Button type="submit" variant="primary" busy={busy}>Anlegen</Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function UpdatesSection() {
  const toast = useToast();
  const updates = useApi<Updates>('/api/updates');
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState('');

  const check = async () => {
    setChecking(true);
    setError('');
    try {
      const { job } = await post<{ job: string }>('/api/updates/check', { update_kind: 'all' });
      await waitJob(job, 5 * 60 * 1000);
      await updates.reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setChecking(false);
    }
  };

  const install = async () => {
    const version = updates.data?.latest;
    if (!version) return;
    setInstalling(true);
    setError('');
    try {
      await action('update_install', { expected_version: version, update_kind: 'all' });
      toast(`Update ${version} ist installiert. Zum Abschluss ist ein Neustart nötig.`);
      await updates.reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setInstalling(false);
    }
  };

  if (updates.loading) return <Loading />;
  const data = updates.data;
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            {data?.available ? <Download className="size-9 text-brand" aria-hidden /> : <CheckCircle2 className="size-9 text-ok" aria-hidden />}
            <div>
              <div className="font-semibold">{data?.available ? `Titan ${data.latest} ist verfügbar` : 'Titan ist aktuell'}</div>
              <div className="text-sm text-white/50">
                Installiert: {data?.current} · Kanal: {data?.channel}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <Button busy={checking} disabled={installing} onClick={check}>
              <RefreshCw className="size-4" /> Suchen
            </Button>
            {data?.available && data.latest && (
              <Button variant="primary" busy={installing} onClick={() => setConfirm(true)}>
                Installieren
              </Button>
            )}
          </div>
        </div>
        {error && <div className="mt-4"><Notice>{error}</Notice></div>}
      </Card>
      <Notice tone="info">
        Updates werden in den zweiten Systembereich geschrieben. Startet das neue System nicht, wechselt Titan automatisch auf den bisherigen Stand zurück.
      </Notice>
      <Button onClick={() => window.open('/classic#updates', '_blank', 'noopener')}>Neustart und Updateverlauf</Button>
      {confirm && data?.latest && (
        <Confirm
          title={`Titan ${data.latest} installieren?`}
          text="Das Update wird heruntergeladen, geprüft und in den inaktiven Systembereich geschrieben. Apps und VMs laufen dabei weiter; aktiv wird es erst nach einem Neustart."
          confirmLabel="Installieren"
          onClose={() => setConfirm(false)}
          onConfirm={() => {
            void install();
          }}
        />
      )}
    </div>
  );
}

export function Settings({ session, section, onSessionChange }: { session: Session; section?: string; onSessionChange: () => Promise<void> }) {
  const admin = session.user?.role === 'admin';
  const sections = SECTIONS.filter(item => !item.admin || admin);
  const active = sections.find(item => item.id === section)?.id || 'system';

  const logout = async () => {
    try {
      await post('/api/logout');
    } finally {
      go();
      await onSessionChange();
    }
  };

  return (
    <Sheet
      title="Einstellungen"
      subtitle={`Angemeldet als ${session.user?.name}`}
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={() => window.open('/classic', '_blank', 'noopener')}>
            Klassische Oberfläche
          </Button>
          <Button size="sm" onClick={logout}>
            <LogOut className="size-4" /> Abmelden
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="Einstellungsbereiche" className="min-w-0">
          <ul className="flex gap-1 overflow-x-auto md:block md:space-y-1">
            {sections.map(item => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-current={item.id === active ? 'page' : undefined}
                  onClick={() => go('settings', item.id)}
                  className={cx('flex w-full items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-left text-sm transition-colors', item.id === active ? 'bg-white/14 font-medium text-white' : 'text-white/65 hover:bg-white/8')}
                >
                  <item.icon className="size-4 shrink-0" aria-hidden /> {item.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 max-w-2xl">
          {active === 'system' && <SystemSection session={session} admin={admin} />}
          {active === 'storage' && <StorageSection />}
          {active === 'users' && <UsersSection current={session.user?.name || ''} />}
          {active === 'updates' && <UpdatesSection />}
        </div>
      </div>
    </Sheet>
  );
}
