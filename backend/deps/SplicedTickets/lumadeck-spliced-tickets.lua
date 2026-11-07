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
-- ticket). The first one with a ticket is remembered and tried first. The
-- base used is logged at info level: "Spliced ticket for <game> on app <base>".
--
-- LumaDeck, 2026-11-07: Spacewar (480) as the base that needs nothing
-- installed. The client only holds the tickets of the apps it has installed
-- (it fetches them at login); an owned app that is not installed reads as an
-- empty ticket until someone ASKS the server for it. Measured in luma-lab's
-- login smoke (run 68, stable 32-bit client, a throwaway account): after the
-- login 480 and 7 read 0 bytes, Proton Experimental and runtime 4183110 (both
-- installed, neither launched) 178; one IClientUser::BUpdateAppOwnershipTicket
-- (480, false) and the server answered within the second with the usual
-- 178-byte ticket (appid at 16, signature at 50); the same call for app 7 is
-- refused ("failed to update ownership ticket (Access Denied)"). So: the
-- ticket of 480 is asked for once per logon, as soon as the client is logged
-- on AND already knows the account's licences (isSubscribed(480) true: a
-- request sent at the logon message itself, before the licences arrive, is
-- dropped; run 70 of the smoke), checked on every CM packet until then, and
-- read back afterwards; 480 is the first base tried, then the list and the
-- scan above as before; and when nothing at all has a ticket the hook asks for
-- 480's then (unless the logon's request was already read back as answered),
-- returns the empty ticket for that launch, and the next launch finds it. The
-- request goes through the live vtable slot of the IClientUser object
-- (SLSsteam's own hook on it included).
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
	void* unpack_user_data(const void*);
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
SplicedTickets.baseApp = nil   -- the base that worked last time; tried first

-- LumaDeck: the ticket request (header). One request per logon from the
-- ticks below (`requested` clears when the client is seen logged off), one
-- more from the hook when nothing has a ticket and that one was never read
-- back as answered. The function is the live vtable slot of the IClientUser
-- object (the `this` Steam passes to the hook, or SLSsteam's engine user).
SplicedTickets.requestApp = 480
SplicedTickets.requested = false
SplicedTickets.verified = false   -- the requested ticket was read back non-empty
SplicedTickets.updateFn = nil

SplicedTickets.engineClientUser = function()
	local ok, p = pcall(function() return ffi.C.unpack_user_data(SLS.steamEngine:getUser(0):getClientUser()) end)
	if ok and p ~= nil then return p end
	return nil
end

SplicedTickets.loggedOn = function()
	local ok, v = pcall(function() return SLS.steamEngine:getUser(0):getClientUser():loggedOn() end)
	return ok and v == true
end

-- The licences are loaded: SLSsteam's isSubscribed asks Steam's own
-- CheckAppOwnership (no spoof), true for 480 only once the account's licences
-- are in. Before that a ticket request is dropped (run 70).
SplicedTickets.licencesLoaded = function()
	local ok, v = pcall(function() return SLS.steamEngine:getUser(0):isSubscribed(SplicedTickets.requestApp) end)
	return ok and v == true
end

SplicedTickets.resolveUpdate = function(this)
	if SplicedTickets.updateFn ~= nil then return SplicedTickets.updateFn end
	local ok, fn = pcall(function()
		local map = VFTableInfo_t("14IClientUserMap", "BUpdateAppOwnershipTicket")
		if not map:init() then return nil end
		local slot = ffi.cast("void**", ffi.cast("void**", this)[0])[map.index]
		if slot == nil then return nil end
		return ffi.cast("UpdateTicket_t", slot)
	end)
	if ok and fn ~= nil then SplicedTickets.updateFn = fn end
	return SplicedTickets.updateFn
end

-- Returns true when a request went out. `this` nil: the engine's user.
-- `again`: the hook's call, when nothing has a ticket: it asks even after the
-- logon did, unless the logon's request was read back as answered (verified).
-- A request counts as done only once its ticket has been seen (run 70: the
-- logon's request was lost and the hook, seeing "already asked", never asked).
SplicedTickets.request = function(this, why, again)
	if SplicedTickets.requested and (SplicedTickets.verified or not again) then return false end
	local app = SplicedTickets.requestApp
	this = this or SplicedTickets.engineClientUser()
	if this == nil then
		log.debug("Spliced tickets: no IClientUser yet, ticket of app " .. app .. " not requested (" .. why .. ")")
		return false
	end
	local fn = SplicedTickets.resolveUpdate(this)
	if fn == nil then
		log.info("Spliced tickets: BUpdateAppOwnershipTicket not resolved, ticket of app " .. app .. " not requested (" .. why .. ")")
		return false
	end
	SplicedTickets.requested = true
	local ok, r = pcall(fn, this, app, 0)
	log.info("Spliced tickets: asked Steam for the ownership ticket of app " .. app .. " (" .. why .. ") -> " .. (ok and tostring(r) or ("error " .. tostring(r))))
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
		if n > 0 then SplicedTickets.baseApp = base end
		return n
	end
	-- try() leaves the ticket in the caller's buffers, so a hit is returned as is.
	if SplicedTickets.baseApp then
		local n = try(SplicedTickets.baseApp)
		if n > 0 then return n end
	end
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
		-- LumaDeck: nothing in memory. Ask for 480's now if the login did not
		-- (header): this launch gets the empty ticket, the next one finds it.
		local asked = SplicedTickets.request(pUser, "no base ticket for " .. appId, true)
		log.info("No base ticket for " .. appId .. ": neither Spacewar, app 7 nor any installed app has one; the stub gets the empty ticket"
			.. (asked and ("; Steam was asked for app " .. SplicedTickets.requestApp .. "'s, the next launch has it") or ""))
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

-- LumaDeck: ask for 480's ticket at logon (header). The plugin API has no
-- timer, so every CM packet, in or out, is a tick: logged off -> a new logon
-- will ask again; logged on with the licences loaded and not asked yet -> ask;
-- asked -> read the ticket back until it is there (one log line), then nothing
-- more. A plugin dropped in with Steam already logged on (LumaDeck installs it
-- hot) asks at the first tick. A tick never re-enters itself: the request is
-- a packet of its own.
SplicedTickets.inTick = false
SplicedTickets.tick = function(why)
	if SplicedTickets.inTick then return end
	SplicedTickets.inTick = true
	pcall(function()
		if not SplicedTickets.loggedOn() then
			if SplicedTickets.requested then
				SplicedTickets.requested = false; SplicedTickets.verified = false
				log.debug("Spliced tickets: logged off; the next logon asks for app " .. SplicedTickets.requestApp .. "'s ticket again")
			end
			return
		end
		if not SplicedTickets.requested then
			if SplicedTickets.licencesLoaded() then SplicedTickets.request(nil, why) end
			return
		end
		if SplicedTickets.verified or SplicedTickets.getTicketTramp == nil then return end
		local this = SplicedTickets.engineClientUser()
		if this == nil then return end
		local n = SplicedTickets.readBack(this)
		if n > 0 then
			SplicedTickets.verified = true
			log.info("Spliced tickets: the ownership ticket of app " .. SplicedTickets.requestApp .. " is in memory (" .. n .. " bytes)")
		end
	end)
	SplicedTickets.inTick = false
end

-- The requested app's ticket, read through the trampoline (not this hook).
SplicedTickets.readBack = function(this)
	if SplicedTickets.rbBuf == nil then
		SplicedTickets.rbBuf = ffi.new("uint8_t[?]", 65536)
		SplicedTickets.rbOff = { ffi.new("uint32_t[1]"), ffi.new("uint32_t[1]"), ffi.new("uint32_t[1]"), ffi.new("uint32_t[1]") }
	end
	local o = SplicedTickets.rbOff
	return tonumber(SplicedTickets.getTicketTramp(this, SplicedTickets.requestApp, SplicedTickets.rbBuf, 65536, o[1], o[2], o[3], o[4])) or 0
end

if SLS ~= nil and SLS.registerCallback ~= nil then
	pcall(SLS.registerCallback, "Network::recvPkt", function() SplicedTickets.tick("logon, licences loaded") end)
	pcall(SLS.registerCallback, "Network::sendPkt", function() SplicedTickets.tick("logon, licences loaded") end)
	pcall(SLS.registerCallback, "SLSsteam::initialized", function() SplicedTickets.tick("initialized, logged on") end)
	SplicedTickets.tick("plugin loaded, logged on")
end

log.notify("spliced-tickets.lua loaded!")
