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

// "We had a session and the server rejected it" — distinct from "never connected".
// Both render the same login gate, but the wording differs: a user who has been
// logged out by an expiry needs to be told that's what happened, not invited to
// log in as if for the first time.
let expired = false;
const expiredListeners = new Set<(v: boolean) => void>();

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

export const getLuatoolsExpired = (): boolean => expired;

export const setLuatoolsExpired = (v: boolean): void => {
  if (expired === v) return;
  expired = v;
  expiredListeners.forEach((l) => l(expired));
};

export const subscribeLuatoolsExpired = (
  l: (v: boolean) => void,
): (() => void) => {
  expiredListeners.add(l);
  return () => {
    expiredListeners.delete(l);
  };
};
