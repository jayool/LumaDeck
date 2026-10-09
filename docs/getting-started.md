# Getting started

This is the short path from a fresh install to your first downloaded game.
For the full install walkthrough (downloading the zip, sideloading through
Decky), see the root [README → Installation](../README.md#installation).

LumaDeck lives in the **Quick Access Menu (QAM)**: press the **`•••`** button,
scroll to the LumaDeck icon, and open it. **Settings** is the gear icon in
LumaDeck's title bar; the arrows next to it refresh the status.

## 1. Set your credentials

LumaDeck fetches game manifests from manifest providers, which need a
credential. Open **Settings ▸ API Credentials** and set at least one:

- **Hubcap API key** — the main provider. See [Credentials](credentials.md#hubcap-api-key).
- **Ryuu** *(optional)* — a second provider. Tap **Log in with Discord**, sign in, and LumaDeck captures the session for you. See [Credentials](credentials.md#ryuu-cookie).

A status line under each field tells you whether the credential is valid and
when it expires.

## 2. Install the components

**First time (nothing installed yet):** the main LumaDeck page shows a
**Welcome** row with a **⚡ Quick Install** button. Tap it, then tap again to
confirm: it installs and configures every component in one pass, the
recommended path for a fresh setup. If your Steam is newer than the build the
hooks support, the confirm reads *continues in Desktop*: LumaDeck switches to
Desktop Mode, installs there and brings you back to Game Mode. (The row only
appears while none of the components are installed. After that, use the
button in **Settings ▸ Components**.)

To reinstall or repair later, open **Settings ▸ Components**. It shows one row
per component and **one** button at the bottom. **Install Components** on a
fresh device, or **Reinstall Components** once they are installed, runs lumalinux's
[`setup.sh`](https://github.com/jayool/lumalinux/blob/main/setup.sh) — one idempotent
pass that installs the whole stack (**SLSsteam + CloudRedirect + netsock + lumalinux**
plus the **.NET 9 runtime**), applies SLSsteam's config flags, and wires injection
through a **launch wrapper**: patched `.desktop` files for Desktop, a PATH drop-in for
terminals, and a systemd drop-in on `steam-launcher.service` for Game Mode. Your
`steam.sh` stays **vanilla**, so there's no install order to get right and nothing to
reapply "last" — every component maps to that same single `setup.sh` run. CloudRedirect
installs but stays inert until you sign into a provider (see [Cloud saves](cloud-saves.md)).
When something needs fixing, the same button changes to the fix it needs (for
example **Repair**, **Restart Steam** or **Fix in Desktop**). Every action asks
for a second tap to confirm.

Each run ends with a single, intentional Steam restart. The panel shows each
component as **Active** (green), **Installed** with a warning line (amber:
present but not working) or **Not installed** (red), and a **Steam** row says
whether your Steam build is supported — see [Components & health](components-and-health.md).

> Some fixes can't run in Game Mode. The panel then offers **Fix in Desktop**,
> which switches to Desktop Mode, runs the fix and brings you back to Game Mode
> by itself. This usually happens after a SteamOS/Steam client update — see
> [Troubleshooting](troubleshooting.md).

## 3. Add your first game

Adding is available once SLSsteam and lumalinux are **Active** and a Hubcap key
or Ryuu session works; until then the buttons are greyed out and a ⚠ line says
what to fix. There are **three ways** to pick a game, all in the **Add Game**
section of the main LumaDeck page:

- **From its Steam store page** — open the store page and LumaDeck auto-detects
  the AppID (shown below).
- **By name** — switch Add Game to **By name**, type a title and press
  **Search** (Steam's own store search), then pick the game.
- **By AppID** — type the Steam AppID into the field under **By AppID** (the
  default).

All three are covered in [Adding & updating games](adding-and-updating-games.md).
The store-page route, end to end:

1. In Steam, open the **store page** of the game you want.
2. Open LumaDeck in the QAM — it **auto-detects the AppID** and fills it in.
3. Check the preview card (name, developer, size, Metacritic, ProtonDB, any DRM
   or launcher notice) and tap **Add game**. (For a game you already own,
   the card says *Only its DLC will be added*.)
4. When it finishes, the game appears in your library **without a Steam restart**.
   (If it doesn't show up, your Steam build may not support the live refresh —
   restart Steam and it appears.)
5. In Steam, press **Install** on the game — it now downloads natively, like any
   owned title. **Progress shows in the Steam library, not in the plugin.**
