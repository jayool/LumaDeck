"""backend/deps/SplicedTickets/lumadeck-spliced-tickets.lua — the Lua itself:
    python -m unittest discover -s tests

Runs the plugin in a Lua interpreter (lupa) with SLSsteam's API stubbed and a
fake GetAppOwnershipTicketExtendedData, and checks LumaDeck's base-ticket
selection and Ace's splice around it. Skipped when lupa is not installed.

Pins: a real ticket is returned untouched; with app 7 empty the base comes
from the candidate list, then from the installed apps (every library in
libraryfolders.vdf), never from the game itself; the splice puts the game's
appid at the old signature offset, moves the signature by 4 and keeps the
steamid; the base that worked is remembered; with no ticket anywhere the hook
returns 0 instead of 4 bytes of appid. 2026-11-07: Spacewar (480) is the
first base; its ticket is asked for once per logon (ClientAccountInfo after
ClientLogOnResponse, or at load when already logged on) and from the hook
when nothing has a ticket and the login did not ask; never twice in a logon.
"""
import os
import sys
import tempfile
import unittest

try:
    import lupa
    from lupa import LuaRuntime
except ImportError:  # pragma: no cover
    lupa = None

PLUGIN = os.path.join(os.path.dirname(__file__), "..", "backend", "deps",
                      "SplicedTickets", "lumadeck-spliced-tickets.lua")

# A 178-byte ticket as Steam issues it: steamid at 8, appid at 16, signature at 50.
def make_ticket(appid, steamid=0x0110000126E63A31):
    t = bytearray(178)
    t[0:4] = (50).to_bytes(4, "little")
    t[4:8] = (4).to_bytes(4, "little")
    t[8:16] = steamid.to_bytes(8, "little")
    t[16:20] = appid.to_bytes(4, "little")
    t[50:178] = bytes([0xA0 + (i % 16) for i in range(128)])
    return bytes(t)


HARNESS = r"""
-- SLSsteam's Lua API, stubbed. `tickets` maps appid -> byte string.
local tickets, calls = ..., {}
local M = {}
M.calls = calls
local ffiStub = {
    cdef = function() end,
    C = { malloc = function(n) return { } end, free = function() end,
          place_lua_hook = function(_, fn) return fn end,
          unpack_user_data = function(ud) return ud end },
    gc = function(p) return p end,
    cast = function(ctype, v)
        -- uint32_t* over a 4-byte box: bytes readable through [0..3]
        if ctype == "uint8_t*" and type(v) == "table" and v.__u32 ~= nil then
            local n = v.__u32
            return setmetatable({}, { __index = function(_, i) return math.floor(n / 256 ^ i) % 256 end })
        end
        if ctype == "uint32_t*" then
            local box = { __u32 = 0 }
            return setmetatable(box, { __newindex = function(t, k, val) rawset(t, "__u32", val) end,
                                       __index = function(t, k) return rawget(t, "__u32") end })
        end
        return v
    end,
}
package.loaded["ffi"] = ffiStub
VFTableInfo_t = function() return { init = function() return true end, index = 105, ptr = {} } end
LuaHook = function() return { index = 1 } end
LuaMutex = function() return { unlock = function() end } end
log = { info = function(m) calls[#calls + 1] = m end, debug = function() end,
        notify = function() end, notifyError = function() end }
-- SLS: the callbacks a plugin registers are captured (M.cbs) and fired by the
-- tests; the engine's user reports M.loggedOn and hands a marker as IClientUser.
M.cbs = {}; M.loggedOn = false; M.clientUser = { marker = "engine IClientUser" }
SLS = {
    registerCallback = function(name, fn) M.cbs[name] = fn end,
    steamEngine = { getUser = function(_, i) return { getClientUser = function()
        return setmetatable(M.clientUser, { __index = { loggedOn = function() return M.loggedOn end } }) end } end },
}
-- the original GetAppOwnershipTicketExtendedData: the fake fills the buffers like Steam does
M.tramp = function(pUser, appId, pTicket, ticketSize, pOffAppId, pOffSteamId, pOffSig, pOffSigSize)
    local t = tickets[appId]
    if not t then pOffAppId[0] = 0; pOffSteamId[0] = 0; pOffSig[0] = 0; pOffSigSize[0] = 0; return 0 end
    for i = 1, #t do pTicket[i - 1] = t:byte(i) end
    pOffAppId[0] = 16; pOffSteamId[0] = 8; pOffSig[0] = 50; pOffSigSize[0] = 128
    return #t
end
local origCast = ffiStub.cast
ffiStub.cast = function(ctype, v)
    if ctype == "GetTicket_t" and v == true then return M.tramp end
    return origCast(ctype, v)
end
-- place_lua_hook returns `true` so the GetTicket_t cast above hands back the fake tramp
ffiStub.C.place_lua_hook = function() return true end
M.run = function(src, appId)
    assert(load(src))()
    local buf = setmetatable({}, { __index = function(t, k) return rawget(t, k) or 0 end })
    local pa, ps, pg, pz = { [0] = 0 }, { [0] = 0 }, { [0] = 0 }, { [0] = 0 }
    local n = SplicedTickets.hkGetTicket({}, appId, buf, 1024, pa, ps, pg, pz)
    local bytes = {}
    for i = 0, (n > 0 and n + 3 or -1) do bytes[#bytes + 1] = string.char(buf[i]) end
    return n, table.concat(bytes), pa[0], ps[0], pg[0], pz[0], SplicedTickets.baseApp
end
return M
"""


