"""Progress of a setup.sh run (Quick Install, Update, Repair, Reinstall) as the
QAM shows it: one bar from start to Done, fed by real numbers wherever a tool
reports them and by a short, capped time fill where none does.

The bar is split into phases in the script's real order (measured on the
codespace, 2026-11-23: Quick Install 68 s, of which the CloudRedirect app's
flatpak runtimes 47 s / 710 MB of the 760 MB the whole run downloads). Each
phase owns a share of the bar (its weight) proportional to what it moves:

  preparing  5 | slssteam 2 | cloudredirect 2 | cloudredirect_app 80 |
  netsock 1 | lumalinux 3 | tools 1 | dotnet 4 | gamemode 2      (= 100)

Inside a phase the bar fills with:
  - curl's --progress-bar percent (the GitHub downloads, the .NET tarball);
  - flatpak's own progress ("Installing 3/7… ████ 45%", printed when it sees
    a terminal: the backend runs the script on a pty and setup.sh calls
    flatpak without --noninteractive), weighted by the per-runtime sizes
    flatpak lists before it starts ("1. org.kde.Platform 6.10 i flathub
    < 392.1 MB"); without a terminal flatpak prints only "Installing
    runtime/…" per ref, which still advances the phase ref by ref;
  - otherwise time: 1 - e^(-t/T) against the phase's expected seconds,
    capped at 90 % of the phase, so a silent step moves and never pretends
    to be done. T comes from the codespace run (the app: 90 s, between the
    codespace's 47 s and the one Deck run on record, 2026-10-14).
A phase ends when the script prints the next phase's first line; the bar
then jumps to that phase's start. It never goes back. Done is 100.

The app phase is 80 % of the run, so its text is split too: a sub-phase from
what is really happening (the bundle's curl bar, flatpak's runtime rows, the
bundle's own table) and, once nothing has changed for FILLER_SEC seconds, a
filler line that advances every FILLER_SEC seconds and stays on the last one
(decoration, chosen 2026-11-24: flatpak writes a 400 MB runtime to disk in
silence for 15-30 s and the row should not look dead).
"""
import math
import re
import time

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CURL_BAR_RE = re.compile(r"^[#\s]*(\d{1,3}(?:\.\d+)?)%\s*$")
# flatpak's plan table, one row per ref:
#  " 1.     org.kde.KStyle.Adwaita          6.10            i           flathub         < 8.6 MB"
FLATPAK_ROW_RE = re.compile(
    r"^\s*(\d+)\.\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+<?\s*([\d.,]+)\s*([kKMG]?B)\b")
# flatpak's progress line (pty): "Installing… ████ 45%  5.2 MB/s" or "Installing 3/7… ███ 45%"
FLATPAK_PROG_RE = re.compile(r"^Installing(?:\s+(\d+)/(\d+))?…\s.*?(\d{1,3})%")
# flatpak's live table on a pty (what a real Quick Install printed, codespace
# 2026-11-23): one row per ref, redrawn in place with cursor codes, with the
# bytes so far once a ref is in flight:
#   " 1. [ ] org.freedesktop.Platform.GL.default  25.08  i  flathub  < 147.8 MB"
#   " 1. [/] org.freedesktop.Platform.GL.default  25.08  i  flathub   1.0 kB / 147.8 MB"
#   " 1. [✓] org.cloudredirect.CloudRedirect      master i  cloudredirect-origin  0 bytes"
# Several rows can arrive in one piece of text, so this is searched, not matched.
FLATPAK_LIVE_ROW_RE = re.compile(
    r"(\d+)\.\s+\[(.)\]\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:<\s*)?([\d.,]+)\s*(bytes|[kKMG]B)"
    r"(?:\s*/\s*([\d.,]+)\s*(bytes|[kKMG]B))?(\s*\(partial\))?")
# flatpak without a terminal: one line per ref as it starts
FLATPAK_REF_RE = re.compile(r"^Installing (?:runtime|app)/\S+")

