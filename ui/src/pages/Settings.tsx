import { useState } from 'react';
import type { ReactNode } from 'react';
import { Archive, BellRing, Boxes, Globe, SquareTerminal, CheckCircle2, Download, FolderOpen, UsersRound, HardDrive, Info, KeyRound, LogOut, Power, RefreshCw, RotateCw, Users as UsersIcon } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { action, get, post, waitJob } from '../api';
import type { Monitoring, Session, Status, Updates } from '../api';
import { bytes, cx, duration, go, message, percent, useApi } from '../lib';
import { SharesSection } from './Shares';
import { StorageSection } from './StorageSection';
import { BackupsSection } from './Backups';
import { GroupsSection } from './Groups';
import { DockerSection } from './Docker';
import { TerminalSection } from './Terminal';
import { RemoteSection } from './Remote';
import { GraphicsCard } from './Graphics';
import { AccountSection, UsersSection } from './Users';
import { Button, Card, Confirm, Loading, Meter, Notice, Sheet, useToast } from '../ui';

type Section = { id: string; label: string; icon: LucideIcon; admin?: boolean };
const SECTIONS: Section[] = [
  { id: 'system', label: 'System', icon: Info },
  { id: 'storage', label: 'Speicher', icon: HardDrive, admin: true },
  { id: 'shares', label: 'Freigaben', icon: FolderOpen, admin: true },
  { id: 'users', label: 'Benutzer', icon: UsersIcon, admin: true },
  { id: 'groups', label: 'Gruppen und Rechte', icon: UsersRound, admin: true },
  { id: 'backups', label: 'Sicherungen', icon: Archive, admin: true },
  { id: 'remote', label: 'Fernzugriff', icon: Globe, admin: true },
  { id: 'docker', label: 'Docker', icon: Boxes, admin: true },
  { id: 'terminal', label: 'Terminal', icon: SquareTerminal, admin: true },
  { id: 'updates', label: 'Updates', icon: Download, admin: true },
  { id: 'account', label: 'Mein Konto', icon: KeyRound },
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
  const [reboot, setReboot] = useState(false);

  const acknowledge = async (id: string) => {
    try {
      await post('/api/monitoring/ack', { id });
      await monitoring.reload();
    } catch (reason) {
      toast(message(reason), true);
    }
  };
  const s = status.data;
  const alerts = (monitoring.data?.alerts || []).filter(alert => alert.active && !alert.acknowledged);

  return (
    <div className="space-y-4">
      {alerts.map(alert => (
        <Notice key={alert.id} tone={alert.severity === 'critical' ? 'bad' : 'warn'}>
          <span className="font-medium">{alert.title}</span>
          <span className="block opacity-80">{alert.detail}</span>
          <button type="button" onClick={() => acknowledge(alert.id)} className="mt-1 text-[13px] font-medium underline underline-offset-4">
            Als gelesen markieren
          </button>
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
      {admin && <GraphicsCard />}
      {admin && (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Neu starten oder ausschalten</h2>
            <p className="mt-0.5 text-sm text-white/50">Zum Ausschalten müssen virtuelle Maschinen heruntergefahren sein.</p>
          </div>
          <div className="flex gap-2">
            <Button onClick={() => setReboot(true)}>
              <RotateCw className="size-4" /> Neu starten
            </Button>
            <Button variant="danger" onClick={() => setShutdown(true)}>
              <Power className="size-4" /> Ausschalten
            </Button>
          </div>
        </Card>
      )}
      {reboot && (
        <Confirm
          title="NAS neu starten?"
          text="Apps, virtuelle Maschinen und Freigaben sind während des Neustarts für einige Minuten nicht erreichbar. Ein bereits installiertes Update wird dabei aktiv."
          confirmLabel="Neu starten"
          onClose={() => setReboot(false)}
          onConfirm={async () => {
            try {
              // The agent only reboots the system state the administrator has seen.
              const system = await get<{ booted: { digest: string } }>('/api/updates/system');
              const result = await action('system_reboot', { expected_digest: system.booted.digest, confirmation: 'NEUSTART' });
              toast(String(result.message || 'Das NAS startet neu.'));
            } catch (reason) {
              toast(message(reason), true);
            }
          }}
        />
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
      toast(`Update ${version} ist installiert. Es wird nach einem Neustart aktiv (Einstellungen → System).`);
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
        <div className={cx('min-w-0', active === 'terminal' || active === 'docker' ? 'max-w-4xl' : 'max-w-2xl')}>
          {active === 'system' && <SystemSection session={session} admin={admin} />}
          {active === 'storage' && <StorageSection />}
          {active === 'shares' && <SharesSection />}
          {active === 'users' && <UsersSection current={session.user?.name || ''} />}
          {active === 'remote' && <RemoteSection />}
          {active === 'docker' && <DockerSection />}
          {active === 'terminal' && <TerminalSection />}
          {active === 'groups' && <GroupsSection />}
          {active === 'backups' && <BackupsSection />}
          {active === 'account' && <AccountSection name={session.user?.name || ''} onChanged={onSessionChange} />}
          {active === 'updates' && <UpdatesSection />}
        </div>
      </div>
    </Sheet>
  );
}
