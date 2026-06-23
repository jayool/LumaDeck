# Updating LumaDeck

## The plugin itself

LumaDeck is sideloaded, so it doesn't auto-update through Decky's store. It has
an **in-plugin self-update** instead, in **Settings ▸ About**:

1. **Check for Updates** — queries the latest GitHub release and compares it to
   your installed version.
2. If newer, **Update Now (vX.Y.Z)** downloads the release zip and applies it.
3. Restart Steam to finish — Decky reloads the plugin.

If files are in use during the update, the new zip is **staged and applied on
the next start** instead of clobbering the running plugin. A background
auto-check is intentionally **off by default**; the manual button is the
supported path.

> Your installed and latest versions are shown at the top of the About panel.

## The components

The bundled components (SLSsteam, lumalinux, CloudRedirect) update
independently of the plugin. When a newer component release is available and the
component is otherwise healthy, LumaDeck surfaces an **info notice** (blue) on
the main page and in Dependencies. The update button itself lives in **Settings
▸ Dependencies** — tap the matching *Install / Reapply* action.

A **broken** component (red) is different from an **update available** (blue):
the red banner means it needs repair now; the blue notice is routine. See
[Components & health](components-and-health.md).

## After a Steam / SteamOS update

A client update can break the hooks (build-ID or byte-pattern mismatch). Reapply
the affected component from Dependencies; if Game Mode blocks it, run it from
Desktop. Details in [Troubleshooting](troubleshooting.md).
