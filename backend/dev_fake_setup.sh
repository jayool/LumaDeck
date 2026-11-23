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
# flatpak on a terminal, as a real Quick Install printed it through the pty
# (codespace 2026-11-23): the plan table redrawn in place, one row per ref
# with the bytes so far, separated by cursor codes rather than newlines.
flatpak_table() {   # $1 = row in flight, $2 = MB done of that row; rows: name|branch|total_MB|done(1/0)
    local cur=$1 done=$2 n=0 line
    printf '\x1b[5A'
    for spec in "org.freedesktop.Platform.GL.default|25.08|147.8" "org.freedesktop.Platform.GL.default|25.08-extra|147.8" \
                "org.freedesktop.Platform.codecs-extra|25.08-extra|14.6" "org.kde.Platform.Locale|6.10|1.2" "org.kde.Platform|6.10|392.1"; do
        n=$((n+1)); IFS='|' read -r name branch total <<<"$spec"
        if (( n < cur )); then line=$(printf '%d. [✓] %-40s %-12s i  flathub  %7.1f MB / %7.1f MB' "$n" "$name" "$branch" "$total" "$total")
        elif (( n == cur )); then line=$(printf '%d. [/] %-40s %-12s i  flathub  %7.1f MB / %7.1f MB' "$n" "$name" "$branch" "$done" "$total")
        else line=$(printf '%d. [ ] %-40s %-12s i  flathub  < %7.1f MB' "$n" "$name" "$branch" "$total"); fi
        printf '%s\x1b[K\x1b[1B\r' "$line"
    done
}
flatpak_runtimes() {
    echo "Looking for matches…"
    echo "        ID                                    Branch      Op Remote  Download"
    printf '\n\n\n\n\n'
    local totals=(147.8 147.8 14.6 1.2 392.1) secs=(3 1 0.5 0.2 7) steps
    for ((r = 1; r <= 5; r++)); do
        steps=8
        for ((i = 0; i <= steps; i++)); do
            flatpak_table "$r" "$(awk -v t="${totals[r-1]}" -v i="$i" -v k="$steps" 'BEGIN{printf "%.1f", t*i/k}')"
            nap "$(awk -v s="${secs[r-1]}" -v k="$steps" 'BEGIN{printf "%.3f", s/k}')"
        done
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
flatpak_runtimes
echo "        ID                              Branch Op Remote               Download"
printf '1. [ ] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytes\r1. [✓] org.cloudredirect.CloudRedirect master i  cloudredirect-origin 0 bytes\n'
nap 0.5
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
