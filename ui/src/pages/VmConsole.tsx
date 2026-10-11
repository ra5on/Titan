import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Maximize2, Power, RotateCw } from 'lucide-react';
import { action } from '../api';
import type { VmList } from '../api';
import { go, message, useApi } from '../lib';
import { Button, IconButton, Loading, Notice, StateDot, useToast } from '../ui';

/** A virtual machine's screen inside Titan instead of a separate browser tab. */
export function VmConsole({ vmId }: { vmId: string }) {
  const toast = useToast();
  const vms = useApi<VmList>('/api/vms', 5000);
  const vm = vms.data?.vms.find(item => item.id === vmId);
  const [busy, setBusy] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const label = vm?.display_name || vm?.name || 'Virtuelle Maschine';
  const running = vm?.state === 'running';

  // The embedded console asks its host page to go back when the VM is gone.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin === window.location.origin && event.data?.type === 'titan-console-back') go('vms');
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const run = async (command: string, done: string) => {
    setBusy(true);
    try {
      await action('vm_action', { vm: vmId, action: command });
      toast(`${label}: ${done}`);
    } catch (reason) {
      toast(`${label}: ${message(reason)}`, true);
    } finally {
      setBusy(false);
      await vms.reload();
    }
  };

  return (
    <section className="mx-auto flex h-full w-full max-w-[110rem] flex-col px-2 pb-24 pt-2 sm:px-4 sm:pt-4">
      <div className="glass flex min-h-0 flex-1 flex-col overflow-hidden rounded-3xl shadow-2xl animate-rise">
        <header className="flex flex-wrap items-center gap-2 border-b border-white/8 px-3 py-2">
          <IconButton label="Zurück zu den virtuellen Maschinen" onClick={() => go('vms')}>
            <ArrowLeft className="size-5" />
          </IconButton>
          <h1 className="flex min-w-0 flex-1 items-center gap-2 truncate text-sm font-semibold">
            {vm && <StateDot state={busy ? 'restarting' : vm.state} />}
            <span className="truncate">{label}</span>
          </h1>
          {running && (
            <>
              <Button size="sm" variant="ghost" busy={busy} onClick={() => run('shutdown', 'Herunterfahren angefordert.')}>
                <Power className="size-4" /> Herunterfahren
              </Button>
              <IconButton label="Neu starten" disabled={busy} onClick={() => run('reboot', 'Neustart angefordert.')}>
                <RotateCw className="size-4" />
              </IconButton>
              <IconButton label="Vollbild" onClick={() => stage.current?.requestFullscreen?.()}>
                <Maximize2 className="size-4" />
              </IconButton>
            </>
          )}
        </header>
        <div ref={stage} className="relative min-h-0 flex-1 bg-black">
          {vms.loading ? (
            <Loading />
          ) : !vm ? (
            <div className="mx-auto max-w-lg p-6"><Notice>Diese virtuelle Maschine gibt es nicht mehr.</Notice></div>
          ) : !running ? (
            <div className="mx-auto max-w-lg space-y-3 p-6">
              <Notice tone="info">{label} ist ausgeschaltet. Die Konsole erscheint, sobald die VM läuft.</Notice>
              <Button variant="primary" busy={busy} onClick={() => run('start', 'gestartet.')}>Starten</Button>
            </div>
          ) : (
            <iframe
              src={`/console.html?${new URLSearchParams({ vm: vm.id, embedded: '1', name: label })}`}
              title={`Konsole von ${label}`}
              className="absolute inset-0 size-full border-0"
              allow="fullscreen; clipboard-read; clipboard-write"
            />
          )}
        </div>
      </div>
    </section>
  );
}
