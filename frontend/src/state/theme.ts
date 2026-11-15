import { useEffect } from 'react';

/**
 * Dark only (user decision): no light mode is reachable. prefers-color-scheme is ignored.
 * public/boot.js sets the attribute before first paint and clears a legacy stored 'light'.
 */
export type Theme = 'dark';

export function useDarkTheme(): 'dark' {
  useEffect(() => {
    document.documentElement.dataset.theme = 'dark';
  }, []);
  return 'dark';
}
