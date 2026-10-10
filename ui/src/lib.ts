import { useCallback, useEffect, useRef, useState } from 'react';
import { get } from './api';

export function bytes(value: number | undefined | null) {
  if (value == null || !Number.isFinite(value)) return '–';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let index = 0;
  let amount = value;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index++;
  }
  return `${amount.toLocaleString('de-DE', { maximumFractionDigits: amount >= 100 || index === 0 ? 0 : 1 })} ${units[index]}`;
}

export function duration(seconds: number) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days) return `${days} T ${hours} Std`;
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} Std ${minutes} Min` : `${minutes} Min`;
}

export const dateTime = (epoch: number) =>
  new Date(epoch * 1000).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' });

export const percent = (used: number, total: number) => (total > 0 ? Math.min(100, Math.max(0, (used / total) * 100)) : 0);

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ');

/** Hash route as path segments: "#/store/titan-immich" -> ["store", "titan-immich"]. */
export function useRoute() {
  const read = () => window.location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const update = () => setRoute(read());
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return route;
}

export const go = (...segments: string[]) => {
  window.location.hash = '/' + segments.map(encodeURIComponent).join('/');
};

type Resource<T> = { data: T | null; error: string; loading: boolean; reload: () => Promise<void> };

/** Fetch a GET endpoint, optionally refreshing while the tab is visible. Stale data stays on a failed refresh. */
export function useApi<T>(path: string | null, intervalMs = 0): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(Boolean(path));
  const current = useRef(path);
  current.current = path;

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const value = await get<T>(path);
      if (current.current !== path) return;
      setData(value);
      setError('');
    } catch (reason) {
      if (current.current === path) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (current.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setData(null);
    setError('');
    setLoading(Boolean(path));
    void reload();
    if (!intervalMs || !path) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void reload();
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [path, intervalMs, reload]);

  return { data, error, loading, reload };
}

export const message = (reason: unknown) => (reason instanceof Error ? reason.message : String(reason));
