# Updating LumaDeck

## The plugin itself

LumaDeck is sideloaded, so it doesn't auto-update through Decky's store. Two
ways to update it:

- **In-plugin** — in **Settings ▸ About**, tap **Check for Updates**, then
  **Update Now** if a newer release exists. It downloads the latest release,
  overwrites the plugin on disk, and restarts Steam so the new version loads
  (the running code stays in memory until then).
- **Manually via Decky** — reinstall the latest `LumaDeck.zip` from Decky's
  developer mode, the same way you first sideloaded it. Decky reloads the plugin
  itself, so no Steam restart is needed.

LumaDeck **never auto-installs**: it checks on its own and surfaces a notice (in
the QAM update banner and Settings ▸ About), but applying an update is always a
manual action.

> Your installed and latest versions are shown at the top of the About panel.

### Your credentials survive it

Updating replaces the whole plugin directory, which wipes the files LumaDeck
keeps there — including your Hubcap key, Ryuu cookie and LuaTools session. They
come back: each one is mirrored into the plugin's *settings* directory, which
Decky leaves alone, and restored on the next load.

The LuaTools session only joined that list in v0.7.4. Before it, every single
update quietly signed you out of LuaTools and you had to log in again. See
[Credentials](credentials.md#where-the-values-live).

## The components

The bundled components (SLSsteam, lumalinux, CloudRedirect) update
independently of the plugin. When a newer component release is available and the
component is otherwise healthy, LumaDeck surfaces an **info notice** (blue) on
the main page and in Components. The update button itself lives in **Settings
▸ Components**: press the matching *Install / Reinstall Components* action.

A **broken** component (amber or red) is different from an **update available**
(blue): the broken status means it needs repair now; the blue notice is routine.
See [Components & health](components-and-health.md).

## After a Steam / SteamOS update

A client update can break the hooks (build-ID or byte-pattern mismatch), which
shows as `not_supported`. Fix it with **Fix in Desktop**; if Game Mode blocks
it, it runs from Desktop. Details in [Troubleshooting](troubleshooting.md).
