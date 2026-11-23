// Small pure formatters shared by the pages (kept free of @decky imports so
// they can be unit-tested).

// "3:07" for 187 s: what the Quick Install row shows as time elapsed.
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const sec = total % 60;
  return `${m}:${sec < 10 ? "0" : ""}${sec}`;
}
