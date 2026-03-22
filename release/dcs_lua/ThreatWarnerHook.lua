-- ============================================================================
--  DCS Auto-GCI — Hook Script  (OPTIONAL — adds mission-event detection)
--
--  Captures DCS mission events (shots fired, hits, etc.) and sends them
--  to the companion app via UDP for real-time voice & text alerts.
--
--  INSTALLATION
--    Copy this file to:
--      %USERPROFILE%\Saved Games\DCS\Scripts\Hooks\ThreatWarnerHook.lua
--    (Create the Hooks folder if it doesn't exist.)
--
--  REQUIREMENT
--    For this hook to inject the event handler into the mission scripting
--    environment, LuaSocket must be accessible from mission scripts.
--    Edit your MissionScripting.lua (in the DCS install directory under
--    Scripts\MissionScripting.lua) and ensure these two sanitize lines
--    are commented out:
--
--      --sanitizeModule('os')
--      --sanitizeModule('io')
--
--    Many DCS scripting frameworks (MOOSE, MIST) require the same change,
--    so you may already have this done.
--
--    If you are NOT comfortable modifying MissionScripting.lua, skip this
--    hook entirely — the Export script alone still provides threat detection.
-- ============================================================================

local tw_hook = {}
tw_hook.injected = false

-- ── Called when a mission finishes loading ─────────────────────────────
function tw_hook.onMissionLoadEnd()
    tw_hook.injected = false

    -- Inject an event handler into the MISSION scripting environment.
    -- net.dostring_in('mission', code) runs `code` inside the mission Lua
    -- state, which has access to world.addEventHandler, Unit, etc.
    local injectCode = [[
        do
            -- Try to load LuaSocket inside the mission env
            local sok, socket = pcall(require, "socket")
            if not sok then return end

            local udp = socket.udp()
            udp:settimeout(0)
            udp:setpeername("127.0.0.1", 9876)

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
                    udp:send("EVENT:SHOT|" .. shooter .. "|" .. weapon)

                -- S_EVENT_HIT  (unit was hit)
                elseif e.id == world.event.S_EVENT_HIT then
                    local target = "Unknown"
                    if e.target and e.target.getName then
                        local ok, n = pcall(e.target.getName, e.target)
                        if ok then target = n end
                    end
                    local weapon = e.weapon_name or "Unknown"
                    udp:send("EVENT:HIT|" .. target .. "|" .. weapon)

                -- S_EVENT_SHOOTING_START  (gun burst started)
                elseif e.id == world.event.S_EVENT_SHOOTING_START then
                    local shooter = "Unknown"
                    if e.initiator and e.initiator.getName then
                        local ok, n = pcall(e.initiator.getName, e.initiator)
                        if ok then shooter = n end
                    end
                    udp:send("EVENT:SHOOTING|" .. shooter)

                -- S_EVENT_PILOT_DEAD
                elseif e.id == world.event.S_EVENT_PILOT_DEAD then
                    udp:send("EVENT:PILOT_DEAD|")
                end
            end

            world.addEventHandler(handler)
        end
    ]]

    local ok, err = pcall(function()
        net.dostring_in('mission', injectCode)
    end)

    tw_hook.injected = ok
end

-- ── Register the hook ──────────────────────────────────────────────────
DCS.setUserCallbacks(tw_hook)
