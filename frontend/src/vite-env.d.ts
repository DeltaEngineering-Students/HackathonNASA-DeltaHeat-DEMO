/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_API_MODE?: 'live' | 'fixtures' | 'auto';
}
declare module '*?worker&url' {
  const url: string;
  export default url;
}
