// Shared LuaTools connection state across the separate React trees (the Settings
// credential row and the GameDetail Fixes/Online tabs). Same lightweight
// module-observable pattern as refresh.ts — a module-level value + a Set of
// listeners — so both trees stay in sync live: connect in Settings and the
// GameDetail fix gate reflects it immediately, without waiting for its own
// backend re-read.
//
// The backend (luatools_session.json) is still the source of truth; this is just
// an in-memory mirror. `null` = not resolved yet (first refresh hasn't returned);
// true/false once known. Because it lives at module scope it persists across
// component mounts, so after the first load a freshly opened GameDetail already
// knows the state on its first render — no desync window.
let connected: boolean | null = null;
const listeners = new Set<(v: boolean | null) => void>();

export const getLuatoolsConnected = (): boolean | null => connected;

export const setLuatoolsConnected = (v: boolean | null): void => {
  if (connected === v) return;
  connected = v;
  listeners.forEach((l) => l(connected));
};

export const subscribeLuatoolsConnected = (
  l: (v: boolean | null) => void,
): (() => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
