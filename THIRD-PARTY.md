# Third-party code and licences

What LumaDeck ships inside its release zip that is not its own, and under
which terms. Components LumaDeck installs on the Deck at run time but does not
redistribute (lumalinux, SLSsteam, CloudRedirect, steamnetsock-patch,
eos-proxy, Decky Loader, the .NET runtime) are credited in the README and keep
their own licences; nothing of them is in the zip.

## DeckTools — MIT

LumaDeck is a fork of [DeckTools](https://github.com/lopesleo/DeckTools) by
Leonardo Lopes (lopesleo). The plugin's architecture, most of the frontend and
many backend modules come from it. DeckTools' licence notice applies to that
code and is reproduced here as it requires:

```
MIT License

Copyright (c) 2026 Leonardo Lopes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

DeckTools states that its manifest handling and API logic derive from
[LuaToolsLinux](https://github.com/Star123451/LuaToolsLinux) (Star123451),
which declares no licence of its own.

## Steamless — CC BY-NC-ND 4.0

`backend/deps/Steamless/` holds an unmodified build of
[Steamless](https://github.com/atom0s/Steamless) by atom0s (`Steamless.CLI`
and its unpacker plugins), used as-is to remove the SteamStub wrapper from a
game's executable. Steamless is licensed under the Creative Commons
Attribution-NonCommercial-NoDerivatives 4.0 International License
(<https://creativecommons.org/licenses/by-nc-nd/4.0/>): it is redistributed
here with attribution, unchanged, for non-commercial use only. It is a
separate work aggregated in the zip, not part of LumaDeck's own code.

## Goldberg Steam Emulator (gbe_fork) — LGPL-3.0

The release build fetches the emulator binaries of
[gbe_fork](https://github.com/Detanup01/gbe_fork) (Detanup01's fork of the
Goldberg Steam Emulator) into `backend/deps/Goldberg/`, unmodified, so the zip
ships them. They are licensed under the GNU Lesser General Public License
v3.0; the source is in that repository and the binaries are used as separate
libraries copied next to a game, not linked into LumaDeck.

## spliced-tickets.lua — author Ace, no licence declared

`backend/deps/SplicedTickets/lumadeck-spliced-tickets.lua` is the SLSsteam
plugin `spliced-tickets.lua` written by Ace (AceSLS, the author of SLSsteam),
published on the SLSsteam Discord on 2026-08-30 without a licence statement.
LumaDeck ships it under another file name with the changes marked in the
file (the base-ticket choice); the hook, the splice and the double-load guard
are his, unchanged.

## LumaDeck itself

MIT, inherited from DeckTools (see the README). Copyright (c) 2026 jayool for
the LumaDeck changes.
