import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ExternalLink, RotateCw, SlidersHorizontal } from 'lucide-react';
import type { InstalledApp } from '../api';
import { go, useApi } from '../lib';
import { appAddress } from '../system';
import type { AppAddress } from '../system';
import { AppIcon, Button, IconButton, Loading, Notice } from '../ui';

/** An installed app inside Titan's own window instead of a new browser tab. */
export function AppWindow({ appId }: { appId: string }) {
  const apps = useApi<{ installed: InstalledApp[] }>('/api/apps');
  const app = apps.data?.installed.find(item => item.id === appId);
  const [address, setAddress] = useState<AppAddress | null>(null);
  const [reload, setReload] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let stale = false;
    if (app) void appAddress(app).then(value => !stale && setAddress(value));
    return () => {
      stale = true;
    };
  }, [app?.id, app?.port, app?.scheme]); // eslint-disable-line react-hooks/exhaustive-deps

  const running = app?.state === 'running';
  return (
    <section className="mx-auto flex h-full w-full max-w-[110rem] flex-col px-2 pb-24 pt-2 sm:px-4 sm:pt-4">
      <div className="glass flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl shadow-2xl animate-rise">
        <header className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
          <IconButton label="Zurück zur Startseite" onClick={() => go()}>
            <ArrowLeft className="size-5" />
          </IconButton>
          {app && <AppIcon id={app.id} name={app.name} size={28} />}
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{app?.name || 'App'}</h1>
          {address?.embeddable && running && (
            <IconButton label="App neu laden" onClick={() => setReload(value => value + 1)}>
              <RotateCw className="size-4" />
            </IconButton>
          )}
          {app && (
            <IconButton label="Details und Protokoll" onClick={() => go('apps', app.id)}>
              <SlidersHorizontal className="size-4" />
            </IconButton>
          )}
          {address?.url && (
            <Button size="sm" variant="ghost" onClick={() => window.open(address.url!, '_blank', 'noopener')}>
              <ExternalLink className="size-4" /> Neuer Tab
            </Button>
          )}
        </header>
        <div className="relative min-h-0 flex-1 bg-black/30">
          {apps.loading || (app && !address) ? (
            <Loading />
          ) : !app ? (
            <div className="mx-auto max-w-lg p-6"><Notice>Diese App ist nicht installiert.</Notice></div>
          ) : !running ? (
            <div className="mx-auto max-w-lg space-y-3 p-6">
              <Notice tone="info">{app.name} läuft gerade nicht.</Notice>
              <Button onClick={() => go('apps', app.id)}>Zur App-Seite</Button>
            </div>
          ) : !address?.embeddable ? (
            <div className="mx-auto max-w-lg space-y-3 p-6">
              <Notice tone="info">{address?.reason}</Notice>
              {address?.url && (
                <Button variant="primary" onClick={() => window.open(address.url!, '_blank', 'noopener')}>
                  <ExternalLink className="size-4" /> In neuem Tab öffnen
                </Button>
              )}
            </div>
          ) : (
            // Some apps forbid being embedded; the "Neuer Tab" button in the header stays available for them.
            <iframe
              key={reload}
              ref={frame}
              src={address.url!}
              title={app.name}
              className="absolute inset-0 size-full border-0 bg-white"
              allow="fullscreen; clipboard-read; clipboard-write; autoplay; camera; microphone"
            />
          )}
        </div>
      </div>
    </section>
  );
}
