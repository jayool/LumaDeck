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


def phase_for_line(text):
    """The phase id a setup.sh line starts, or None."""
    for pid, _label, _w, _t, triggers in PHASES:
        if any(t in text for t in triggers):
            return pid
    return None


def _mb(value: str, unit: str) -> float:
    n = float(value.replace(",", "."))
    return {"B": n / 1048576, "kB": n / 1024, "KB": n / 1024, "MB": n, "GB": n * 1024}.get(unit, n)


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
        self.detail = ""            # the last script line, for the log / debugging
        self.done = False
        # flatpak: sizes (MB) by 1-based row from its plan table, and the ref in progress
        self._fp_sizes = {}
        self._fp_ref = 0
        self._fp_total = 0

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
        self._fp_sizes, self._fp_ref, self._fp_total = {}, 0, 0
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
            return
        m = FLATPAK_ROW_RE.match(text)
        if m and "/" not in m.group(2) and m.group(4) in ("i", "u", "r"):
            self._fp_sizes[int(m.group(1))] = _mb(m.group(6), m.group(7))
            self._fp_total = max(self._fp_total, int(m.group(1)))
            return
        m = FLATPAK_PROG_RE.match(text)
        if m:
            ref = int(m.group(1)) if m.group(1) else max(1, self._fp_ref or 1)
            total = int(m.group(2)) if m.group(2) else max(self._fp_total, ref)
            self._fp_ref, self._fp_total = ref, max(total, self._fp_total)
            self._set_percent(self._flatpak_percent(ref, int(m.group(3))))
            return
        if FLATPAK_REF_RE.match(text):
            # no terminal: a ref began; the previous ones are complete
            self._fp_ref += 1
            self._fp_total = max(self._fp_total, self._fp_ref)
            self._set_percent(self._flatpak_percent(self._fp_ref, 0))
            return
        self.detail = text
        pid = phase_for_line(text)
        if pid:
            self.enter(pid)

    def _set_percent(self, value: float) -> None:
        """Inside a phase the bar never goes back: a lower reading (a second
        curl bar in the same phase, a flatpak ref count that re-learns its
        total) keeps the higher one."""
        value = max(0.0, min(100.0, value))
        if self.percent is None or value > self.percent:
            self.percent = value

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
        # The time fill runs until the first real reading; a first reading
        # below it (flatpak's 0 % after a second of fill) must not pull the
        # bar back, so the shown fraction is the higher of the two.
        fill = time_fill(self._now() - self.phase_started, expected)
        frac = max(fill, self.percent / 100.0) if self.percent is not None else fill
        return {"phase": self.phase, "progress": label, "percent": self.percent,
                "overall": round(_OFFSET[self.phase] + weight * frac, 1),
                "step": idx + 1, "stepTotal": TOTAL_STEPS, "detail": self.detail}
