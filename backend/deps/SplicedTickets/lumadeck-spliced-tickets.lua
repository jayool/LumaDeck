-- lumadeck-spliced-tickets.lua — SLSsteam plugin, installed by LumaDeck.
--
-- Author: Ace (SLSsteam). Published by him on the SLSsteam Discord on
-- 2026-08-30 as "spliced-tickets.lua". Modified by LumaDeck on 2026-10-30:
-- the base ticket is no longer app 7 alone (see "LumaDeck:" below); the
-- hook, the splice and the double-load guard are his, unchanged. LumaDeck
-- ships it under a different file name so that other tools which deploy
-- their own copy into ~/.config/SLSsteam/plugins/ neither overwrite nor
-- delete ours. The global table `SplicedTickets` is deliberately kept:
-- SLSsteam runs every plugin in one Lua state, so a second copy sees
-- `setup == true` and returns without placing a second hook (whichever copy
-- loads first wins; SLSsteam loads the plugins directory in name order).
--
-- What it does: SteamStub-wrapped games ask Steam for an app-ownership ticket
-- at launch; for an unowned game Steam returns an empty one and the stub
-- shows "Application load error 6:0000065432". On an empty ticket this plugin
-- takes the ticket of an app the account does own, splices the game's appid
-- in front of the signature and adjusts the offsets, so stubs that do not
-- verify the signature unpack and run. See FIXES_MAP.md (SteamStub).
--
-- LumaDeck: which app's ticket is the base. Ace's plugin used app 7 (the
-- Steam client, owned by every account). Since 2026-10-20 (the day app 7's
-- record changed) the client no longer holds an ownership ticket for app 7:
-- the call returns size 0, the splice was built on nothing and every stub
-- showed 65432 again. The tickets of apps the account owns AND has installed
-- are still issued, in the same layout (178 bytes: steamid at 8, appid at
-- 16, the 128-byte signature at 50), and the stub accepts the splice built
-- on any of them: verified on 2026-10-30 in CI with Proton Experimental, a
-- Steam Linux Runtime and Spacewar as the base. So the base is looked for in
-- this order: app 7 (should Valve bring it back), Valve's compat tools and
-- runtimes a Deck that runs Windows games has installed, then every installed
-- app in every Steam library (libraryfolders.vdf, SD card included) except
-- the ones added through SLSsteam (AdditionalApps: installed, not owned, no
-- ticket). The base used is logged at info level: "Spliced ticket for <game> on app <base>".
--
-- LumaDeck, 2026-11-07: Spacewar (480) first. The client only holds the
-- tickets of the apps it has installed; an owned app that is not installed
-- reads as empty until someone asks the server for it, and the server issues
-- 480's at once (luma-lab login smoke, runs 68/69, 32- and 64-bit clients;
-- app 7's is refused). So when 480 reads empty the hook asks for it right
-- there (IClientUser::BUpdateAppOwnershipTicket through the object's live
-- vtable slot) and goes on with the bases above: that launch uses one of
-- them or fails as before, the next one has 480. SLSsteam keeps the ticket
-- on disk (cache/ticket_480.yaml), so this happens once per machine.
--
-- To keep LumaDeck from installing it: touch ~/.config/lumadeck/no_spliced_tickets

SplicedTickets = SplicedTickets or {
	setup = false,

	getTicketHook = nil, getTicketTramp = nil,
}

if SplicedTickets.setup then
	return
end
SplicedTickets.setup = true

local ffi = require("ffi")

ffi.cdef[[
	void* malloc(int);
	void free(void*);

	void* place_lua_hook(const int, const void*);

	typedef uint32_t(*GetTicket_t)(void*, uint32_t, uint8_t*, uint32_t, uint32_t*, uint32_t*, uint32_t*, uint32_t*);
	typedef bool(*UpdateTicket_t)(void*, uint32_t, int);
]]

SplicedTickets.mutexReturn = function(value, mutex)
	mutex:unlock()
	return value
end

local clientUserMap = VFTableInfo_t("14IClientUserMap", "GetAppOwnershipTicketExtendedData")
if not clientUserMap:init() then
	log.notifyError("Failed to initialize IClientUserMap!")
	return
