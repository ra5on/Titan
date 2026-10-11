import { useEffect, useState } from 'react';
import { post } from '../api';
import { message, useApi } from '../lib';
import { Button, Field, Input, Modal, Notice, Select } from '../ui';

type Access = { enabled: boolean; expires?: number; two_factor_required?: boolean; demo?: boolean };

export function RootAccess({ onChange }: { onChange: (enabled: boolean) => void }) {
  const state = useApi<Access>('/api/root-access', 5000);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [minutes, setMinutes] = useState('15');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { onChange(state.data?.enabled === true); }, [state.data?.enabled, onChange]);
  const change = async (enable: boolean) => {
    setBusy(true); setError('');
    try {
      await post('/api/root-access', enable ? { password, ...(otp ? { otp } : {}), minutes: Number(minutes) } : { enabled: false });
      setPassword(''); setOtp(''); setOpen(false); await state.reload();
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  const close = () => { if (!busy) { setOpen(false); setPassword(''); setOtp(''); } };
  return <div className="mb-4 space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 p-3 text-sm">
      <span>{state.data?.enabled ? `Root-Modus${state.data.demo ? ' · Demo' : ''} · bis ${new Date((state.data.expires || 0) * 1000).toLocaleTimeString('de')}` : 'Geschützter NAS-Modus'}</span>
      <Button size="sm" busy={busy} disabled={state.loading || !!state.error} onClick={() => state.data?.enabled ? void change(false) : setOpen(true)}>{state.data?.enabled ? 'Root-Modus beenden' : 'Root-Modus aktivieren'}</Button>
    </div>
    {(state.error || error && !open) && <Notice>{state.error || error}</Notice>}
    {open && <Modal title="Root-Modus aktivieren" onClose={close}>
      <form className="space-y-4" onSubmit={event => { event.preventDefault(); void change(true); }}>
        <p className="text-sm text-white/70">Root hat vollständige Administratorrechte. Befehle und Systemdateien können das NAS verändern. Schreibgeschützte Systembereiche bleiben geschützt; manuelle Systemänderungen können bei Updates verloren gehen.</p>
        {state.data?.demo && <Notice tone="info">Isolierte Demo: Keine Root-Befehle auf diesem Rechner.</Notice>}
        <Field label="Aktuelles Passwort"><Input type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></Field>
        {state.data?.two_factor_required && <Field label="Authenticator- oder Wiederherstellungscode"><Input autoComplete="one-time-code" required value={otp} onChange={event => setOtp(event.target.value)} /></Field>}
        <Field label="Dauer"><Select value={minutes} onChange={event => setMinutes(event.target.value)}>{[5, 15, 30].map(value => <option key={value} value={value}>{value} Minuten</option>)}</Select></Field>
        {error && <Notice>{error}</Notice>}
        <div className="flex justify-end gap-2"><Button disabled={busy} onClick={close}>Abbrechen</Button><Button type="submit" variant="primary" busy={busy}>Root-Modus aktivieren</Button></div>
      </form>
    </Modal>}
  </div>;
}
