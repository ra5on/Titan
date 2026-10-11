import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { FolderOpen, Home as HomeIcon, MonitorPlay, Settings as SettingsIcon, Store as StoreIcon } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { get, setCsrf } from './api';
import type { InstalledApp, Session, VmList } from './api';
import { cx, go, message, useApi, useRoute } from './lib';
import { PrefsProvider, usePrefs } from './prefs';
import { AppIcon, Loading, Notice } from './ui';
import { Login } from './pages/Login';
import { Home } from './pages/Home';
import { Store } from './pages/Store';
import { AppDetail } from './pages/AppDetail';
import { AppWindow } from './pages/AppWindow';
import { VmConsole } from './pages/VmConsole';
import { Files } from './pages/Files';
import { Vms } from './pages/Vms';
import { Settings } from './pages/Settings';

type Tool = { route: string; label: string; icon: LucideIcon; tint: string; need?: 'files' | 'apps' | 'vms' };

const TOOLS: Record<string, Tool> = {
  'tool:home': { route: '', label: 'Start', icon: HomeIcon, tint: 'from-sky-400 to-blue-600' },
  'tool:store': { route: 'store', label: 'App Store', icon: StoreIcon, tint: 'from-violet-400 to-indigo-600', need: 'apps' },
  'tool:files': { route: 'files', label: 'Dateien', icon: FolderOpen, tint: 'from-amber-300 to-orange-500', need: 'files' },
  'tool:vms': { route: 'vms', label: 'Virtuelle Maschinen', icon: MonitorPlay, tint: 'from-emerald-300 to-teal-600', need: 'vms' },
  'tool:settings': { route: 'settings', label: 'Einstellungen', icon: SettingsIcon, tint: 'from-slate-300 to-slate-600' },
};
const DOCK_SIZE = { small: 44, medium: 56, large: 68 };

function Dock({ route, session }: { route: string[]; session: Session }) {
  const { prefs } = usePrefs();
  const allowed = (need?: 'files' | 'apps' | 'vms') => !need || Boolean(session.permissions[need]?.allowed);
  const wantsApps = allowed('apps') && prefs.dock.some(entry => entry.startsWith('app:'));
  const wantsVms = allowed('vms') && prefs.dock.some(entry => entry.startsWith('vm:'));
  const apps = useApi<{ installed: InstalledApp[] }>(wantsApps ? '/api/apps' : null, 30000);
  const vms = useApi<VmList>(wantsVms ? '/api/vms' : null, 30000);
  const nav = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(window.innerWidth);
  const gap = width < 640 ? 8 : 12;
  const preferred = DOCK_SIZE[prefs.dock_size] || DOCK_SIZE.medium;
  // Fit the account's dock to the viewport; crowded phone docks may wrap.
  const count = Math.max(1, prefs.dock.length);
  const size = Math.max(32, Math.min(preferred, Math.floor((width - 40 - gap * (count - 1)) / count)));
  useLayoutEffect(() => {
    const element = nav.current!;
    const measure = () => {
      setWidth(window.innerWidth);
      document.documentElement.style.setProperty('--dock-clearance', `${element.getBoundingClientRect().height + 12}px`);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener('resize', measure);
    measure();
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      document.documentElement.style.removeProperty('--dock-clearance');
    };
  }, []);
  const page = route[0] || '';

  const items = prefs.dock.flatMap(entry => {
    const tool = TOOLS[entry];
    if (tool) {
      if (!allowed(tool.need)) return [];
      const current = tool.route ? tool.route === page : page === '';
      return [{ key: entry, label: tool.label, current, open: () => go(...(tool.route ? [tool.route] : [])), node: <tool.icon style={{ width: size * 0.5, height: size * 0.5 }} strokeWidth={1.8} aria-hidden />, tint: tool.tint }];
    }
    if (entry.startsWith('app:')) {
      const app = apps.data?.installed.find(item => item.id === entry.slice(4));
      if (!app) return [];
      return [{ key: entry, label: app.name, current: (page === 'open' || page === 'apps') && route[1] === app.id, open: () => go('open', app.id), node: <AppIcon id={app.id} name={app.name} size={size} />, tint: '' }];
    }
    const vm = vms.data?.vms.find(item => item.id === entry.slice(3));
    if (!vm) return [];
    return [{ key: entry, label: vm.display_name || vm.name, current: page === 'vms' && route[1] === vm.id, open: () => go('vms', vm.id),
      node: <MonitorPlay style={{ width: size * 0.5, height: size * 0.5 }} strokeWidth={1.8} aria-hidden />, tint: 'from-teal-300 to-cyan-700' }];
  });

  return (
    <nav ref={nav} aria-label="Hauptnavigation" className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
      <ul className="glass pointer-events-auto flex max-w-full flex-wrap items-end justify-center gap-2 overflow-visible rounded-[26px] p-2.5 shadow-2xl sm:gap-3">
        {items.map(item => (
          <li key={item.key} className="group relative shrink-0">
            <button
              type="button"
              aria-label={item.label}
              aria-current={item.current ? 'page' : undefined}
              onClick={item.open}
              style={{ width: size, height: size, borderRadius: size * 0.28 }}
              className={cx(
                'flex items-center justify-center overflow-hidden text-white shadow-lg shadow-black/30 transition-transform duration-200',
                'hover:-translate-y-1.5 hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white',
                item.tint && 'bg-gradient-to-br ' + item.tint,
              )}
            >
              {item.node}
            </button>
            <span className={cx('absolute -bottom-1.5 left-1/2 size-1 -translate-x-1/2 rounded-full bg-white transition-opacity', item.current ? 'opacity-90' : 'opacity-0')} aria-hidden />
            <span className="glass pointer-events-none absolute -top-10 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-lg px-2.5 py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100 sm:block" aria-hidden>
              {item.label}
            </span>
          </li>
        ))}
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
      // Appearance belongs to the account, so it is loaded per sign-in.
      <PrefsProvider key={session.user.name}>
        <main className="h-full">
          {page === 'store' && allowed('apps') ? (
            <Store appId={route[1]} admin={session.user?.role === 'admin'} />
          ) : page === 'open' && route[1] && allowed('apps') ? (
            <AppWindow key={route[1]} appId={route[1]} />
          ) : page === 'vms' && route[1] && allowed('vms') ? (
            <VmConsole key={route[1]} vmId={route[1]} />
          ) : page === 'apps' && route[1] && allowed('apps') ? (
            <AppDetail key={route[1]} appId={route[1]} />
          ) : page === 'files' && allowed('files') ? (
            <Files key={route[1] || ''} initialShare={route[1]} />
          ) : page === 'vms' && allowed('vms') ? (
            <Vms />
          ) : page === 'settings' ? (
            <Settings session={session} section={route[1]} onSessionChange={refresh} />
          ) : (
            <Home session={session} onSessionChange={refresh} />
          )}
        </main>
        <Dock route={route} session={session} />
      </PrefsProvider>
    );
  }

  return (
    <>
      <Wallpaper dimmed={Boolean(session?.user) && page !== ''} />
      {content}
    </>
  );
}
