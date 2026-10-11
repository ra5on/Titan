import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Cpu, ExternalLink, HardDrive, LogOut, MemoryStick, MonitorPlay, MoreHorizontal, Palette, Power, SlidersHorizontal, Play, Plus, RotateCw, Square, Trash2 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { action } from '../api';
import type { InstalledApp, Session, Status, Storage, VmList } from '../api';
import { bytes, cx, go, message, percent, useApi } from '../lib';
import { usePrefs } from '../prefs';
import { logout, rebootSystem, shutdownSystem } from '../system';
import { AppearanceDialog } from './Appearance';
import { AppIcon, Confirm, Menu, Meter, StateDot, useToast } from '../ui';

function greeting() {
  const hour = new Date().getHours();
  return hour < 5 ? 'Gute Nacht' : hour < 11 ? 'Guten Morgen' : hour < 18 ? 'Guten Tag' : 'Guten Abend';
}

function Widget({ icon: Icon, label, value, detail, fraction }: { icon: LucideIcon; label: string; value: string; detail: string; fraction: number }) {
  return (
    <div className="glass min-w-0 rounded-2xl p-3 sm:w-52 sm:rounded-3xl sm:p-4">
      <div className="flex items-center gap-1.5 truncate text-[11px] font-medium uppercase tracking-wider text-white/50 sm:text-xs">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        {label}
      </div>
      <div className="mt-1.5 truncate text-lg font-semibold tabular-nums tracking-tight sm:mt-2 sm:text-2xl">{value}</div>
      <div className="mb-3 mt-0.5 truncate text-xs text-white/50">{detail}</div>
      <Meter value={fraction} />
    </div>
  );
}

const appUrl = (app: InstalledApp) => (app.port ? `${app.scheme || 'http'}://${window.location.hostname}:${app.port}` : null);

function AppTile({ app, admin, onChanged }: { app: InstalledApp; admin: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const url = appUrl(app);
  const running = app.state === 'running';

  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !container.current?.contains(event.target as Node)) setMenu(false);
    };
    window.addEventListener('mousedown', close);
    window.addEventListener('keydown', close);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', close);
    };
  }, [menu]);

  const run = async (command: 'start' | 'stop' | 'restart' | 'remove', done: string) => {
    setMenu(false);
    setBusy(true);
    try {
      await action('app_action', { app: app.id, action: command });
      toast(`${app.name}: ${done}`);
    } catch (reason) {
      toast(`${app.name}: ${message(reason)}`, true);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  const open = () => {
    if (!running) return toast(`${app.name} ist gestoppt. Über das Menü starten.`, true);
    if (url) go('open', app.id);
    else toast(`${app.name} hat keine Weboberfläche.`);
  };

  const items: { label: string; icon: LucideIcon; onClick: () => void; danger?: boolean }[] = [
    ...(running && url ? [{ label: 'Öffnen', icon: ExternalLink, onClick: open }, { label: 'In neuem Tab öffnen', icon: ExternalLink, onClick: () => { setMenu(false); window.open(url, '_blank', 'noopener'); } }] : []),
    ...(running
      ? [
          { label: 'Neu starten', icon: RotateCw, onClick: () => run('restart', 'neu gestartet.') },
          { label: 'Stoppen', icon: Square, onClick: () => run('stop', 'gestoppt.') },
        ]
      : [{ label: 'Starten', icon: Play, onClick: () => run('start', 'gestartet.') }]),
    { label: 'Details und Protokoll', icon: SlidersHorizontal, onClick: () => go('apps', app.id) },
    { label: 'Deinstallieren', icon: Trash2, danger: true, onClick: () => { setMenu(false); setRemoving(true); } },
  ];

  return (
    <div ref={container} className="group relative flex w-24 flex-col items-center sm:w-28">
      <button
        type="button"
        onClick={open}
        onContextMenu={event => {
          if (!admin) return;
          event.preventDefault();
          setMenu(true);
        }}
        className="rounded-[22px] transition-transform duration-200 hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white active:scale-95"
        aria-label={`${app.name} öffnen`}
      >
        <span className={cx('block transition-opacity', (!running || busy) && 'opacity-45 grayscale')}>
          <AppIcon id={app.id} name={app.name} size={76} />
        </span>
      </button>
      <div className="mt-2.5 flex max-w-full items-center gap-1.5 text-[13px] font-medium text-white drop-shadow">
        <StateDot state={busy ? 'restarting' : app.state} />
        <span className="truncate">{app.name}</span>
      </div>
      {admin && (
        <button
          type="button"
          aria-label={`Aktionen für ${app.name}`}
          aria-expanded={menu}
          onClick={() => setMenu(value => !value)}
          className="glass absolute -right-1 -top-1 flex size-6 items-center justify-center rounded-full opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"
        >
          <MoreHorizontal className="size-3.5" />
        </button>
      )}
      {menu && (
        <div role="menu" className="glass absolute left-1/2 top-[88px] z-30 w-52 -translate-x-1/2 rounded-2xl p-1.5 shadow-2xl animate-fade">
          {items.map(item => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={item.onClick}
              className={cx('flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm hover:bg-white/10', item.danger ? 'text-bad' : 'text-white/90')}
            >
              <item.icon className="size-4" aria-hidden />
              {item.label}
            </button>
          ))}
        </div>
      )}
      {removing && (
        <Confirm
          title={`${app.name} deinstallieren?`}
          text="Die Container werden entfernt. Konfiguration und Nutzdaten der App bleiben auf dem NAS erhalten."
          confirmLabel="Deinstallieren"
          danger
          onClose={() => setRemoving(false)}
          onConfirm={() => run('remove', 'deinstalliert.')}
        />
      )}
    </div>
  );
}

