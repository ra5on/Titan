import { useEffect, useRef, useState } from 'react';
import type { Session } from '../api';
import { Button, Loading, Notice, useToast } from '../ui';
import { message } from '../lib';
import { createRuntime } from './runtime';
import type { Feature } from './features';
import './skin.css';

export function ManagementPanel({ feature, session }: { feature: Feature; session?: Session }) {
  const host = useRef<HTMLDivElement>(null);
  const modal = useRef<HTMLDialogElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  const toast = useToast();
  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    const ctx = createRuntime(host.current!, modal.current!, toast);
    setLoading(true); setError('');
    void import('./features').then(async ({ mountFeature }) => {
      if (disposed) return;
      cleanup = await mountFeature(feature, host.current!, ctx, session);
      if (disposed) cleanup?.();
      else setLoading(false);
    }).catch(reason => { if (!disposed) { setLoading(false); setError(message(reason)); } });
    return () => { disposed = true; ctx.dispose(); cleanup?.(); };
  }, [feature, session?.user?.name, session?.user?.role, attempt, toast]);
  return <div className="space-y-4">
    {loading && <Loading />}
    {error && <Notice>{error}<Button className="mt-3" onClick={() => retry(n => n + 1)}>Erneut laden</Button></Notice>}
    <p data-management-job role="status" hidden className="rounded-xl bg-white/8 px-4 py-3 text-sm text-white/75" />
    <div ref={host} className="management" />
    <dialog ref={modal} id="dialog" className="management management-modal" aria-labelledby="management-dialog-title"><div id="dialog-body" /></dialog>
  </div>;
}
