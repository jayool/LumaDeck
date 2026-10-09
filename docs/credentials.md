# Credentials

LumaDeck pulls game manifests from **manifest providers**. Each one needs a
credential, configured in **Settings ▸ API Credentials**. You only need one
provider to start; having both gives you more sources to fall back on.

A **status line** under each credential shows its live state, and a warning
appears at download time if a credential is dead.

There is one more credential that is **not** a manifest provider: the
[LuaTools account](#luatools-account), which game fixes need. It has its own
section at the bottom of the same tab and works differently — see below.

## Hubcap API key

The primary provider ([hubcapmanifest.com](https://hubcapmanifest.com)).

1. In **Settings ▸ API Credentials**, tap **Get API Key (opens Hubcap)** — it
   opens Hubcap in the Steam browser.
2. Log in with Discord, regenerate your key, and copy it.
3. Paste it into the **Hubcap API Key** field and tap **Save Hubcap Key**.

The key is stored in `api.json`, inside the Hubcap entry's URL (the
`?api_key=` part; the entry is still named *Morrenus*). At download time it is
sent as an `Authorization: Bearer` header, so it never lands in a log.

To **remove** the key, clear the field and tap **Save Hubcap Key** again. That
strips it from `api.json`, disables the Hubcap entry (without a key Hubcap only
answers 401) and forgets the copy in the settings store, so a plugin reload
does not bring it back. Adding and updating games keep working through Ryuu;
search by name uses Steam's store and needs no credential.

## Ryuu cookie

A secondary provider ([generator.ryuu.lol](https://generator.ryuu.lol)). Its
credential is a hidden `session` cookie, not a value shown on a page — so
LumaDeck captures it for you, with **no DevTools and no copy/paste**:

1. Tap **Log in with Discord**. The Steam browser opens Ryuu; sign in with
   Discord there and finish the authorisation.
2. LumaDeck watches the browser's cookie store and, as soon as the session is
   **logged in**, saves it and closes the browser.

Ryuu hands out a `session` cookie before you log in (an anonymous one, valid
30 days), so LumaDeck does not accept the first cookie it sees: it checks each
new cookie against Ryuu's home page and only keeps the one that carries your
user. While the session is anonymous the browser stays open for you to log in;
after three minutes without a login it gives up ("Ryuu login timed out"). If
Ryuu can't be reached to check, the session is saved unverified and checked
later.

You can also paste a cookie by hand and tap **Save Cookie**. A pasted cookie is
saved as-is, without the logged-in check.

> **How it works:** LumaDeck reads the live cookie through Steam's CEF debug
> port, so it arrives already decrypted. If the debug port isn't reachable it
> falls back to Steam's on-disk Chromium cookie store: `v10` values decrypt with
> Chromium's fixed no-keyring key (`peanuts`/`saltysalt`), and `v11` values are
> tried against the OS keyring. If neither works, paste the cookie by hand.

## Other sources in `api.json`

Besides Hubcap and Ryuu, `api.json` lists two free GitHub mirrors (Sushi,
Spinoza), but they ship **disabled** because they lag behind new releases. When
you add a game, the backend tries each *enabled* source in order (Hubcap first,
then Ryuu) and uses the first that returns a valid manifest zip. In practice you
need a Hubcap key or a Ryuu session.

The list is built into LumaDeck and rewritten on every plugin load, so every
install uses the same order and the same enabled set. Your saved Hubcap key is
kept across the rewrite. Each entry is a templated URL plus the HTTP codes that
mean "got it" (`success_code`, default 200) and "not here — try the next one"
(`unavailable_code`, default 404):

```json
{ "name": "...", "url": "https://.../<appid>", "success_code": 200,
  "unavailable_code": 404, "enabled": true }
```

## LuaTools account

Not a manifest provider — this one is for **game fixes**. It has its own
**LuaTools fixes** section at the bottom of **Settings ▸ API Credentials**,
below Hubcap and Ryuu.

Browsing the fix catalogue needs no account: **Check for Fixes** on a game's
**Fixes & Repairs** tab works logged out. An account is needed to actually **apply a fix** or to
**install the game build a fix needs** — without one those buttons stay greyed
out, with a prompt to log in next to them.

1. In **Settings ▸ API Credentials ▸ LuaTools fixes**, tap **Log in with Discord**. LumaDeck opens
   lua.tools in the Steam browser.
2. Sign in with Discord. LumaDeck captures the session and closes the browser for
   you — there is nothing to copy or paste.

> **How it works:** lua.tools keeps its session in a browser cookie, split across
> several parts because it's too big for one. LumaDeck reads it through Steam's
> CEF debug port, which returns the **live** cookie already decrypted — CEF holds
> a fresh cookie in memory for about 15 seconds before writing it to disk, so
> reading it this way catches your login the instant it lands instead of waiting
> out that flush. If the debug port isn't reachable it falls back to reading (and
> decrypting) Steam's on-disk cookie store, the same way the Ryuu import does.

### It renews itself

A LuaTools access token is good for **exactly one hour**. You are not expected to
log in every hour: the session also carries a *refresh token*, and LumaDeck uses
it to get a new access token automatically, a minute before the old one runs out.
As long as you open LumaDeck now and then, you should never have to log in again.

That renewal was broken from the day the feature shipped until **v0.7.4**: the
call it made didn't exist, the error was swallowed, and the dead token was sent
anyway — so everyone got one hour of LuaTools and then a permanent
`session_expired` (issue #42).

> **Worth knowing:** each renewal replaces **both** tokens — the refresh token is
> single-use and the server hands you a new one every time. LumaDeck and the Steam
> browser each hold their own copy of the session from the moment you log in, so
> the first renewal makes the browser's copy stale. In practice this only matters
> if you also visit lua.tools in the Steam browser; if it ever does bite, it shows
> up as an expired session, and logging in again fixes it.

### The three states

The Settings row tells you which one you're in:

| Row says | Meaning |
| --- | --- |
| **Connected.** Fixes appear on each game details page | LumaDeck holds a usable token |
| **Session expired.** Log in again to apply fixes | The server rejected the session — renewal can't recover it |
| **Log in with Discord** to apply fixes… | No session at all |

"Connected" means LumaDeck actually asked for a usable token, not that a session
file exists somewhere. If the current token is still good the check is instant and
touches no network; if it has run out, the renewal happens first, and only a
**definite rejection** from the server turns the row red. A Deck with no
connection keeps showing its last known state rather than nagging you for a login
it couldn't complete anyway.

The same distinction reaches the Fixes tab: an expired session greys out the fix
buttons and puts a **Log in with Discord** button right there, so a fix that fails
because your session died is two taps from working instead of an error with
nowhere to go.

### Logging out

**Log out** in the same Settings row removes the saved session, drops its backup
copy, and clears the live cookie from the Steam browser as well — otherwise
lua.tools would still show you as signed in the next time you opened it.

## Expiry warnings

This section is about the two **API credentials**, Hubcap and Ryuu. The LuaTools
session expires too, but it renews itself and reports differently — see
[The three states](#the-three-states).

Both API credentials expire, so LumaDeck surfaces it — without nagging:

- **Settings status line (always shown).** Under each credential:
  - 🟢 *valid, N days left* (hours when under a day). Hubcap adds today's
    request usage on the same line.
  - 🟡 *expires in N*: regenerate the Hubcap key (shown 5 days ahead; a key
    lasts 7 days) or log in to Ryuu again (shown 1 day ahead).
  - 🔴 *expired*: regenerate the key, or log in with Discord again.
  - grey *none saved*, or *couldn't check* (Hubcap) / *saved, not verified yet*
    (Ryuu).
- **When adding a game.** If neither Hubcap nor Ryuu is usable (both missing or
  expired), the Add Game section shows *Set up a Hubcap or Ryuu key in
  Settings.* and **Add game** is disabled. While at least one works, nothing is
  shown there; Settings tells you about the other one.

Hubcap expiry comes from its free `/user/stats` endpoint (it doesn't cost you a
request). Ryuu has two signals: the cookie's own expiry date (captured at
login, whatever date Ryuu set) and a **live check**, a GET of Ryuu's home page with the
cookie, once an hour per cookie, that looks for the logged-in marker. Ryuu can
drop a session before its date (measured 2026-10-07), so a dead session reads
as *expired* even when the date is fine, and a download that Ryuu answers with
401/403 marks it dead at once. The live check costs no download.

When a download started from a game page (**Re-download Manifest**, **Fix
Update**) fails because a credential was rejected, the page's **Updates** tab
shows a **Hubcap API key expired** and/or **Ryuu session expired** row with an
**Open Settings** button instead of the generic failure.

## Where the values live

| Credential | Stored in |
| --- | --- |
| Hubcap key | `api.json` (the Hubcap provider entry) |
| Ryuu cookie | `data/ryuu_cookie.txt` |
| Ryuu cookie expiry | `data/ryuu_cookie_expiry.txt` (captured at import) |
| LuaTools session | `data/luatools_session.json` |

All four are also **mirrored into the plugin's settings directory**, which Decky
does not wipe when it replaces the plugin, and restored from there on the next
load. That is why updating LumaDeck no longer signs you out of anything.

LuaTools has a **Log out** button, and the Hubcap key can be removed by saving
an empty field. The Ryuu cookie can only be replaced. Logging out clears the mirror as well as the saved
session; without that the next plugin load would restore the very session you
just discarded, which is what happened in the release that first added LuaTools
to the restore list.