@unittest.skipUnless(lupa, "lupa (Lua for Python) not installed")
class SplicedTicketsLua(unittest.TestCase):
    def setUp(self):
        with open(PLUGIN, "rb") as f:
            self.src = f.read()
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.steamapps = os.path.join(self.home, ".local", "share", "Steam", "steamapps")
        os.makedirs(self.steamapps)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def _runtime(self, tickets):
        # encoding=None: Lua strings cross as bytes, so a ticket's bytes survive.
        L = LuaRuntime(unpack_returned_tuples=True, encoding=None)
        L.execute(b'os.getenv = function(k) if k == "HOME" then return "%s" end end' % self.home.encode())
        # lupa's Lua has no io.popen: the plugin's `ls "<dir>"` is answered from Python.
        def pylist(cmd):
            d = bytes(cmd).decode().split('"')[1]
            return L.table_from([n.encode() for n in sorted(os.listdir(d))] if os.path.isdir(d) else [])
        L.globals().pylist = pylist
        L.execute(b'io.popen = function(cmd) local t = pylist(cmd); local i = 0; '
                  b'return { lines = function() return function() i = i + 1; return t[i] end end, close = function() end } end')
        M = L.eval(b"function(...) " + HARNESS.encode() + b" end")(L.table_from(tickets))
        return L, M

    def _run(self, tickets, appid):
        L, M = self._runtime(tickets)
        n, data, offApp, offSteam, offSig, sigSize, base = M.run(self.src, appid)
        log = [bytes(c).decode() for c in M.calls.values()]
        return int(n), bytes(data), int(offApp), int(offSteam), int(offSig), int(sigSize), base, log

    def _acf(self, appid, folder=None):
        d = folder or self.steamapps
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"appmanifest_{appid}.acf"), "w") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"%d"\n}\n' % appid)

    def test_real_ticket_is_returned_untouched(self):
        t = make_ticket(229890)
        n, data, offApp, offSteam, offSig, _, base, _ = self._run({229890: t}, 229890)
        self.assertEqual(n, 178)
        self.assertEqual(data[:178], t)
        self.assertEqual((offApp, offSteam, offSig), (16, 8, 50))
        self.assertIsNone(base)

    def test_app7_still_wins_when_steam_issues_it(self):
        n, data, offApp, offSteam, offSig, _, base, _ = self._run({7: make_ticket(7)}, 229890)
        self.assertEqual(base, 7)
        self.assertEqual(n, 178)                                        # Ace's plugin returns the base size
        self.assertEqual(data[50:54], (229890).to_bytes(4, "little"))   # the game's appid at the old sig offset
        self.assertEqual((offApp, offSteam, offSig), (50, 8, 54))
        self.assertEqual(data[8:16], make_ticket(7)[8:16])              # steamid kept
        self.assertEqual(data[54:182], make_ticket(7)[50:178])          # signature moved by 4, intact

    def test_candidate_tool_is_the_base_when_app7_is_empty(self):
        n, data, offApp, _, offSig, _, base, log = self._run({1493710: make_ticket(1493710)}, 229890)
        self.assertEqual(base, 1493710)
        self.assertEqual(data[50:54], (229890).to_bytes(4, "little"))
        self.assertEqual((offApp, offSig), (50, 54))
        self.assertTrue(any("Spliced ticket for 229890 on app 1493710" in m for m in log), log)

    def test_installed_app_from_any_library_is_the_base(self):
        sd = os.path.join(self.tmp, "sdcard")
        self._acf(229890)                     # the game itself: never the base
        self._acf(480, os.path.join(sd, "steamapps"))
        with open(os.path.join(self.steamapps, "libraryfolders.vdf"), "w") as f:
            f.write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                    % (os.path.dirname(self.steamapps), sd))
        n, data, _, _, _, _, base, _ = self._run({480: make_ticket(480)}, 229890)
        self.assertEqual(base, 480)
        self.assertEqual(n, 178)
        self.assertEqual(data[50:54], (229890).to_bytes(4, "little"))

    def test_apps_added_through_slssteam_are_not_asked(self):
        # Added (unowned) apps have an .acf too; SLSsteam lists them in AdditionalApps.
        self._acf(229890); self._acf(4001890); self._acf(480)
        cfg = os.path.join(self.home, ".config", "SLSsteam")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config.yaml"), "w") as f:
            f.write("PlayNotOwnedGames: yes\nAdditionalApps:\n  - 4001890  #Extra Data\n  - 229890\nDisableFamilyShareLock: yes\n")
        L, M = self._runtime({480: make_ticket(480)})
        order = []
        orig = M.tramp
        def spy(pUser, appId, *rest):
            order.append(int(appId)); return orig(pUser, appId, *rest)
        M.tramp = spy
        n, data, _, _, _, _, base = M.run(self.src, 229890)
        self.assertEqual(base, 480)
        self.assertNotIn(4001890, order)                         # added through SLSsteam: never asked
        self.assertEqual(order.count(229890), 1)                 # the game: its own real-ticket call only

    def test_no_ticket_anywhere_returns_zero_not_four_bytes(self):
        self._acf(229890)
        n, data, _, _, _, _, base, log = self._run({}, 229890)
        self.assertEqual(n, 0)
        self.assertEqual(data, b"")
        self.assertIsNone(base)
        self.assertTrue(any("No base ticket for 229890" in m for m in log), log)

    def test_working_base_is_remembered_and_tried_first(self):
        L, M = self._runtime({4183110: make_ticket(4183110)})
        M.run(self.src, 229890)
        self.assertEqual(L.eval(b"SplicedTickets.baseApp"), 4183110)
        order = []
        orig = M.tramp
        def spy(pUser, appId, *rest):
            order.append(int(appId))
            return orig(pUser, appId, *rest)
        L.globals().SplicedTickets.getTicketTramp = spy
        zero = lambda: L.table_from({0: 0})
        buf = L.eval(b"setmetatable({}, { __index = function(t, k) return rawget(t, k) or 0 end })")
        L.globals().SplicedTickets.hkGetTicket(L.table(), 229890, buf, 1024, zero(), zero(), zero(), zero())
        self.assertEqual(order, [229890, 4183110])   # the game's own ticket, then the remembered base: nothing else

    # --- 2026-11-07: Spacewar as the requested base -------------------------

    def _hook(self, L, appid):
        zero = lambda: L.table_from({0: 0})
        buf = L.eval(b"setmetatable({}, { __index = function(t, k) return rawget(t, k) or 0 end })")
        return int(L.globals().SplicedTickets.hkGetTicket(L.table(), appid, buf, 1024, zero(), zero(), zero(), zero()))

    def _spy(self, L):
        asked = []
        def update(this, appid, stale):
            asked.append((this, int(appid), int(stale))); return True
        L.globals().SplicedTickets.updateFn = update
        return asked

    def test_spacewar_is_the_first_base(self):
        tickets = {480: make_ticket(480), 7: make_ticket(7), 1493710: make_ticket(1493710)}
        n, data, offApp, _, offSig, _, base, log = self._run(tickets, 229890)
        self.assertEqual(base, 480)
        self.assertEqual(n, 178)
        self.assertEqual(data[50:54], (229890).to_bytes(4, "little"))
        self.assertEqual(data[8:16], make_ticket(480)[8:16])
        self.assertTrue(any("Spliced ticket for 229890 on app 480" in m for m in log), log)

    def test_hook_asks_for_spacewar_once_when_nothing_has_a_ticket(self):
        L, M = self._runtime({})
        M.run(self.src, 229890)                      # loaded; the first miss could not resolve the request (stubbed vtable)
        asked = self._spy(L)
        L.globals().SplicedTickets.requested = False
        self.assertEqual(self._hook(L, 229890), 0)   # this launch: empty ticket, request sent
        self.assertEqual([a[1:] for a in asked], [(480, 0)])
        self.assertEqual(self._hook(L, 229890), 0)   # a second miss in the same logon: no second request
        self.assertEqual(len(asked), 1)
        logs = [bytes(c).decode() for c in M.calls.values()]
        self.assertTrue(any("asked Steam for the ownership ticket of app 480 (no base ticket for 229890)" in m for m in logs), logs)
        self.assertTrue(any("the next launch has it" in m for m in logs), logs)

    def test_logon_asks_once_and_a_new_logon_asks_again(self):
        L, M = self._runtime({})
        M.run(self.src, 229890)
        asked = self._spy(L)
        L.globals().SplicedTickets.requested = False
        recv = M.cbs[b"Network::recvPkt"]
        pkt = lambda t: L.table_from({b"body": L.table_from({b"type": t})})
        recv(pkt(768 - 2147483648))                  # ClientAccountInfo, protobuf high bit set: the request
        recv(pkt(768 - 2147483648))                  # again in the same logon: nothing
        self.assertEqual([a[1:] for a in asked], [(480, 0)])
        self.assertEqual(bytes(asked[0][0].marker), b"engine IClientUser")   # the engine's IClientUser, not the hook's pUser
        recv(pkt(751 - 2147483648))                  # ClientLogOnResponse: a new logon
        recv(pkt(768 - 2147483648))
        self.assertEqual(len(asked), 2)
        self.assertEqual(self._hook(L, 229890), 0)   # the hook does not ask again after the login did
        self.assertEqual(len(asked), 2)

    def test_plugin_loaded_with_a_session_asks_at_load(self):
        L, M = self._runtime({})
        M.loggedOn = True
        # resolveUpdate cannot work on the stubbed vtable: the load-time request is
        # attempted (the log says so) and nothing breaks.
        M.run(self.src, 229890)
        logs = [bytes(c).decode() for c in M.calls.values()]
        self.assertTrue(any("not resolved, ticket of app 480 not requested (plugin loaded, logged on)" in m for m in logs), logs)
        self.assertIn(b"SLSsteam::initialized", M.cbs)
        self.assertIn(b"Network::recvPkt", M.cbs)


if __name__ == "__main__":
    unittest.main()
