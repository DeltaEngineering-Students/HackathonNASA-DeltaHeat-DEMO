// Requests started by the inline script in index.html before the bundle loads (QA R3-3).
// Each promise is handed out once; callers fall back to a normal request if it is missing or failed.
interface Pre { meta?: Promise<unknown>; zone?: string; place?: Promise<unknown>; analyze?: Promise<unknown> }

const pre = (): Pre | undefined => (typeof window === 'undefined' ? undefined : (window as unknown as { __uhdPre?: Pre }).__uhdPre);

export function takePrefetch(kind: 'meta'): Promise<unknown> | undefined;
export function takePrefetch(kind: 'place' | 'analyze', zone: string): Promise<unknown> | undefined;
export function takePrefetch(kind: 'meta' | 'place' | 'analyze', zone?: string): Promise<unknown> | undefined {
  const p = pre();
  if (!p) return undefined;
  if (kind !== 'meta' && p.zone !== zone) return undefined;
  const v = p[kind];
  p[kind] = undefined;
  return v;
}

/** Use a prefetched JSON promise if there is one, otherwise (or if it failed) run `fallback`. */
export async function viaPrefetch<T>(pending: Promise<unknown> | undefined, fallback: () => Promise<T>): Promise<T> {
  if (pending) {
    try { return (await pending) as T; } catch { /* fall through to a normal request */ }
  }
  return fallback();
}
