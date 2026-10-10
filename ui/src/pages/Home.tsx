import { useEffect, useRef, useState } from 'react';
import { Cpu, ExternalLink, HardDrive, MemoryStick, MoreHorizontal, Play, Plus, RotateCw, Square, Trash2 } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { action } from '../api';
import type { InstalledApp, Session, Status, Storage } from '../api';
import { bytes, cx, go, message, percent, useApi } from '../lib';
import { AppIcon, Confirm, Meter, StateDot, useToast } from '../ui';

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
    if (url) window.open(url, '_blank', 'noopener');
    else toast(`${app.name} hat keine Weboberfläche.`);
  };

  const items: { label: string; icon: LucideIcon; onClick: () => void; danger?: boolean }[] = [
    ...(running && url ? [{ label: 'Öffnen', icon: ExternalLink, onClick: open }] : []),
    ...(running
      ? [
          { label: 'Neu starten', icon: RotateCw, onClick: () => run('restart', 'neu gestartet.') },
          { label: 'Stoppen', icon: Square, onClick: () => run('stop', 'gestoppt.') },
        ]
      : [{ label: 'Starten', icon: Play, onClick: () => run('start', 'gestartet.') }]),
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
        <div role="menu" className="glass absolute left-1/2 top-[88px] z-30 w-44 -translate-x-1/2 rounded-2xl p-1.5 shadow-2xl animate-fade">
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

export function Home({ session }: { session: Session }) {
  const admin = session.user?.role === 'admin';
  const canApps = Boolean(session.permissions.apps?.allowed);
  const status = useApi<Status>(canApps || admin ? '/api/status' : null, 5000);
  const storage = useApi<Storage>(admin ? '/api/storage' : null, 60000);
  const apps = useApi<{ installed: InstalledApp[] }>(canApps ? '/api/apps' : null, 10000);

  const pools = storage.data?.pools || [];
  const total = pools.reduce((sum, pool) => sum + pool.size, 0);
  const used = pools.reduce((sum, pool) => sum + pool.used, 0);
  const s = status.data;

  return (
    <div className="scroll-area h-full overflow-y-auto px-4 pb-36 pt-[9vh]">
      <div className="mx-auto max-w-5xl">
        <h1 className="text-center text-4xl font-semibold tracking-tight drop-shadow-lg sm:text-5xl">
          {greeting()}, {session.user?.name}
        </h1>
        <p className="mt-2 text-center text-sm text-white/65 drop-shadow">{s?.hostname || 'Titan'} · Version {session.version}</p>

        {s && (
          <div className="mx-auto mt-9 grid max-w-2xl grid-cols-3 gap-2 sm:flex sm:justify-center sm:gap-3">
            <Widget icon={Cpu} label="CPU" value={`${Math.round(s.cpu_percent)} %`} detail={`${s.cpus} Kerne${s.temperature_available && s.cpu_temperature ? ` · ${Math.round(s.cpu_temperature)} °C` : ''}`} fraction={s.cpu_percent} />
            <Widget icon={MemoryStick} label="RAM" value={bytes(s.memory_used)} detail={`von ${bytes(s.memory_total)}`} fraction={percent(s.memory_used, s.memory_total)} />
            {total > 0 && <Widget icon={HardDrive} label="Speicher" value={bytes(used)} detail={`von ${bytes(total)}`} fraction={percent(used, total)} />}
          </div>
        )}

        {canApps && (
          <div className="mt-12 flex flex-wrap justify-center gap-x-6 gap-y-8 sm:gap-x-9">
            {(apps.data?.installed || []).map(app => (
              <AppTile key={app.id} app={app} admin={admin} onChanged={apps.reload} />
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
