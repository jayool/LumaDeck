import { useCallback, useEffect, useState } from "react";
import { Navigation } from "@decky/ui";

import { connectLuatools, disconnectLuatools, getLuatoolsStatus } from "../api";

type Toast = (title: string, body?: string, duration?: number) => void;
type Translate = (key: string, ...args: any[]) => string;

/**
 * Shared LuaTools connection flow, used by both the Settings credential row
 * (canonical connect/disconnect) and the GameDetail Fixes tab (contextual
 * "connect to apply" prompt). Centralises the Game-Mode browser login →
 * cookie-harvest → auto-close dance so the two call sites don't drift.
 *
 * `connect()` opens the lua.tools login in the built-in browser; the backend
 * polls the CEF cookie store and captures the Supabase session as soon as it
 * appears, then we close the browser. If the caller unmounts during the nav the
 * backend still saves the session, and the next status refresh reflects it.
 */
export function useLuatoolsConnect(toast: Toast, t: Translate) {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);

  const refresh = useCallback(async () => {
    const r = await getLuatoolsStatus();
    const c = !!(r?.success && r.connected);
    setConnected(c);
    return c;
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const connect = useCallback(async (): Promise<boolean> => {
    setConnecting(true);
    Navigation.NavigateToExternalWeb("https://lua.tools/");
    try {
      const res = await connectLuatools(); // resolves when captured (or timeout)
      if (res?.success) {
        Navigation.NavigateBack(); // close the browser, back to the caller
        setConnected(true);
        toast("LuaTools connected ✓"); // TODO i18n
        return true;
      } else if (!res?.cancelled) {
        toast(t("toastError"), "LuaTools login timed out", 5000);
      }
    } catch {
      /* component unmounted during nav; backend saved the session anyway */
    } finally {
      setConnecting(false);
    }
    return false;
  }, [toast, t]);

  const disconnect = useCallback(async () => {
    await disconnectLuatools();
    setConnected(false);
    toast("LuaTools disconnected"); // TODO i18n
  }, [toast]);

  return { connected, connecting, connect, disconnect, refresh, setConnected };
}