# (id, label, weight, expected seconds, lines that start it)
PHASES = (
    ("preparing", "Preparing…", 5, 8.0, ("Installing lumalinux unlock stack",)),
    ("slssteam", "Downloading SLSsteam…", 2, 2.0, ("Downloading SLSsteam",)),
    ("cloudredirect", "Downloading CloudRedirect…", 2, 2.0, ("Downloading CloudRedirect",)),
    ("cloudredirect_app", "Installing CloudRedirect app", 80, 90.0, ("Installing CloudRedirect app",)),
    ("netsock", "Downloading netsock…", 1, 1.0, ("Downloading netsock",)),
    ("lumalinux", "Downloading lumalinux…", 3, 2.0, ("Downloading lumalinux",)),
    ("tools", "Installing tools…", 1, 1.0, ("Runtime tools from",)),
    ("dotnet", "Installing .NET…", 4, 3.0, ("Installing .NET 9 runtime",)),
    ("gamemode", "Setting up Game Mode…", 2, 1.0,
     ("Writing injection wrapper", "Guardian installed", "Game Mode injection installed")),
)
PHASE_IDS = tuple(p[0] for p in PHASES)
PHASE_LABELS = {p[0]: p[1] for p in PHASES}
PHASE_LABELS["done"] = "Done"
TOTAL_STEPS = len(PHASES)
_OFFSET = {}
_acc = 0
for _id, _label, _w, _t, _trig in PHASES:
    _OFFSET[_id] = _acc
    _acc += _w
assert _acc == 100, _acc
TIME_FILL_CAP = 0.9
# A flatpak runtime is half download (its bytes, reported) and half deploy
# (writing it to disk, silent until the ✓): the deploy half fills by time
# against DEPLOY_SEC_PER_MB × size (codespace 2026-11-23: 148 MB in ~10 s,
# 392 MB in ~27 s). Half and half is a choice, not a measurement: on the
# codespace's 150 MB/s the deploy is 90 % of a runtime's time, on a Deck's
# wifi the download is; the split errs least without knowing which.
DEPLOY_SHARE = 0.5
DEPLOY_SEC_PER_MB = 0.07
# The app phase's sub-phases (snapshot()["sub"]; the frontend has the text):
#   app_download     the bundle's curl bar
#   runtime_download flatpak's runtime rows (plan table, live table, progress)
#   app_install      the bundle's own flatpak table / ref
APP_SUBS = ("app_download", "runtime_download", "app_install")
APP_BUNDLE_REF = "org.cloudredirect.CloudRedirect"
# Filler lines (by index; the frontend has the text) once the app phase has
# been quiet for FILLER_SEC: index 0 at FILLER_SEC, 1 at 2 × FILLER_SEC …
# and the last one for as long as the silence lasts.
FILLER_COUNT = 8
FILLER_SEC = 5.0


def phase_for_line(text):
    """The phase id a setup.sh line starts, or None."""
    for pid, _label, _w, _t, triggers in PHASES:
        if any(t in text for t in triggers):
            return pid
    return None


def _mb(value: str, unit: str) -> float:
    n = float(value.replace(",", "."))
    return {"B": n / 1048576, "bytes": n / 1048576, "kB": n / 1024, "KB": n / 1024,
            "MB": n, "GB": n * 1024}.get(unit, n)


def time_fill(elapsed: float, expected: float) -> float:
    """0..TIME_FILL_CAP: how much of a silent phase the bar shows after
    `elapsed` seconds, against the `expected` duration; quick at first,
    slower and slower, never full."""
    if expected <= 0:
        return 0.0
    return min(TIME_FILL_CAP, 1.0 - math.exp(-elapsed / expected))


