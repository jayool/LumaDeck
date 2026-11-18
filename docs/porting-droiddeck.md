# DroidDeck compatibility preview

**This branch is NOT a working game downloader.** It does not port lumalinux or
SLSsteam hooks, Steam entitlement handling, or native Steam CDN integration.
Do not market or distribute it as a functional DroidDeck downloader.

## Implemented

- Detect DroidDeck using the decky service marker, environment or an explicit test override.
- Select native ARM64 (steamrtarm64) or experimental FEX/x86-64 (steamrt64).
- Prefer `/root/.local/share/Steam` on native ARM64 and
  `/root/.droiddeck-x64/.local/share/Steam` for FEX.
- Resolve the guest's real HOME/UID correctly.
- Allow plugin metadata startup without patching SteamOS systemd launchers.
- Return explicit unsupported errors for installers and major Steam-mutating operations.

## Running tests

```sh
python3 -m unittest discover -s tests
```

## Known issues

- The plugin frontend is not verified on a real DroidDeck device.
- Various status panels still assume SteamOS and may display incorrect health.
- No Android-compatible `lumalinux` hook is included. Even the FEX Steam
  client's existing hook binaries require validation and a compatible loader.
- Existing releases from upstream are SteamOS-oriented and should not be used
  as a DroidDeck installer.
- Other features (cloud redirects, fixes, self-updates) remain unported.

To test detection in a non-DroidDeck Linux guest, use
`LUMADECK_DROIDDECK=1` or `LUMADECK_DROIDDECK=0`.
You may set `LUMADECK_DROIDDECK_CLIENT=x86_64` and
`LUMADECK_STEAM_ROOT=/absolute/path` for diagnostic overrides.