end

local clientUser = VFTableInfo_t("5CUser", "GetAppOwnershipTicketExtendedData", clientUserMap.index, 0)
clientUser:init()

log.debug("User ExtendedData at "..clientUserMap.index)

-- LumaDeck: candidate base apps, most likely first. 7 = Steam client (Ace's
-- original base, empty since 2026-10-20); then Proton Experimental, Proton
-- Hotfix, Proton 10, Proton 9, Proton 8, Steam Linux Runtime 3.0 (sniper),
-- Steam Linux Runtime (4183110, pulled by Proton Experimental), 2.0 (soldier),
-- 1.0 (scout on soldier). Whatever Proton a Deck installed for its Windows
-- games is in here or in the installed-apps scan below.
-- LumaDeck 2026-11-07: Spacewar (480) first, the app whose ticket this plugin
-- asks the server for (header); it needs nothing installed.
SplicedTickets.baseCandidates = { 480, 7, 1493710, 2180100, 3658110, 2805730, 1887720, 1628350, 4183110, 1070560, 1391110 }
SplicedTickets.baseApp = nil   -- the base used last time (for the log line; 480 is always tried first)

-- LumaDeck: ask Steam for 480's ticket (header). `this` is the IClientUser
-- the hook was called on; the function is its live vtable slot (SLSsteam's own
-- hook on it included). Logs one line; the answer arrives asynchronously.
SplicedTickets.requestApp = 480
SplicedTickets.request = function(this)
	local app = SplicedTickets.requestApp
	if SplicedTickets.updateFn == nil then
		local ok, fn = pcall(function()
			local map = VFTableInfo_t("14IClientUserMap", "BUpdateAppOwnershipTicket")
			if not map:init() then return nil end
			return ffi.cast("UpdateTicket_t", ffi.cast("void**", ffi.cast("void**", this)[0])[map.index])
		end)
		if not ok or fn == nil then log.info("Spliced tickets: BUpdateAppOwnershipTicket not resolved, ticket of app " .. app .. " not requested"); return false end
		SplicedTickets.updateFn = fn
	end
	local ok, r = pcall(SplicedTickets.updateFn, this, app, 0)
	log.info("Spliced tickets: asked Steam for the ownership ticket of app " .. app .. " -> " .. (ok and tostring(r) or ("error " .. tostring(r))))
	return ok
end

-- LumaDeck: the apps added through SLSsteam (AdditionalApps in its
-- config.yaml). They are installed but not owned, so they never have a
-- ticket; the scan below skips them instead of asking Steam for nothing.
SplicedTickets.addedApps = function()
	local cfgDir = os.getenv("XDG_CONFIG_HOME") or ((os.getenv("HOME") or "") .. "/.config")
	local added, inList = {}, false
	local f = io.open(cfgDir .. "/SLSsteam/config.yaml", "r")
	if not f then return added end
	for line in f:lines() do
		if line:match("^AdditionalApps:") then inList = true
		elseif inList then
			local id = line:match("^%s*%-%s*(%d+)")
			if id then added[tonumber(id)] = true
			elseif not line:match("^%s*$") and not line:match("^%s*#") then inList = false end
		end
	end
	f:close()
	return added
end

