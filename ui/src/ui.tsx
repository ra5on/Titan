import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, X } from 'lucide-react';
import { cx } from './lib';

/* ---------- Buttons ---------- */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
  busy?: boolean;
};

const variants = {
  primary: 'bg-brand text-white hover:bg-brand-strong',
  secondary: 'bg-white/10 text-white hover:bg-white/16',
  ghost: 'text-white/80 hover:bg-white/10 hover:text-white',
  danger: 'bg-bad/15 text-bad hover:bg-bad/25',
};

export function Button({ variant = 'secondary', size = 'md', busy, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || busy}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3.5 text-[13px]' : 'h-10 px-5 text-sm',
        variants[variant],
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function IconButton({ label, className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...rest}
      className={cx(
        'inline-flex size-9 items-center justify-center rounded-full text-white/75 transition-colors hover:bg-white/10 hover:text-white',
        'focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-40',
        className,
      )}
    >
      {children}
    </button>
  );
}

/* ---------- Form controls ---------- */

const control =
  'h-11 w-full rounded-xl border border-white/10 bg-white/6 px-3.5 text-sm text-white placeholder:text-white/35 ' +
  'outline-none transition-colors focus:border-brand focus:bg-white/10';

export function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-white/70">{label}</span>
      {children}
      {help && <span className="mt-1.5 block text-xs leading-relaxed text-white/45">{help}</span>}
    </label>
  );
}

export const Input = (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} className={cx(control, props.className)} />;

export const Select = (props: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select {...props} className={cx(control, 'appearance-none [&>option]:bg-slate-900', props.className)} />
);

/* ---------- Feedback ---------- */

export const Spinner = ({ className }: { className?: string }) => (
  <Loader2 className={cx('animate-spin text-white/60', className || 'size-6')} aria-label="Lädt" />
);

export function Loading() {
  return (
    <div className="flex h-48 items-center justify-center">
      <Spinner />
    </div>
  );
}

export function Notice({ tone = 'bad', children }: { tone?: 'bad' | 'warn' | 'info'; children: ReactNode }) {
  const tones = { bad: 'bg-bad/12 text-bad', warn: 'bg-warn/12 text-warn', info: 'bg-white/8 text-white/75' };
  return (
    <div role={tone === 'bad' ? 'alert' : 'status'} className={cx('flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-sm', tones[tone])}>
      {tone !== 'info' && <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}
      <div className="min-w-0 leading-relaxed">{children}</div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      <p className="text-base font-medium text-white/85">{title}</p>
      {children && <div className="max-w-sm text-sm leading-relaxed text-white/50">{children}</div>}
    </div>
  );
}

export function Meter({ value, tone }: { value: number; tone?: 'ok' | 'warn' | 'bad' }) {
  const resolved = tone || (value >= 90 ? 'bad' : value >= 75 ? 'warn' : 'ok');
  const colors = { ok: 'bg-brand', warn: 'bg-warn', bad: 'bg-bad' };
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cx('h-full rounded-full transition-[width] duration-500', colors[resolved])} style={{ width: `${value}%` }} />
    </div>
  );
}

export function StateDot({ state }: { state: string }) {
  const running = state === 'running';
  const transitional = ['restarting', 'paused', 'created', 'in shutdown'].includes(state);
  return <span className={cx('inline-block size-2 rounded-full', running ? 'bg-ok' : transitional ? 'bg-warn' : 'bg-white/30')} aria-hidden />;
}

/* ---------- App icon ---------- */

export function AppIcon({ id, name, color, size = 72 }: { id: string; name: string; color?: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const key = id.replace(/^titan-/, '');
  const radius = Math.round(size * 0.24);
  if (broken) {
    return (
      <div
        className="flex shrink-0 items-center justify-center font-semibold text-white shadow-lg shadow-black/30"
        style={{ width: size, height: size, borderRadius: radius, fontSize: size * 0.42, background: `linear-gradient(145deg, ${color || '#5b8cff'}, #1f2a4d)` }}
        aria-hidden
      >
        {name.slice(0, 1).toUpperCase()}
      </div>
    );
  }
  return (
    <img
      src={`/app-icons/${encodeURIComponent(key)}.svg`}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setBroken(true)}
      className="shrink-0 object-cover shadow-lg shadow-black/30"
      style={{ width: size, height: size, borderRadius: radius }}
    />
  );
}

/* ---------- Modal ---------- */

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-close])')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/55 p-0 animate-fade sm:items-center sm:p-6" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx('glass scroll-area max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl p-6 shadow-2xl animate-rise sm:rounded-3xl', wide ? 'sm:max-w-2xl' : 'sm:max-w-md')}
      >
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <IconButton label="Schließen" onClick={onClose} data-close>
            <X className="size-5" />
          </IconButton>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, text, confirmLabel, danger, onConfirm, onClose }: { title: string; text: ReactNode; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<void> | void; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="text-sm leading-relaxed text-white/70">{text}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Abbrechen
        </Button>
        <Button
          variant={danger ? 'danger' : 'primary'}
          busy={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              onClose();
            } finally {
              setBusy(false);
            }
          }}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

/* ---------- Toasts ---------- */

type Toast = { id: number; text: string; bad: boolean };
const ToastContext = createContext<(text: string, bad?: boolean) => void>(() => undefined);
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(0);
  const push = useCallback((text: string, bad = false) => {
    const id = ++next.current;
    setToasts(list => [...list.slice(-3), { id, text, bad }]);
    window.setTimeout(() => setToasts(list => list.filter(item => item.id !== id)), bad ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-2 px-4" aria-live="polite">
        {toasts.map(toast => (
          <div key={toast.id} className="glass pointer-events-auto flex max-w-md items-start gap-2.5 rounded-2xl px-4 py-3 text-sm shadow-xl animate-rise">
            {toast.bad ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-bad" /> : <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" />}
            <span className="leading-relaxed">{toast.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/* ---------- Page sheet ---------- */

export function Sheet({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="mx-auto flex h-full w-full max-w-6xl flex-col px-3 pt-3 sm:px-6 sm:pt-6">
      <div className="glass flex min-h-0 flex-1 flex-col overflow-hidden rounded-t-[28px] shadow-2xl animate-rise">
        <header className="flex flex-wrap items-center justify-between gap-3 px-5 pb-4 pt-5 sm:px-8 sm:pt-7">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold tracking-tight sm:text-[28px]">{title}</h1>
            {subtitle && <p className="mt-1 truncate text-sm text-white/50">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
        <div className="scroll-area min-h-0 flex-1 overflow-y-auto px-5 pb-32 sm:px-8">{children}</div>
      </div>
    </section>
  );
}

export const Card = ({ className, children }: { className?: string; children: ReactNode }) => (
  <div className={cx('glass-soft rounded-2xl p-5', className)}>{children}</div>
);