/** Top-left system menu: sign out, restart and shut down, each after a confirmation. */
function SystemMenu({ name, admin, session, onSessionChange }: { name: string; admin: boolean; session: Session; onSessionChange: () => Promise<void> }) {
  const toast = useToast();
  const [appearance, setAppearance] = useState(false);
  const [confirm, setConfirm] = useState<'logout' | 'reboot' | 'shutdown' | null>(null);
  const actions = {
    logout: { title: 'Abmelden?', text: 'Du wirst von Titan abgemeldet. Apps und virtuelle Maschinen laufen weiter.', label: 'Abmelden', danger: false,
      run: async () => { try { await logout(); } finally { await onSessionChange(); } } },
    reboot: { title: 'NAS neu starten?', text: 'Apps, virtuelle Maschinen und Freigaben sind während des Neustarts für einige Minuten nicht erreichbar.', label: 'Neu starten', danger: false,
      run: async () => { try { toast(await rebootSystem()); } catch (reason) { toast(message(reason), true); } } },
    shutdown: { title: 'NAS ausschalten?', text: 'Titan fährt herunter und ist erst wieder erreichbar, wenn das Gerät eingeschaltet wird. Virtuelle Maschinen müssen vorher heruntergefahren sein.', label: 'Ausschalten', danger: true,
      run: async () => { try { toast(await shutdownSystem()); } catch (reason) { toast(message(reason), true); } } },
  };
  const active = confirm && actions[confirm];
  return (
    <div className="fixed left-4 top-4 z-30">
      <Menu
        label="Systemmenü"
        placement="below"
        align="left"
        trigger={
          <span className="glass flex h-10 items-center gap-2 rounded-full pl-3 pr-2.5 text-sm font-medium shadow-lg">
            <Power className="size-4" aria-hidden />
            <span className="max-w-40 truncate">{name}</span>
            <ChevronDown className="size-4 text-white/60" aria-hidden />
          </span>
        }
        items={[
          { label: 'Darstellung', icon: Palette, onClick: () => setAppearance(true) },
          { label: 'Abmelden', icon: LogOut, onClick: () => setConfirm('logout') },
          ...(admin ? [{ label: 'Neu starten', icon: RotateCw, onClick: () => setConfirm('reboot') }, { label: 'Ausschalten', icon: Power, danger: true, onClick: () => setConfirm('shutdown') }] : []),
        ]}
      />
      {appearance && <AppearanceDialog session={session} onClose={() => setAppearance(false)} />}
      {active && <Confirm title={active.title} text={active.text} confirmLabel={active.label} danger={active.danger} onClose={() => setConfirm(null)} onConfirm={active.run} />}
    </div>
  );
}

