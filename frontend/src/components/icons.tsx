// Inline icons from the F7 generator plus a few product additions. All decorative (aria-hidden).
/** Роман P2-1: the DELTAHEAT mark (deltaheat-icon.svg, no background): heat rising over the blue forest base. */
export const Logo = () => (
  <svg width="30" height="28" viewBox="116 74 280 256" aria-hidden="true" data-testid="logo">
    <defs>
      <linearGradient id="dh-tr" x1="256" y1="84" x2="365" y2="318" gradientUnits="userSpaceOnUse"><stop offset="0%" stopColor="#ff2e93" /><stop offset="50%" stopColor="#ff5aa8" /><stop offset="100%" stopColor="#ff8a3d" /></linearGradient>
      <linearGradient id="dh-tl" x1="256" y1="90" x2="175" y2="290" gradientUnits="userSpaceOnUse"><stop offset="0%" stopColor="#ff7744" /><stop offset="50%" stopColor="#ff5aa8" /><stop offset="100%" stopColor="#e02e88" /></linearGradient>
      <linearGradient id="dh-fb" x1="138" y1="295" x2="256" y2="145" gradientUnits="userSpaceOnUse"><stop offset="0%" stopColor="#4e73ff" /><stop offset="65%" stopColor="#7f9bff" /><stop offset="100%" stopColor="#9cb2ff" /></linearGradient>
      <linearGradient id="dh-fo" x1="140" y1="295" x2="340" y2="315" gradientUnits="userSpaceOnUse"><stop offset="0%" stopColor="#3c5fe6" /><stop offset="100%" stopColor="#708eff" /></linearGradient>
    </defs>
    <g strokeLinejoin="round" strokeLinecap="round">
      <path d="M 212 124 L 134 260 Q 127 272 134 284 L 148 308 Q 154 318 166 318 L 180 290 L 234 162 Z" fill="url(#dh-fb)" />
      <path d="M 234 92 Q 239 84 248 84 L 264 84 L 282 116 L 182 290 L 150 290 L 234 142 Z" fill="url(#dh-tl)" />
      <path d="M 134 284 L 148 308 Q 154 318 166 318 L 322 318 L 338 290 L 137 290 Z" fill="url(#dh-fo)" />
      <path d="M 234 92 Q 239 84 248 84 L 264 84 Q 273 84 278 92 L 378 266 Q 385 278 378 290 L 364 310 Q 358 318 346 318 L 318 318 L 334 290 L 234 116 Z" fill="url(#dh-tr)" />
    </g>
  </svg>
);
export const SearchIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="6" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M13 13l5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
);
export const ChatIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M3 3h12v9H8l-4 3v-3H3z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
);
export const Arrow = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M6 3l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
);
export const Back = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3L5 8l5 5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
);
export const Close = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
);
export const Auto = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M9 2.5a6.5 6.5 0 0 1 0 13z" fill="currentColor" /></svg>
);
export const PolyIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6l7-3 6 6-3 8-9-2z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><circle cx="4" cy="6" r="1.8" fill="currentColor" /><circle cx="11" cy="3" r="1.8" fill="currentColor" /><circle cx="17" cy="9" r="1.8" fill="currentColor" /><circle cx="14" cy="17" r="1.8" fill="currentColor" /><circle cx="5" cy="15" r="1.8" fill="currentColor" /></svg>
);
export const CircleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeDasharray="3 2" /><circle cx="10" cy="10" r="1.8" fill="currentColor" /></svg>
);
export const Plus = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
);
export const Minus = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
);

/** «Вся Україна»: a frame with a dot (fit the country). */
export const UaIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
    <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" /><circle cx="8" cy="8" r="2" fill="currentColor" stroke="none" />
  </svg>
);
export const Chevron = ({ dir = 'left' }: { dir?: 'left' | 'right' }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d={dir === 'left' ? 'M10 3L5 8l5 5' : 'M6 3l5 5-5 5'} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
);
