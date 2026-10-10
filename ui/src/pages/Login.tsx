import { useState } from 'react';
import type { FormEvent } from 'react';
import { post } from '../api';
import type { Session } from '../api';
import { message } from '../lib';
import { Button, Field, Input, Notice } from '../ui';

export function Login({ session, onDone }: { session: Session; onDone: () => Promise<void> }) {
  const setup = session.setup_required;
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [otp, setOtp] = useState('');
  const [needOtp, setNeedOtp] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    if (setup && password !== repeat) {
      setError('Die beiden Passwörter stimmen nicht überein.');
      return;
    }
    setBusy(true);
    try {
      if (setup) await post('/api/setup', { name, password }, session.setup_csrf || '');
      await post('/api/login', { name, password, ...(otp ? { otp } : {}) }, '');
      await onDone();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center overflow-y-auto p-4">
      <form onSubmit={submit} className="glass w-full max-w-sm rounded-[28px] p-8 shadow-2xl animate-rise">
        <img src="/logo.svg" alt="" className="mx-auto size-16 rounded-2xl bg-white p-2.5 shadow-lg shadow-black/30" />
        <h1 className="mt-5 text-center text-2xl font-semibold tracking-tight">{setup ? 'Willkommen bei Titan' : 'Anmelden'}</h1>
        <p className="mt-2 text-center text-sm text-white/55">
          {setup ? 'Lege das Administratorkonto für dieses NAS an.' : 'Melde dich mit deinem Titan-Konto an.'}
        </p>
        <div className="mt-7 space-y-4">
          <Field label="Benutzername" help={setup ? 'Kleinbuchstaben, Ziffern, - und _; beginnt mit einem Buchstaben.' : undefined}>
            <Input value={name} onChange={event => setName(event.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required />
          </Field>
          <Field label="Passwort">
            <Input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete={setup ? 'new-password' : 'current-password'} required />
          </Field>
          {setup && (
            <Field label="Passwort wiederholen">
              <Input type="password" value={repeat} onChange={event => setRepeat(event.target.value)} autoComplete="new-password" required />
            </Field>
          )}
          {!setup && needOtp && (
            <Field label="Sicherheitscode" help="Sechsstelliger Code aus der Authenticator-App oder ein Wiederherstellungscode.">
              <Input value={otp} onChange={event => setOtp(event.target.value)} autoComplete="one-time-code" inputMode="numeric" autoFocus />
            </Field>
          )}
          {!setup && !needOtp && (
            <button type="button" onClick={() => setNeedOtp(true)} className="text-[13px] text-white/50 underline-offset-4 hover:text-white/80 hover:underline">
              Zwei-Faktor-Code eingeben
            </button>
          )}
          {error && <Notice>{error}</Notice>}
        </div>
        <Button type="submit" variant="primary" busy={busy} className="mt-7 w-full">
          {setup ? 'Konto anlegen' : 'Anmelden'}
        </Button>
        {session.demo && <p className="mt-4 text-center text-xs text-white/40">Demo-Modus</p>}
      </form>
    </div>
  );
}
