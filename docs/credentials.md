# Credentials

LumaDeck pulls game manifests from **manifest providers**. Each one needs a
credential, configured in **Settings ▸ API Credentials**. You only need one
provider to start; having both gives you more sources to fall back on.

A **status line** under each credential shows its live state, and a warning
appears at download time if a credential is dead.

There is one more credential that is **not** a manifest provider: the
[LuaTools account](#luatools-account), which game fixes need. It lives in its own
Settings section and works differently — see below.

## Hubcap API key

The primary provider ([hubcapmanifest.com](https://hubcapmanifest.com)).

1. In **Settings ▸ API Credentials**, tap **Get API Key (opens Hubcap)** — it
   opens Hubcap in the Steam browser.
2. Log in with Discord, regenerate your key, and copy it.
3. Paste it into the **Hubcap API Key** field and tap **Save Hubcap Key**.

The key is stored in `api.json` as the Hubcap entry's `api_key`.

## Ryuu cookie

A secondary provider ([generator.ryuu.lol](https://generator.ryuu.lol)). Its
credential is a hidden `session` cookie, not a value shown on a page — so
LumaDeck can import it for you, with **no DevTools and no copy/paste**:

1. Tap **Open Ryuu (log in)** and sign in with Discord in the Steam browser.
2. Back in LumaDeck, tap **Import cookie from Steam browser**.

LumaDeck reads Steam's in-client (CEF/Chromium) cookie store, decrypts the
`session` cookie, and saves it. You can still paste a cookie manually into the
field if you prefer.

> **How it works:** Steam's Game Mode browser stores cookies in a Chromium
> SQLite DB. The value is `v10`-encrypted, which is decryptable with no OS
> keyring (the `peanuts`/`saltysalt` scheme Chromium uses when no keyring is
> present). If your cookie happens to be keyring-encrypted (`v11`), the import
> can't decrypt it and you'll be asked to paste it manually instead.

## Free APIs (no credential)

Hubcap and Ryuu are the **keyed** providers, but LumaDeck also ships a list of
**free, keyless manifest sources** in `api.json`. When you download a game, the
backend tries every *enabled* provider in order and uses the first that returns
a valid manifest zip — so even with no Hubcap key or Ryuu cookie, these can
still serve some titles.

**Settings ▸ APIs ▸ Update Free APIs** refreshes that list from the upstream it's
seeded from ([Star123451/LuaToolsLinux `api.json`](https://github.com/Star123451/LuaToolsLinux/blob/main/backend/api.json)).
Run it if downloads start failing because a source moved or a new one was added.
Your saved Hubcap key is preserved across the refresh.

Each entry is a templated URL plus the HTTP codes that mean "got it"
(`success_code`, default 200) and "not here — try the next one"
(`unavailable_code`, default 404):

```json
{ "name": "...", "url": "https://.../<appid>", "success_code": 200,
  "unavailable_code": 404, "enabled": true }
```

## LuaTools account

Not a manifest provider — this one is for **game fixes**. It lives in its own
**Settings ▸ LuaTools fixes** section, not under API Credentials.

Browsing the fix catalogue needs no account: **Check for Fixes** on a game's
Fixes tab works logged out. An account is needed to actually **apply a fix** or to
**install the game build a fix needs** — without one those buttons stay greyed
out, with a prompt to log in next to them.

1. In **Settings ▸ LuaTools fixes**, tap **Log in with Discord**. LumaDeck opens
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
  - 🟢 *valid — N days left (expires …)* — Hubcap also shows today's request usage.
  - 🟡 *expires in N — regenerate / re-import soon*
  - 🔴 *expired — regenerate / re-import it*
  - grey *none saved* / *couldn't check*
- **Download-time warning (only when adding a game).** If a credential is
  **expired or missing** when you stage a game for download, a warning appears
  above the **Download Manifest** button. "Expiring soon" is deliberately *not*
  shown here — the current download would still work — so it stays in Settings
  only.

Hubcap expiry comes from its free `/user/stats` endpoint (it doesn't cost you a
request). Ryuu expiry is read from the cookie itself when you import it.

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

LuaTools is the only one you can actively **log out** of — the other three you
replace rather than delete. Logging out clears the mirror as well as the saved
session; without that the next plugin load would restore the very session you
just discarded, which is what happened in the release that first added LuaTools
to the restore list.
