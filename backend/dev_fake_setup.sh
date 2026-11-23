#!/usr/bin/env bash
# dev_fake_setup.sh — a stand-in for lumalinux's setup.sh that installs NOTHING.
#
# Run by installer.py instead of the real script when the Dev tab sets
# "Installer: fake" (backend/dev.py, key "installer"). It prints what the
# real script printed on a real Quick Install (codespace, 2026-11-23, 68 s:
# same phase lines in the same order, same colour codes, curl's progress
# bars for the downloads, flatpak's plan table and progress for the
# CloudRedirect app's runtimes), with the measured pauses scaled down, so
# the QAM's progress row can be watched end to end without touching Steam,
# SLSsteam, CloudRedirect or lumalinux.
#
# LUMADECK_FAKE_SETUP_FAST=1 removes the pauses (the tests).
set -u
c_info='\e[0;36m'; c_ok='\e[0;32m'; c_rst='\e[0m'
info() { printf "${c_info}[*]${c_rst} %s\n" "$*"; }
ok()   { printf "${c_ok}[+]${c_rst} %s\n" "$*"; }
fast="${LUMADECK_FAKE_SETUP_FAST:-0}"
nap() { [[ "$fast" == "1" ]] || sleep "$1"; }
# A download: curl's bar, redrawn with \r every step, newline at the end.
curl_bar() {
    local steps=$1 pct
    for ((i = 1; i <= steps; i++)); do
        pct=$(( i * 100 / steps ))
        printf '\r%-72s %5.1f%%' "$(printf '#%.0s' $(seq 1 $(( pct * 72 / 100 ))))" "$pct"
        nap 0.12
    done
    printf '\n'
}
# flatpak on a terminal: "Installing N/M… ████ P%  speed", redrawn with \r.
flatpak_ref() {
    local n=$1 m=$2 secs=$3 steps=$4 pct
    for ((i = 1; i <= steps; i++)); do
        pct=$(( i * 100 / steps ))
        printf '\rInstalling %d/%d… %-20s %3d%%  %s' "$n" "$m" "$(printf '█%.0s' $(seq 1 $(( pct / 5 ))))" "$pct" "12.4 MB/s"
        nap "$(awk -v s="$secs" -v k="$steps" 'BEGIN{printf "%.3f", s/k}')"
    done
    printf '\n'
}

info "Installing lumalinux unlock stack (self-contained, wrapper injection)..."
nap 1
info "SLSsteam release: 20261112130346"
info "Downloading SLSsteam (latest), release 20261112130346..."
curl_bar 10
ok "Deployed /home/deck/.local/share/SLSsteam/x86_64/SLSsteam.so (64-bit client, latest)"
info "The latest SLSsteam release is 64-bit only: installing the last 32-bit release (20261106120254) for the 32-bit client."
info "Downloading SLSsteam (32-bit), release 20261106120254..."
curl_bar 10
ok "Deployed /home/deck/.local/share/SLSsteam/SLSsteam.so (32-bit client, 32-bit)"
ok "Seeded /home/deck/.config/SLSsteam/config.yaml (default)"
info "Downloading CloudRedirect..."
curl_bar 8
ok "Deployed /home/deck/.local/share/CloudRedirect/cloud_redirect.so"
curl_bar 8
ok "Deployed /home/deck/.local/share/CloudRedirect/x86_64/cloud_redirect.so (64-bit client)"
info "Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)..."
curl_bar 4
echo "Looking for matches…"
echo "        ID                                              Branch          Op          Remote          Download"
echo " 1.     org.freedesktop.Platform.GL.default             25.08           i           flathub         < 147.8 MB"
echo " 2.     org.freedesktop.Platform.GL.default             25.08-extra     i           flathub         < 147.8 MB"
echo " 3.     org.freedesktop.Platform.codecs-extra           25.08-extra     i           flathub         <  14.6 MB"
echo " 4.     org.kde.KStyle.Adwaita                          6.10            i           flathub         <   8.6 MB"
echo " 5.     org.kde.Platform.Locale                         6.10            i           flathub         <   1.2 MB (partial)"
echo " 6.     org.kde.Platform                                6.10            i           flathub         < 392.1 MB"
echo " 7.     org.cloudredirect.CloudRedirect                 master          i           cloudredirect   <   3.0 MB"
echo
flatpak_ref 1 7 3 12      # measured: 11 s on the codespace, scaled
flatpak_ref 2 7 1 6
flatpak_ref 3 7 1 4
flatpak_ref 4 7 0.5 3
flatpak_ref 5 7 0.3 2
flatpak_ref 6 7 7 20      # measured: 30 s
flatpak_ref 7 7 0.5 3
ok "CloudRedirect app installed (sign into your provider from Desktop)."
ok "Deployed /home/deck/.local/share/CloudRedirect/cloud_redirect_cli (from the flatpak)"
info "Downloading netsock..."
curl_bar 3
ok "Deployed /home/deck/.config/SLSsteam/tools/netsock/netsock.so"
info "Downloading lumalinux..."
curl_bar 8
ok "Deployed /home/deck/.local/share/lumalinux/liblumalinux.so"
curl_bar 8
ok "Deployed /home/deck/.local/share/lumalinux/liblumalinux-x86_64.so (64-bit client)"
ok "Created /home/deck/.config/lumalinux/keys.txt (empty)"
info "Runtime tools from v0.22.9 (same ref as the .so)"
nap 0.4
ok "Deployed /home/deck/.local/share/lumalinux/tools/steamidra_lite.py (v0.22.9)"
ok "Deployed /home/deck/.local/share/lumalinux/tools/vdf_inject_keys.py (v0.22.9)"
ok "Deployed SLSsteam plugin /home/deck/.config/SLSsteam/plugins/lumalinux-cuser.lua"
info "Installing .NET 9 runtime (Steamless needs it)..."
curl_bar 10
nap 0.6
ok "Deployed .NET 9 runtime to /home/deck/.dotnet"
info "Writing injection wrapper at /home/deck/.local/share/SLSsteam/path/steam..."
ok "Wrapper written."
nap 0.3
ok "Created override /home/deck/.local/share/applications/steam.desktop (shadows /usr/share/applications/steam.desktop)"
ok "Guardian installed (watches launcher dirs + 5-min reconcile)."
ok "Game Mode injection installed (steam-launcher.service drop-in, via fail-safe)."
nap 0.3
ok "Done. Restart Steam to load the stack."
exit 0
