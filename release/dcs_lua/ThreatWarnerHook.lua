-- ============================================================================
--  DCS Auto-GCI — Hook Script  (OPTIONAL — adds mission-event & AWACS data)
--
--  Captures DCS mission events (shots fired, hits, etc.) and AWACS/EWR
--  radar detections, then sends them to the companion app via UDP.
--
--  INSTALLATION
--    Copy this file to:
--      %USERPROFILE%\Saved Games\DCS\Scripts\Hooks\ThreatWarnerHook.lua
--    (Create the Hooks folder if it doesn't exist.)
--
--  NO changes to MissionScripting.lua are required.  All network I/O
--  happens inside the hook environment, which has unrestricted access
--  to LuaSocket.  The mission scripting environment is only used for
--  reading game-world data (events, coalition detections).
-- ============================================================================

local tw_hook = {}
tw_hook.injected   = false
tw_hook.hookSocket = nil
tw_hook.lastPoll   = 0
tw_hook.POLL_SEC   = 2          -- how often the hook reads mission-env data

-- ── Utility: send one line via hook-level UDP ─────────────────────────
local function tw_send(line)
    if tw_hook.hookSocket and line ~= "" then
        pcall(function() tw_hook.hookSocket:send(line) end)
    end
end

-- ── Called when a mission finishes loading ─────────────────────────────
function tw_hook.onMissionLoadEnd()
    tw_hook.injected = false
    tw_hook.lastPoll = 0

    -- Create a hook-level UDP socket (hooks have full LuaSocket access)
    if not tw_hook.hookSocket then
        local sok, socketLib = pcall(require, "socket")
        if sok then
            tw_hook.hookSocket = socketLib.udp()
            tw_hook.hookSocket:settimeout(0)
            tw_hook.hookSocket:setpeername("127.0.0.1", 9876)
        end
    end

    -- ── Inject event handler into mission env ─────────────────────────
    -- No socket required — events are queued in a global table that
    -- the hook layer reads periodically via onSimulationFrame().
    local injectCode = [[
        do
            AUTOGCI_EVENT_QUEUE = AUTOGCI_EVENT_QUEUE or {}

            local handler = {}

            function handler:onEvent(e)
                -- S_EVENT_SHOT  (weapon launched)
                if e.id == world.event.S_EVENT_SHOT then
                    local shooter = "Unknown"
                    if e.initiator and e.initiator.getName then
                        local ok, n = pcall(e.initiator.getName, e.initiator)
                        if ok then shooter = n end
                    end
                    local weapon = "Unknown"
                    if e.weapon and e.weapon.getTypeName then
                        local ok, n = pcall(e.weapon.getTypeName, e.weapon)
                        if ok then weapon = n end
                    end
                    table.insert(AUTOGCI_EVENT_QUEUE,
                                 "EVENT:SHOT|" .. shooter .. "|" .. weapon)

                -- S_EVENT_HIT  (unit was hit)
                elseif e.id == world.event.S_EVENT_HIT then
                    local target = "Unknown"
                    if e.target and e.target.getName then
                        local ok, n = pcall(e.target.getName, e.target)
                        if ok then target = n end
                    end
                    local weapon = e.weapon_name or "Unknown"
                    table.insert(AUTOGCI_EVENT_QUEUE,
                                 "EVENT:HIT|" .. target .. "|" .. weapon)

                -- S_EVENT_SHOOTING_START  (gun burst started)
                elseif e.id == world.event.S_EVENT_SHOOTING_START then
                    local shooter = "Unknown"
                    if e.initiator and e.initiator.getName then
                        local ok, n = pcall(e.initiator.getName, e.initiator)
                        if ok then shooter = n end
                    end
                    table.insert(AUTOGCI_EVENT_QUEUE,
                                 "EVENT:SHOOTING|" .. shooter)

                -- S_EVENT_PILOT_DEAD
                elseif e.id == world.event.S_EVENT_PILOT_DEAD then
                    table.insert(AUTOGCI_EVENT_QUEUE, "EVENT:PILOT_DEAD|")
                end
            end

            world.addEventHandler(handler)
        end
    ]]

    local ok, _ = pcall(function()
        net.dostring_in('mission', injectCode)
    end)
    tw_hook.injected = ok

    -- ── Inject AWACS/EWR detection polling into mission env ───────────
    -- Results are stored in a global string; no socket needed in mission.
    local mySide = 0
    local myId = net.get_my_player_id()
    if myId then
        local info = net.get_player_info(myId)
        if info then mySide = info.side or 0 end
    end

    local awacsCode = [[
        do
            AUTOGCI_PLAYER_SIDE = ]] .. tostring(mySide) .. [[

            AUTOGCI_AWACS_DATA = ""

            local function awacsPoll()
                local side = AUTOGCI_PLAYER_SIDE
                if not side or side < 1 then
                    AUTOGCI_AWACS_DATA = ""
                    return
                end
                local lines = {}
                local seen = {}
                local cats = {Group.Category.AIRPLANE, Group.Category.GROUND}
                for _, gc in ipairs(cats) do
                    local ok1, groups = pcall(coalition.getGroups, side, gc)
                    if ok1 and groups then
                        for _, grp in ipairs(groups) do
                            if grp and grp:isExist() then
                                local ctrl = grp:getController()
                                if ctrl then
                                    local ok2, tgts = pcall(
                                        ctrl.getDetectedTargets, ctrl,
                                        Controller.Detection.RADAR)
                                    if ok2 and tgts then
                                        for _, det in ipairs(tgts) do
                                            local obj = det.object
                                            if obj and obj.isExist
                                               and obj:isExist() then
                                                local id =
                                                    tonumber(obj:getID()) or 0
                                                if not seen[id] then
                                                    seen[id] = true
                                                    local ok3, p = pcall(
                                                        obj.getPoint, obj)
                                                    if ok3 and p then
                                                        local lat, lon, alt =
                                                            coord.LOtoLL(p)
                                                        local oc =
                                                            obj:getCoalition()
                                                        if oc ~= side
                                                           and oc ~= 0 then
                                                            local cat = "AIR"
                                                            local ok4, d = pcall(
                                                                obj.getDesc, obj)
                                                            if ok4 and d
                                                               and (d.category == 2
                                                                or d.category == 3)
                                                            then
                                                                cat = "GROUND"
                                                            end
                                                            local hdg = 0
                                                            local ok5, upos = pcall(
                                                                obj.getPosition, obj)
                                                            if ok5 and upos
                                                               and upos.x then
                                                                hdg = math.atan2(
                                                                    upos.x.z,
                                                                    upos.x.x)
                                                                if hdg < 0 then
                                                                    hdg = hdg
                                                                        + 6.2831853
                                                                end
                                                            end
                                                            local tn = "Unknown"
                                                            local ok6, n = pcall(
                                                                obj.getTypeName, obj)
                                                            if ok6 and n then
                                                                tn = n
                                                            end
                                                            lines[#lines + 1] =
                                                                string.format(
                                                                "AWACS:%s|%d|%s"
                                                                .. "|%.6f|%.6f"
                                                                .. "|%.1f|%.4f|%d",
                                                                cat, id, tn,
                                                                lat, lon, alt,
                                                                hdg, oc)
                                                        end
                                                    end
                                                end
                                            end
                                        end
                                    end
                                end
                            end
                        end
                    end
                end
                AUTOGCI_AWACS_DATA = table.concat(lines, "\n")
            end

            local function awacsTimer(_, t)
                pcall(awacsPoll)
                return t + 10.0
            end
            timer.scheduleFunction(awacsTimer, nil, timer.getTime() + 2)
        end
    ]]

    pcall(function()
        net.dostring_in('mission', awacsCode)
    end)
end

-- ── Per-frame: relay data from mission env to companion app via UDP ───
function tw_hook.onSimulationFrame()
    if not tw_hook.hookSocket then return end

    -- Throttle reads to every POLL_SEC seconds
    local now = DCS.getRealTime()
    if now - tw_hook.lastPoll < tw_hook.POLL_SEC then return end
    tw_hook.lastPoll = now

    -- Read & forward AWACS detections
    local ok1, awacsData = pcall(function()
        return net.dostring_in('mission', 'return AUTOGCI_AWACS_DATA or ""')
    end)
    if ok1 and awacsData and awacsData ~= "" then
        for line in awacsData:gmatch("[^\n]+") do
            tw_send(line)
        end
    end

    -- Read & forward queued events (and clear the queue)
    local ok2, eventData = pcall(function()
        return net.dostring_in('mission', [[
            local q = AUTOGCI_EVENT_QUEUE or {}
            AUTOGCI_EVENT_QUEUE = {}
            return table.concat(q, "\n")
        ]])
    end)
    if ok2 and eventData and eventData ~= "" then
        for line in eventData:gmatch("[^\n]+") do
            tw_send(line)
        end
    end
end

-- ── Clean up on mission stop ──────────────────────────────────────────
function tw_hook.onSimulationStop()
    tw_hook.injected = false
    tw_hook.lastPoll = 0
end

-- ── Update player side when slot changes ──────────────────────────────
function tw_hook.onPlayerChangeSlot(id)
    if id == net.get_my_player_id() then
        local info = net.get_player_info(id)
        if info then
            pcall(function()
                net.dostring_in('mission',
                    'AUTOGCI_PLAYER_SIDE = ' .. tostring(info.side or 0))
            end)
        end
    end
end

-- ── Register the hook ──────────────────────────────────────────────────
DCS.setUserCallbacks(tw_hook)
