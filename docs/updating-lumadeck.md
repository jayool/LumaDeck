# Updating LumaDeck

## The plugin itself

LumaDeck is sideloaded, so it doesn't auto-update through Decky's store. It has
an **in-plugin self-update** instead, in **Settings ▸ About**:

1. **Check for Updates** — queries the latest GitHub release and compares it to
   your installed version.
2. If newer, **Update Now (vX.Y.Z)** downloads the release zip and applies it.
3. Restart Steam to finish — Decky reloads the plugin.

The update **overwrites the plugin's files in place**. On Linux that's safe even
while LumaDeck is running — the loaded code keeps running and the new files take
effect on the next Steam restart. Only if that overwrite *fails* is the zip
**staged** (saved in the settings dir, which survives the overwrite) and applied
automatically on the next plugin load.

LumaDeck **never auto-installs** updates. It does check on its own and surface a
notice (in the QAM update banner and Settings ▸ About), but applying one is
always the manual **Update Now** button.

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
