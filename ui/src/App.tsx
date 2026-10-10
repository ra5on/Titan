import { useCallback, useEffect, useState } from 'react';
import { FolderOpen, Home as HomeIcon, MonitorPlay, Settings as SettingsIcon, Store as StoreIcon } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { get, setCsrf } from './api';
import type { Session } from './api';
import { cx, go, message, useRoute } from './lib';
import { Loading, Notice } from './ui';
import { Login } from './pages/Login';
import { Home } from './pages/Home';
import { Store } from './pages/Store';
import { Files } from './pages/Files';
import { Vms } from './pages/Vms';
import { Settings } from './pages/Settings';

type DockItem = { id: string; label: string; icon: LucideIcon; tint: string; need?: 'files' | 'apps' | 'vms'; admin?: boolean };

const DOCK: DockItem[] = [
  { id: '', label: 'Start', icon: HomeIcon, tint: 'from-sky-400 to-blue-600' },
  { id: 'store', label: 'App Store', icon: StoreIcon, tint: 'from-violet-400 to-indigo-600', need: 'apps' },
  { id: 'files', label: 'Dateien', icon: FolderOpen, tint: 'from-amber-300 to-orange-500', need: 'files' },
  { id: 'vms', label: 'Virtuelle Maschinen', icon: MonitorPlay, tint: 'from-emerald-300 to-teal-600', need: 'vms' },
  { id: 'settings', label: 'Einstellungen', icon: SettingsIcon, tint: 'from-slate-300 to-slate-600' },
];

function Dock({ active, session }: { active: string; session: Session }) {
  const items = DOCK.filter(item => !item.need || session.permissions[item.need]?.allowed);
  return (
    <nav aria-label="Hauptnavigation" className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center pb-4">
      <ul className="glass pointer-events-auto flex items-end gap-2 rounded-[26px] p-2.5 shadow-2xl sm:gap-3">
        {items.map(item => {
          const current = active === item.id;
          return (
            <li key={item.id} className="group relative">
              <button
                type="button"
                aria-label={item.label}
                aria-current={current ? 'page' : undefined}
                onClick={() => go(...(item.id ? [item.id] : []))}
                className={cx(
                  'flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br text-white shadow-lg shadow-black/30 transition-transform duration-200',
                  'hover:-translate-y-1.5 hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:size-14',
                  item.tint,
                )}
              >
                <item.icon className="size-6 sm:size-7" strokeWidth={1.8} aria-hidden />
              </button>
              <span className={cx('absolute -bottom-1.5 left-1/2 size-1 -translate-x-1/2 rounded-full bg-white transition-opacity', current ? 'opacity-90' : 'opacity-0')} aria-hidden />
              <span className="glass pointer-events-none absolute -top-10 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-lg px-2.5 py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100 sm:block" aria-hidden>
                {item.label}
              </span>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Wallpaper({ dimmed }: { dimmed: boolean }) {
  return (
    <div className="fixed inset-0 -z-10" aria-hidden>
      <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_20%_0%,#27408b_0%,#141a33_45%,#0b1020_100%)]" />
      <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: 'url(/wallpapers/horizon.png)' }} />
      <div className={cx('absolute inset-0 transition-colors duration-300', dimmed ? 'bg-black/45' : 'bg-black/15')} />
    </div>
  );
}

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const route = useRoute();

  const refresh = useCallback(async () => {
    try {
      const value = await get<Session>('/api/session');
      setCsrf(value.user?.csrf || '');
      setSession(value);
      setError('');
    } catch (reason) {
      setError(message(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const page = route[0] || '';

  let content;
  if (error && !session) {
    content = (
      <div className="mx-auto mt-32 max-w-md px-4">
        <Notice>Titan ist nicht erreichbar: {error}</Notice>
      </div>
    );
  } else if (!session) {
    content = <Loading />;
  } else if (!session.user) {
    content = <Login session={session} onDone={refresh} />;
  } else {
    const allowed = (need: 'files' | 'apps' | 'vms') => Boolean(session.permissions[need]?.allowed);
    content = (
      <>
        <main className="h-full">
          {page === 'store' && allowed('apps') ? (
            <Store appId={route[1]} />
          ) : page === 'files' && allowed('files') ? (
            <Files />
          ) : page === 'vms' && allowed('vms') ? (
            <Vms />
          ) : page === 'settings' ? (
            <Settings session={session} section={route[1]} onSessionChange={refresh} />
          ) : (
            <Home session={session} />
          )}
        </main>
        <Dock active={['store', 'files', 'vms', 'settings'].includes(page) ? page : ''} session={session} />
      </>
    );
  }

  return (
    <>
      <Wallpaper dimmed={Boolean(session?.user) && page !== ''} />
      {content}
    </>
  );
}
