import { takePrefetch, viaPrefetch } from './prefetch';

describe('early prefetch (QA R3-3)', () => {
  afterEach(() => { delete (window as unknown as { __uhdPre?: unknown }).__uhdPre; });
  it('hands each promise out once and only for the prefetched zone', async () => {
    (window as unknown as { __uhdPre: unknown }).__uhdPre = { meta: Promise.resolve({ a: 1 }), zone: 'kyiv-pozniaky', analyze: Promise.resolve({ r: 1 }) };
    expect(takePrefetch('analyze', 'kyiv-obolon')).toBeUndefined();
    expect(await takePrefetch('analyze', 'kyiv-pozniaky')).toEqual({ r: 1 });
    expect(takePrefetch('analyze', 'kyiv-pozniaky')).toBeUndefined();
    expect(await takePrefetch('meta')).toEqual({ a: 1 });
  });
  it('falls back to a normal request when the prefetch failed', async () => {
    const failed = Promise.reject(new Error('down'));
    failed.catch(() => undefined);
    expect(await viaPrefetch(failed, async () => 'fresh')).toBe('fresh');
    expect(await viaPrefetch(undefined, async () => 'fresh')).toBe('fresh');
  });
});
