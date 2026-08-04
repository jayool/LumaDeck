import { useCallback, useEffect, useState } from "react";
import { Navigation } from "@decky/ui";

import { connectLuatools, disconnectLuatools, getLuatoolsStatus } from "../api";
import { closeLoginBrowser } from "../browserLogin";
import {
  getLuatoolsConnected,
  setLuatoolsConnected,
  subscribeLuatoolsConnected,
} from "../luatoolsConnection";

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
  // Mirror the shared module state (null = not resolved yet). Every hook instance
  // subscribes, so a connect/disconnect/refresh anywhere updates all of them.
  const [connected, setConnectedLocal] = useState<boolean | null>(
    getLuatoolsConnected(),
  );
  const [connecting, setConnecting] = useState(false);

  useEffect(() => subscribeLuatoolsConnected(setConnectedLocal), []);

  const refresh = useCallback(async () => {
    const r = await getLuatoolsStatus();
    const c = !!(r?.success && r.connected);
    setLuatoolsConnected(c); // → notifies every subscribed instance
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
        closeLoginBrowser(); // pop /externalweb off the main window's backstack
        setLuatoolsConnected(true);
        toast("LuaTools connected ✓"); // TODO i18n
        return true;
      } else if (!res?.cancelled) {
        toast(t("toastError"), "LuaTools login timed out — try again", 5000);
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
    setLuatoolsConnected(false);
    toast("LuaTools disconnected"); // TODO i18n
  }, [toast]);

  return {
    connected,
    connecting,
    connect,
    disconnect,
    refresh,
    setConnected: setLuatoolsConnected,
  };
}
