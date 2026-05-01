/// <reference types="vite/client" />

declare global {
  interface Window {
    __TAURI__?: {
      core?: {
        invoke: <T = unknown>(command: string, args?: Record<string, unknown>) => Promise<T>;
      };
      event?: {
        listen: <T = unknown>(
          event: string,
          handler: (payload: { event: string; payload: T }) => void,
        ) => Promise<() => void>;
      };
      dialog?: {
        open: (options: {
          title?: string;
          directory?: boolean;
          multiple?: boolean;
          defaultPath?: string;
        }) => Promise<string | string[] | null>;
      };
    };
  }
}

export {};
