# Credentials

LumaDeck pulls game manifests from **manifest providers**. Each one needs a
credential, configured in **Settings ▸ API Credentials**. You only need one
provider to start; having both gives you more sources to fall back on.

A **status line** under each credential shows its live state, and a warning
appears at download time if a credential is dead.

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

## Expiry warnings

Both credentials expire, so LumaDeck surfaces it — without nagging:

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