class InstallProgress:
    """Fed one output line at a time (feed), asked for the QAM's numbers at any
    moment (snapshot). `now` is injectable for the tests."""

    def __init__(self, now=None):
        self._now = now or time.monotonic
        self.phase = None           # current phase id, "done" at the end
        self.phase_started = self._now()
        self.percent = None         # real progress inside the phase, 0..100, or None
        self._fill_floor = 0.0      # the time fill shown when the first real reading arrived
        self._shown = 0.0           # the overall value last reported: the bar never goes below it
        self.detail = ""            # the last script line, for the log / debugging
        self.done = False
        # flatpak: sizes (MB) by 1-based row from its plan table, the ref in
        # progress, when it began, and whether flatpak reports a percent
        # inside it (a terminal) or only that it began (no terminal)
        self._fp_sizes = {}
        self._fp_ref = 0
        self._fp_total = 0
        self._fp_ref_started = None
        self._fp_ref_pct = None
        # the live table: by ref (id, branch), [MB so far, MB total, when the
        # download completed (or None), checked ✓]. By ref, not by row: the
        # bundle's table numbers from 1 again.
        self._fp_live = {}
        # refs the plan table listed "(partial)": flatpak then shows the
        # whole runtime's size for them ("x / 401.9 MB" for a locale of which
        # it fetches a couple of MB): their weight is the bytes they really
        # move, never that size (the recording of 2026-11-24: the total
        # jumped 702 → 1104 MB when the Locale went in flight, and the bar
        # sat at 57 % for 30 s)
        self._fp_partial = set()
        # the app phase's sub-phase, and the moment anything the user can
        # see last changed (for the filler lines)
        self.sub = None
        self._curl_pct = None
        self._signal = None
        self._signal_at = self._now()

    # ── input ──────────────────────────────────────────────────────────
    def enter(self, phase: str) -> None:
        if phase == self.phase:
            return
        # never backwards: a trigger of an earlier phase (a repeated line) is noise
        if self.phase in PHASE_IDS and phase in PHASE_IDS and PHASE_IDS.index(phase) < PHASE_IDS.index(self.phase):
            return
        self.phase = phase
        self.phase_started = self._now()
        self.percent = None
        self._fill_floor = 0.0
        self._fp_sizes, self._fp_ref, self._fp_total = {}, 0, 0
        self._fp_ref_started, self._fp_ref_pct = None, None
        self._fp_live = {}
        self._fp_partial = set()
        self.sub = None
        self._touch()
        if phase == "done":
            self.done = True

    def feed(self, raw: str) -> None:
        text = ANSI_RE.sub("", raw).strip()
        if not text:
            return
        m = CURL_BAR_RE.match(text)
        if m:
            # curl's bar is the phase's progress in the download phases. In the
            # app phase it is only the 3 MB bundle before flatpak's 710 MB of
            # runtimes: taking it as the phase sent the bar to 89 % and then
            # back to 9 % when flatpak began (the Quick Install video,
            # codespace 2026-11-23). Ignored there.
            if self.phase != "cloudredirect_app":
                self._set_percent(float(m.group(1)))
            else:
                self._set_sub("app_download")
            self._curl_pct = int(float(m.group(1)))
            self._touch()
            return
        if self.phase == "cloudredirect_app" and self._feed_flatpak_live(text):
            self._touch()
            return
        if self._fp_live:
            # the live table is the one source once it exists: the plan
            # table and the "Installing N/M… pct" line order the refs
            # differently and their max sent the bar ahead of the bytes
            self.detail = text
            pid = phase_for_line(text)
            if pid:
                self.enter(pid)
            return
        m = FLATPAK_ROW_RE.match(text)
        if m and "/" not in m.group(2) and m.group(4) in ("i", "u", "r"):
            self._fp_sizes[int(m.group(1))] = _mb(m.group(6), m.group(7))
            self._fp_total = max(self._fp_total, int(m.group(1)))
            if "(partial)" in text:
                self._fp_partial.add((m.group(2), m.group(3)))
            self._set_sub("app_install" if m.group(2) == APP_BUNDLE_REF else "runtime_download")
            self._touch()
            return
        m = FLATPAK_PROG_RE.match(text)
        if m:
            ref = int(m.group(1)) if m.group(1) else max(1, self._fp_ref or 1)
            total = int(m.group(2)) if m.group(2) else max(self._fp_total, ref)
            if ref != self._fp_ref:
                self._fp_ref_started = self._now()
            self._fp_ref, self._fp_total = ref, max(total, self._fp_total)
            self._fp_ref_pct = int(m.group(3))
            self._set_percent(self._flatpak_percent(ref, self._fp_ref_pct))
            self._set_sub("runtime_download")
            self._touch()
            return
        if FLATPAK_REF_RE.match(text):
            # no terminal: a ref began; the previous ones are complete. Inside
            # it nothing will be reported: snapshot() fills its share by time.
            self._fp_ref += 1
            self._fp_total = max(self._fp_total, self._fp_ref)
            self._fp_ref_started = self._now()
            self._fp_ref_pct = None
            self._set_percent(self._flatpak_percent(self._fp_ref, 0))
            self._set_sub("app_install" if APP_BUNDLE_REF in text else "runtime_download")
            self._touch()
            return
        self.detail = text
        pid = phase_for_line(text)
        if pid:
            self.enter(pid)

    def _set_sub(self, sub: str) -> None:
        """The app phase's sub-phase, forward only (the bundle's table comes
        after the runtimes', and a late runtime row must not flip it back)."""
        if self.phase != "cloudredirect_app" or sub not in APP_SUBS:
            return
        if self.sub is None or APP_SUBS.index(sub) > APP_SUBS.index(self.sub):
            self.sub = sub

    def _touch(self) -> None:
        """Note the moment the visible state last changed: phase, sub-phase,
        the bytes so far, a curl or flatpak percent. The filler lines count
        from there."""
        done = sum(r[0] for r in self._fp_live.values()) if self._fp_live else 0.0
        sig = (self.phase, self.sub, int(done), self._fp_ref, self._fp_ref_pct, self._curl_pct)
        if sig != self._signal:
            self._signal = sig
            self._signal_at = self._now()

    def filler(self) -> "int | None":
        """Index of the filler line to show (0..FILLER_COUNT-1), or None while
        something real changed in the last FILLER_SEC seconds. Only in the
        app phase."""
        if self.phase != "cloudredirect_app" or self.done:
            return None
        quiet = self._now() - self._signal_at
        if quiet < FILLER_SEC:
            return None
        return min(FILLER_COUNT - 1, int(quiet // FILLER_SEC) - 1)

    def _set_percent(self, value: float) -> None:
        """Inside a phase the bar never goes back: a lower reading (a second
        curl bar in the same phase, a flatpak ref count that re-learns its
        total) keeps the higher one."""
        value = max(0.0, min(100.0, value))
        if self.percent is None:
            # the first real reading: whatever the time fill showed until now
            # stays as the floor, so a low first reading does not pull back
            idx = PHASE_IDS.index(self.phase) if self.phase in PHASE_IDS else None
            if idx is not None:
                self._fill_floor = time_fill(self._now() - self.phase_started, PHASES[idx][3])
            self.percent = value
        elif value > self.percent:
            self.percent = value

    def _feed_flatpak_live(self, text: str) -> bool:
        """flatpak's live table rows in `text` (any number of them): bytes so
        far and total per ref, when its download completed, and its ✓. The
        phase percent is computed from them in snapshot() (the deploy half
        moves with time). True when rows were found."""
        found = False
        now = self._now()
        for m in FLATPAK_LIVE_ROW_RE.finditer(text):
            found = True
            key = (m.group(3), m.group(4))
            mark = m.group(2)
            prev = self._fp_live.get(key)
            self._set_sub("app_install" if key[0] == APP_BUNDLE_REF else "runtime_download")
            if m.group(11):                                  # pending "(partial)": size unknown
                self._fp_partial.add(key)
                continue
            if key in self._fp_partial:
                # a partial ref weighs what it really moves: its bytes so far
                # (the size flatpak shows is the whole runtime's)
                done_mb = _mb(m.group(7), m.group(8)) if m.group(9) else (prev[0] if prev else 0.0)
                total_mb = max(done_mb, prev[1] if prev else 0.0)
                if mark == "✓":
                    done_mb = total_mb = max(total_mb, 0.1)
            elif m.group(9):                                 # "x / y": in flight
                done_mb, total_mb = _mb(m.group(7), m.group(8)), _mb(m.group(9), m.group(10))
            elif mark == "✓":                                # complete: whatever it was, all of it
                total_mb = (prev[1] if prev else 0.0) or _mb(m.group(7), m.group(8))
                done_mb = total_mb
            else:                                            # pending "< y"
                done_mb, total_mb = 0.0, _mb(m.group(7), m.group(8))
            if prev and prev[0] > done_mb and prev[1] == total_mb:
                continue                                     # a stale redraw
            completed_at = prev[2] if prev else None
            if total_mb > 0 and done_mb >= total_mb and completed_at is None:
                completed_at = now
            checked = (prev[3] if prev else False) or mark == "✓"
            self._fp_live[key] = [done_mb, total_mb, completed_at, checked]
        if found:
            self._fp_ref_pct = 0                             # real numbers: no ref time fill
            self._set_percent(self._live_percent())
        return found

    def _live_percent(self) -> float:
        """The app phase from the live table: each runtime weighs its size;
        its download half is its bytes, its deploy half is time since the
        download completed (DEPLOY_SEC_PER_MB × size, capped) or whole at ✓."""
        rows = [r for r in self._fp_live.values() if r[1] > 0]
        whole = sum(r[1] for r in rows)
        if whole <= 0:
            return 0.0
        now = self._now()
        acc = 0.0
        for done_mb, total_mb, completed_at, checked in rows:
            dl = min(1.0, done_mb / total_mb)
            if checked:
                dep = 1.0
            elif completed_at is not None:
                dep = time_fill(now - completed_at, max(1.0, DEPLOY_SEC_PER_MB * total_mb))
            else:
                dep = 0.0
            acc += total_mb * ((1 - DEPLOY_SHARE) * dl + DEPLOY_SHARE * dep)
        return min(100.0, 100.0 * acc / whole)

    def _writing(self) -> bool:
        """flatpak has every reported byte and is writing to disk: the text
        says so instead of the frozen MB count."""
        rows = [r for r in self._fp_live.values() if r[1] > 0]
        if not rows or any(0 < r[0] < r[1] for r in rows):
            return False
        return any(r[2] is not None and not r[3] for r in rows)

    def _flatpak_ref_share(self, ref: int, phase_expected: float):
        """(share of the phase this ref is, 0..1; seconds it should take): by
        size where the plan table gave sizes, by count otherwise."""
        total = max(self._fp_total, ref)
        if self._fp_sizes and all(i in self._fp_sizes for i in range(1, total + 1)):
            whole = sum(self._fp_sizes.values()) or 1.0
            share = self._fp_sizes[ref] / whole
        else:
            share = 1.0 / total
        return share, max(1.0, phase_expected * share)

    def _flatpak_percent(self, ref: int, pct: int) -> float:
        """Progress of the whole flatpak install: refs before `ref` complete,
        `ref` at pct, by size where the plan table gave sizes, by count
        otherwise."""
        total = max(self._fp_total, ref)
        if self._fp_sizes and all(i in self._fp_sizes for i in range(1, total + 1)):
            whole = sum(self._fp_sizes.values()) or 1.0
            before = sum(v for i, v in self._fp_sizes.items() if i < ref)
            return min(100.0, 100.0 * (before + self._fp_sizes[ref] * pct / 100.0) / whole)
        return min(100.0, 100.0 * ((ref - 1) + pct / 100.0) / total)

    # ── output ─────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        if self.done or self.phase == "done":
            return {"phase": "done", "progress": PHASE_LABELS["done"], "percent": None,
                    "overall": 100.0, "step": TOTAL_STEPS, "stepTotal": TOTAL_STEPS, "detail": self.detail}
        if self.phase not in PHASE_IDS:
            return {"phase": self.phase, "progress": PHASE_LABELS.get(self.phase or "", ""), "percent": None,
                    "overall": 0.0, "step": 0, "stepTotal": TOTAL_STEPS, "detail": self.detail}
        idx = PHASE_IDS.index(self.phase)
        _id, label, weight, expected, _trig = PHASES[idx]
        # The time fill runs until the first real reading; from then on the
        # real number rules, with the fill reached by then as a floor so a
        # low first reading (flatpak's 0 % after a second of fill) does not
        # pull the bar back.
        if self.phase == "cloudredirect_app" and self._fp_live:
            self._set_percent(self._live_percent())          # the deploy half moves with time
        if self.percent is None:
            frac = time_fill(self._now() - self.phase_started, expected)
        else:
            frac = max(self._fill_floor, self.percent / 100.0)
        # flatpak without a terminal says only which ref began: inside it the
        # bar would sit still for the whole download (29 s at 73 % on the
        # 392 MB org.kde.Platform, measured on the Quick Install video,
        # codespace 2026-11-23). Fill the ref's own share by time, against
        # the seconds its size would take at the phase's expected pace,
        # capped like any silent phase, never reaching the next ref.
        if (self.phase == "cloudredirect_app" and self._fp_ref and self._fp_ref_pct is None
                and self._fp_ref_started is not None and self.percent is not None):
            share, ref_expected = self._flatpak_ref_share(self._fp_ref, expected)
            ref_fill = time_fill(self._now() - self._fp_ref_started, ref_expected) * share
            frac = max(frac, min(1.0, self.percent / 100.0 + ref_fill))
        # Never backwards, whatever the inputs do (a flatpak ref count that
        # re-learns its total, a repeated line): the reported value only grows.
        self._shown = max(self._shown, round(_OFFSET[self.phase] + weight * frac, 1))
        self._touch()
        out = {"phase": self.phase, "progress": label, "percent": self.percent,
               "overall": self._shown,
               "step": idx + 1, "stepTotal": TOTAL_STEPS, "detail": self.detail,
               "sub": self.sub, "filler": self.filler()}
        # The app phase's bytes (flatpak's live table), for the row's text:
        # "146/710 MB" moves every second where the bar alone would not, and
        # "writing" while flatpak deploys a downloaded runtime in silence.
        if self.phase == "cloudredirect_app" and self._fp_live:
            total = sum(r[1] for r in self._fp_live.values())
            if total > 0:
                done = min(total, sum(r[0] for r in self._fp_live.values()))
                out["mbDone"], out["mbTotal"] = int(round(done)), int(round(total))
                out["writing"] = self._writing()
        return out
