// Bridge so the Refresh icon in the native titleView (index.tsx) can trigger
// GameList's reload. They live in separate React trees, so GameList registers
// its loader here on mount and the titleView calls requestRefresh().
let handler: (() => void) | null = null;

export const setRefreshHandler = (fn: (() => void) | null) => {
  handler = fn;
};

export const requestRefresh = () => {
  handler?.();
};

// Whether a status refresh is currently running. GameList drives this around its
// reload (on open AND on a manual Refresh press); the title-bar Refresh icon
// (index.tsx, a separate React tree) subscribes so it can spin while it works.
let refreshing = false;
const listeners = new Set<(b: boolean) => void>();

export const setRefreshing = (b: boolean) => {
  if (refreshing === b) return;
  refreshing = b;
  listeners.forEach((l) => l(refreshing));
};

export const getRefreshing = () => refreshing;

export const subscribeRefreshing = (l: (b: boolean) => void): (() => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
