# Cloud saves (CloudRedirect)

[CloudRedirect](https://github.com/Selectively11/CloudRedirect) redirects Steam
Cloud save traffic to a third-party provider (Google Drive / OneDrive /
Dropbox), so cloud saves keep working for games added through LumaDeck. It is
**optional**.

## Enable it

In **Settings ▸ Dependencies**, tap **Enable CloudRedirect**. This flips
`DisableCloud: yes → no` in SLSsteam's config and installs the CloudRedirect
Flatpak plus its `cloud_redirect.so` hook (via Headcrab). It ends with a Steam
restart.

After this the **library is in place but no provider is signed in** — the
Dependencies panel shows CloudRedirect as `not_authed`.

## Sign into a provider

The provider sign-in opens a real OAuth browser flow, which Game Mode can't
drive today. So, once:

1. Switch to **Desktop mode**.
2. Open the **CloudRedirect** app from the application menu.
3. Sign into Google Drive / OneDrive / Dropbox.

The tokens land at `~/.config/CloudRedirect/tokens_<provider>.json`. Back in
LumaDeck, the panel then shows **CloudRedirect provider: Configured** and the
health state flips to `healthy`.

## Roadmap

Driving that sign-in **entirely from Game Mode** (no Desktop trip) is tracked in
[issue #25](https://github.com/jayool/LumaDeck/issues/25). The key finding: the
32-bit `.so` that consumes the tokens reads the plain
`tokens_<provider>.json` file directly and never touches the OS keyring — so
LumaDeck only needs to write that file. Not implemented yet.

## Related

- [lumalinux cloudredirect docs](https://github.com/jayool/lumalinux/blob/main/docs/cloudredirect.md) — `LD_PRELOAD` ordering when running alongside the Flatpak.