-- LumaDeck: every installed app, from the appmanifest_*.acf of every Steam
-- library (the main one plus the "path" entries of libraryfolders.vdf), as
-- sorted appids, minus the apps added through SLSsteam. Returns {} when
-- nothing can be read.
SplicedTickets.installedApps = function()
	local root = (os.getenv("HOME") or "") .. "/.local/share/Steam"
	local added = SplicedTickets.addedApps()
	local dirs = { root .. "/steamapps" }
	local lf = io.open(root .. "/steamapps/libraryfolders.vdf", "r") or io.open(root .. "/config/libraryfolders.vdf", "r")
	if lf then
		for line in lf:lines() do
			local path = line:match('"path"%s+"([^"]+)"')
			if path and path .. "/steamapps" ~= dirs[1] then dirs[#dirs + 1] = path .. "/steamapps" end
		end
		lf:close()
	end
	local seen, apps = {}, {}
	for _, dir in ipairs(dirs) do
		local ok, ls = pcall(io.popen, 'ls "' .. dir .. '" 2>/dev/null')
		if ok and ls then
			for name in ls:lines() do
				local id = name:match("^appmanifest_(%d+)%.acf$")
				if id and not seen[id] and not added[tonumber(id)] then seen[id] = true; apps[#apps + 1] = tonumber(id) end
			end
			ls:close()
		end
	end
	table.sort(apps)
	return apps
end

-- LumaDeck: fill the ticket buffers with the first base ticket that exists
-- (never the game's own appid, which is the empty one). Returns its size, 0
-- when no app on this machine has a ticket.
SplicedTickets.baseTicket = function(pUser, appId, pTicket, ticketSize, pOffAppId, pOffSteamId, pOffSig, pOffSigSize)
	local tried = {}
	local function try(base)
		if base == appId or tried[base] then return 0 end
		tried[base] = true
		local n = SplicedTickets.getTicketTramp(pUser, base, pTicket, ticketSize, pOffAppId, pOffSteamId, pOffSig, pOffSigSize)
		if n > 0 then SplicedTickets.baseApp = base
		elseif base == SplicedTickets.requestApp then SplicedTickets.request(pUser) end   -- LumaDeck: next launch has it
		return n
	end
	-- try() leaves the ticket in the caller's buffers, so a hit is returned as is.
	-- Always in list order: 480 is on every account, the rest only on some
	-- machines, so the one that worked last time is not tried first.
	for _, base in ipairs(SplicedTickets.baseCandidates) do
		local n = try(base)
		if n > 0 then return n end
	end
	for _, base in ipairs(SplicedTickets.installedApps()) do
		local n = try(base)
		if n > 0 then return n end
	end
	return 0
end

SplicedTickets.hkGetTicket = ffi.cast("GetTicket_t", function(pUser, appId, pTicket, ticketSize, pOffAppId, pOffSteamId, pOffSig, pOffSigSize)
	local mutex = LuaMutex()
	local size = SplicedTickets.getTicketTramp(pUser, appId, pTicket, ticketSize, pOffAppId, pOffSteamId, pOffSig, pOffSigSize)

	if size > 0 then
		return SplicedTickets.mutexReturn(size, mutex)
	end

	-- LumaDeck: was `getTicketTramp(pUser, 7, ...)`; see the header.
	size = SplicedTickets.baseTicket(pUser, appId, pTicket, ticketSize, pOffAppId, pOffSteamId, pOffSig, pOffSigSize)
	if size == 0 then
		log.info("No base ticket for " .. appId .. ": neither Spacewar, app 7 nor any installed app has one; the stub gets the empty ticket")
		return SplicedTickets.mutexReturn(0, mutex)
	end

	local splicedTicket = {}
	for i = 0, size do
		splicedTicket[i] = pTicket[i]
	end

	local sigOffset = pOffSig[0]

	local pAppId = ffi.cast("uint32_t*", ffi.gc(ffi.C.malloc(4), ffi.C.free))
	pAppId[0] = appId
	local appIdBytes = ffi.cast("uint8_t*", pAppId)

	 for i = 0, 3 do
		table.insert(splicedTicket, sigOffset + i, appIdBytes[i])
	 end

	for i = 0, #splicedTicket - 1 do
		pTicket[i] = splicedTicket[i]
	end

	pOffAppId[0] = pOffSig[0]
	pOffSig[0] = pOffSig[0] + 4

	log.info("Spliced ticket for " .. appId .. " on app " .. SplicedTickets.baseApp)   -- LumaDeck: info, so release builds show it

	return SplicedTickets.mutexReturn(size, mutex)
end)

SplicedTickets.getTicketHook = LuaHook("GetTicket", clientUser.ptr)
SplicedTickets.getTicketTramp = ffi.cast("GetTicket_t", ffi.C.place_lua_hook(SplicedTickets.getTicketHook.index, SplicedTickets.hkGetTicket))

log.notify("spliced-tickets.lua loaded!")
