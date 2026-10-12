import { ArrowLeft, SlidersHorizontal } from 'lucide-react';
import type { InstalledApp } from '../api';
import { go, useApi } from '../lib';
import { AppIcon, Button, IconButton, Loading, Notice } from '../ui';
import { RemoteSession } from './RemoteSession';

/** App pages execute in a NAS browser, reached only through Titan's login. */
export function AppWindow({ appId }: { appId: string }) {
  const apps = useApi<{installed: InstalledApp[]}>('/api/apps', 15000);
  const app = apps.data?.installed.find(item => item.id === appId);
  return <section className="mx-auto flex h-full w-full max-w-[110rem] flex-col px-2 pb-[var(--dock-clearance,108px)] pt-2 sm:px-4 sm:pt-4">
    <div className="glass flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl shadow-2xl animate-rise">
      <header className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
        <IconButton label="Zurück zur Startseite" onClick={() => go()}><ArrowLeft className="size-5" /></IconButton>
        {app && <AppIcon id={app.id} name={app.name} size={28} />}
        <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{app?.name || 'App'}</h1>
        {app && <IconButton label="Details und Protokoll" onClick={() => go('apps', app.id)}><SlidersHorizontal className="size-4" /></IconButton>}
      </header>
      <div className="relative min-h-0 flex-1 bg-black/30">
        {apps.loading ? <Loading /> : !app ? <div className="p-6"><Notice>{apps.error || 'Diese App ist nicht installiert.'}</Notice></div>
          : app.state !== 'running' ? <div className="mx-auto max-w-lg space-y-3 p-6"><Notice tone="info">{app.name} läuft gerade nicht.</Notice><Button onClick={() => go('apps', app.id)}>Zur App-Seite</Button></div>
          : <RemoteSession kind="app" target={app.id} title={app.name} />}
      </div>
    </div>
  </section>;
}
