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