export function Home({ session, onSessionChange }: { session: Session; onSessionChange: () => Promise<void> }) {
  const admin = session.user?.role === 'admin';
  const canApps = Boolean(session.permissions.apps?.allowed);
  const status = useApi<Status>(canApps || admin ? '/api/status' : null, 5000);
  const storage = useApi<Storage>(admin ? '/api/storage' : null, 60000);
  const apps = useApi<{ installed: InstalledApp[] }>(canApps ? '/api/apps' : null, 10000);
  const { prefs } = usePrefs();
  const canVms = Boolean(session.permissions.vms?.allowed);
  const vms = useApi<VmList>(canVms && prefs.pinned_vms.length ? '/api/vms' : null, 10000);
  const pinned = (vms.data?.vms || []).filter(vm => prefs.pinned_vms.includes(vm.id));

  const pools = storage.data?.pools || [];
  const total = pools.reduce((sum, pool) => sum + pool.size, 0);
  const used = pools.reduce((sum, pool) => sum + pool.used, 0);
  const s = status.data;

  return (
    <div className="scroll-area h-full overflow-y-auto px-4 pb-36 pt-[9vh]">
      <SystemMenu name={s?.hostname || 'Titan'} admin={admin} session={session} onSessionChange={onSessionChange} />
      <div className="mx-auto max-w-5xl">
        <h1 className="text-center text-4xl font-semibold tracking-tight drop-shadow-lg sm:text-5xl">
          {greeting()}, {session.user?.name}
        </h1>
        <p className="mt-2 text-center text-sm text-white/65 drop-shadow">{s?.hostname || 'Titan'} · Version {session.version}</p>

        {s && prefs.widgets.length > 0 && (
          <div className="mx-auto mt-9 flex max-w-2xl justify-center gap-2 sm:gap-3 [&>*]:min-w-0 [&>*]:flex-1 sm:[&>*]:flex-none">
            {prefs.widgets.includes('cpu') && <Widget icon={Cpu} label="CPU" value={`${Math.round(s.cpu_percent)} %`} detail={`${s.cpus} Kerne${s.temperature_available && s.cpu_temperature ? ` · ${Math.round(s.cpu_temperature)} °C` : ''}`} fraction={s.cpu_percent} />}
            {prefs.widgets.includes('ram') && <Widget icon={MemoryStick} label="RAM" value={bytes(s.memory_used)} detail={`von ${bytes(s.memory_total)}`} fraction={percent(s.memory_used, s.memory_total)} />}
            {prefs.widgets.includes('storage') && total > 0 && <Widget icon={HardDrive} label="Speicher" value={bytes(used)} detail={`von ${bytes(total)}`} fraction={percent(used, total)} />}
          </div>
        )}

        {canApps && (
          <div className="mt-12 flex flex-wrap justify-center gap-x-6 gap-y-8 sm:gap-x-9">
            {(apps.data?.installed || []).filter(app => !prefs.hidden_apps.includes(app.id)).map(app => (
              <AppTile key={app.id} app={app} admin={admin} onChanged={apps.reload} />
            ))}
            {pinned.map(vm => (
              <div key={vm.id} className="flex w-24 flex-col items-center sm:w-28">
                <button
                  type="button"
                  onClick={() => go('vms', vm.id)}
                  aria-label={`${vm.display_name || vm.name} öffnen`}
                  className={cx('flex size-[76px] items-center justify-center rounded-[18px] bg-gradient-to-br from-teal-300 to-cyan-700 shadow-lg shadow-black/30 transition-transform duration-200 hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white active:scale-95', vm.state !== 'running' && 'opacity-45 grayscale')}
                >
                  <MonitorPlay className="size-9" strokeWidth={1.6} aria-hidden />
                </button>
                <div className="mt-2.5 flex max-w-full items-center gap-1.5 text-[13px] font-medium text-white drop-shadow">
                  <StateDot state={vm.state} />
                  <span className="truncate">{vm.display_name || vm.name}</span>
                </div>
              </div>
            ))}
            {apps.data && (
              <div className="flex w-24 flex-col items-center sm:w-28">
                <button
                  type="button"
                  onClick={() => go('store')}
                  aria-label="App hinzufügen"
                  className="glass flex size-[76px] items-center justify-center rounded-[18px] border-dashed text-white/70 transition-transform duration-200 hover:scale-105 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white"
                >
                  <Plus className="size-7" strokeWidth={1.6} />
                </button>
                <div className="mt-2.5 text-[13px] font-medium text-white/80 drop-shadow">App hinzufügen</div>
              </div>
            )}
          </div>
        )}
        {apps.error && <p className="mt-10 text-center text-sm text-white/60">Apps konnten nicht geladen werden: {apps.error}</p>}
      </div>
    </div>
  );
}
