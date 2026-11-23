#!/usr/bin/env bash
# dev_fake_setup.sh — a stand-in for lumalinux's setup.sh that installs NOTHING.
#
# Run by installer.py instead of the real script when the Dev tab sets
# "Installer: fake" (backend/dev.py, key "installer"). It prints the same
# messages the real script prints at each phase (same wording, same colour
# codes, see lumalinux setup.sh info()/ok()), with pauses, and fakes curl's
# --progress-bar for the downloads (carriage-return redraws, no newline), so
# the QAM's progress row can be watched end to end, as often as needed,
# without touching Steam, SLSsteam, CloudRedirect or lumalinux.
#
# LUMADECK_FAKE_SETUP_FAST=1 removes the pauses (the tests).
set -u
c_info='\e[0;36m'; c_ok='\e[0;32m'; c_rst='\e[0m'
info() { printf "${c_info}[*]${c_rst} %s\n" "$*"; }
ok()   { printf "${c_ok}[+]${c_rst} %s\n" "$*"; }
fast="${LUMADECK_FAKE_SETUP_FAST:-0}"
nap() { [[ "$fast" == "1" ]] || sleep "$1"; }
# A download: curl's bar, redrawn with \r every step, newline at the end.
download() {
    local steps=$1 pct
    for ((i = 1; i <= steps; i++)); do
        pct=$(( i * 100 / steps ))
        printf '\r%-72s %5.1f%%' "$(printf '#%.0s' $(seq 1 $(( pct * 72 / 100 ))))" "$pct"
        nap 0.15
    done
    printf '\n'
}

info "Installing lumalinux unlock stack (self-contained, wrapper injection)..."
nap 1
info "SLSsteam release: v20261112130346"
info "Downloading SLSsteam (64-bit client), release v20261112130346..."
download 20
ok "Deployed /home/deck/.local/share/SLSsteam/x86_64/SLSsteam.so (64-bit client, 64-bit client)"
ok "Seeded /home/deck/.config/SLSsteam/config.yaml (default)"
nap 1
info "Downloading CloudRedirect..."
download 12
ok "Deployed /home/deck/.local/share/CloudRedirect/x86_64/cloud_redirect.so (64-bit client)"
info "Installing CloudRedirect app (flatpak bundle; may pull the KDE runtime)..."
nap 6
ok "CloudRedirect app installed (sign into your provider from Desktop)."
info "Downloading netsock..."
download 6
ok "Deployed /home/deck/.local/share/lumalinux/netsock.so"
info "Downloading lumalinux..."
download 10
ok "Deployed /home/deck/.local/share/lumalinux/liblumalinux-x86_64.so (64-bit client)"
info "Runtime tools from v0.22.3 (same ref as the .so)"
nap 2
ok "Deployed /home/deck/.local/share/lumalinux/tools/steamidra_lite.py (v0.22.3)"
ok "Guardian installed (watches launcher dirs + 5-min reconcile)."
nap 1
ok "Game Mode injection installed (steam-launcher.service drop-in, via fail-safe)."
nap 1
exit 0
