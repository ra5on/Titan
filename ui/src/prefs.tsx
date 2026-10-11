import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { get, post } from './api';

export type Prefs = {
  transparency: number;
  dock_size: 'small' | 'medium' | 'large';
  dock: string[];
  widgets: ('cpu' | 'ram' | 'storage')[];
  hidden_apps: string[];
  pinned_vms: string[];
};

export const DEFAULT_PREFS: Prefs = {
  transparency: 40,
  dock_size: 'medium',
  dock: ['tool:home', 'tool:store', 'tool:files', 'tool:vms', 'tool:settings'],
  widgets: ['cpu', 'ram', 'storage'],
  hidden_apps: [],
  pinned_vms: [],
};

/** Glass surfaces get more see-through as the transparency rises. */
export function applyTransparency(transparency: number) {
  document.documentElement.style.setProperty('--glass-alpha', (0.96 - (transparency / 100) * 0.72).toFixed(3));
}

type Value = { prefs: Prefs; save: (prefs: Prefs) => Promise<void> };
const PrefsContext = createContext<Value>({ prefs: DEFAULT_PREFS, save: async () => undefined });
export const usePrefs = () => useContext(PrefsContext);

/** Per-account appearance, loaded once after sign-in. Defaults apply until then and if loading fails. */
export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);

  useEffect(() => {
    let stale = false;
    get<Prefs>('/api/interface')
      .then(value => !stale && setPrefs({ ...DEFAULT_PREFS, ...value }))
      .catch(() => undefined);
    return () => {
      stale = true;
    };
  }, []);

  useEffect(() => applyTransparency(prefs.transparency), [prefs.transparency]);

  const save = useCallback(async (next: Prefs) => {
    setPrefs(await post<Prefs>('/api/interface', next));
  }, []);

  return <PrefsContext.Provider value={{ prefs, save }}>{children}</PrefsContext.Provider>;
}
