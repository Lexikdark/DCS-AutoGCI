-- ============================================================================
--  DCS Auto-GCI — Export Script
--  Sends player telemetry and detected threats to the companion app via UDP.
--
--  INSTALLATION
--    Copy this file to (or append its contents to):
--      %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
--    For Open Beta use:
--      %USERPROFILE%\Saved Games\DCS.openbeta\Scripts\Export.lua
--
--    If you already have an Export.lua (e.g. for Helios, SRS, etc.), paste
--    the entire contents of this file AT THE END of your existing Export.lua.
--    The script chains with any previously defined export callbacks.
-- ============================================================================

do -- wrap in do...end so local names never collide with other scripts

    -- ── Settings ──────────────────────────────────────────────────────
    local TW_HOST     = "127.0.0.1"
    local TW_PORT     = 9876
    local TW_INTERVAL = 0.1          -- seconds between updates
    local TW_MAX_RANGE_M = 150000    -- 150 km (~80 nm) for air/ground
    local TW_MAX_WPN_M   = 300000    -- 300 km for weapons in-flight

    -- ── Internal state ────────────────────────────────────────────────
    local tw_udp     = nil
    local tw_started = false
    local tw_sp_mode = true           -- SP detection on by default
    local tw_modeCheckNext = 0        -- when to re-read the flag file
    local tw_MODE_FILE = os.getenv("TEMP") .. "\\autogci_sp_mode.txt"

    -- ── LuaSocket loader ──────────────────────────────────────────────
    local function tw_initSocket()
        package.path  = package.path  .. ";.\\LuaSocket\\?.lua"
        package.cpath = package.cpath .. ";.\\LuaSocket\\?.dll"
        local ok, socketLib = pcall(require, "socket")
        if not ok then return nil end
        return socketLib
    end

    -- ── Safe UDP send ─────────────────────────────────────────────────
    local function tw_send(msg)
        if tw_udp then
            pcall(function() tw_udp:send(msg) end)
        end
    end

    -- ── Coalition helper (handles string or number) ───────────────────
    local function tw_isEnemy(selfCoal, objCoal)
        if selfCoal == nil or objCoal == nil then return false end
        if selfCoal == objCoal then return false end
        -- Skip neutrals
        if objCoal == 0 or objCoal == "0" or objCoal == ""
           or objCoal == "Neutral" or objCoal == "Neutrals" then
            return false
        end
        return true
    end

    -- ── Rough distance (degrees → metres) for quick filtering ─────────
    local function tw_approxDistM(lat1, lon1, lat2, lon2)
        local dlat = lat1 - lat2
        local dlon = (lon1 - lon2) * math.cos(math.rad((lat1 + lat2) / 2))
        return math.sqrt(dlat * dlat + dlon * dlon) * 111320
    end

    -- ── Preserve any existing export callbacks ────────────────────────
    local tw_prevStart      = LuaExportStart
    local tw_prevStop       = LuaExportStop
    local tw_prevNextEvent  = LuaExportActivityNextEvent
    local tw_prevBefore     = LuaExportBeforeNextFrame
    local tw_prevAfter      = LuaExportAfterNextFrame

    -- ── Read the SP-mode flag file (written by the companion app) ─────
    local function tw_readModeFlag(t)
        if t < tw_modeCheckNext then return end
        tw_modeCheckNext = t + 2.0   -- re-check every 2 seconds
        local f = io.open(tw_MODE_FILE, "r")
        if f then
            local v = f:read("*l")
            f:close()
            if v == "0" then tw_sp_mode = false
            else              tw_sp_mode = true
            end
        else
            tw_sp_mode = true  -- default: SP on when flag missing
        end
    end

    -- ── LuaExportStart ────────────────────────────────────────────────
    LuaExportStart = function()
        local socketLib = tw_initSocket()
        if socketLib then
            tw_udp = socketLib.udp()
            tw_udp:settimeout(0)
            tw_udp:setpeername(TW_HOST, TW_PORT)
            tw_send("STATUS:CONNECTED")
            tw_started = true
            log.write("DCS-AutoGCI", log.INFO, "Export started — sending to "
                       .. TW_HOST .. ":" .. TW_PORT)
        else
            log.write("DCS-AutoGCI", log.WARNING, "LuaSocket not available")
        end
        if tw_prevStart then tw_prevStart() end
    end

    -- ── LuaExportStop ─────────────────────────────────────────────────
    LuaExportStop = function()
        if tw_started then
            tw_send("STATUS:DISCONNECTED")
            if tw_udp then pcall(function() tw_udp:close() end) end
            tw_udp = nil
            tw_started = false
        end
        if tw_prevStop then tw_prevStop() end
    end

    -- ── LuaExportActivityNextEvent ────────────────────────────────────
    LuaExportActivityNextEvent = function(t)
        if not tw_started then
            if tw_prevNextEvent then return tw_prevNextEvent(t) end
            return t + 1.0
        end

        -- Re-read the mode flag periodically
        tw_readModeFlag(t)

        -- Player telemetry
        local selfOk, selfData = pcall(LoGetSelfData)
        if selfOk and selfData then
            tw_send(string.format("SELF:%s|%.6f|%.6f|%.1f|%.4f",
                selfData.Name or "Unknown",
                selfData.LatLongAlt.Lat,
                selfData.LatLongAlt.Long,
                selfData.LatLongAlt.Alt,
                selfData.Heading))

            local myCoal = selfData.Coalition
            local myLat  = selfData.LatLongAlt.Lat
            local myLon  = selfData.LatLongAlt.Long

            -- ── World objects (threats) ───────────────────────────────
            -- Only called when Single-Player mode is active (avoids IC
            -- flags on multiplayer servers that restrict this function).
            if tw_sp_mode then
                local wOk, objects = pcall(LoGetWorldObjects)
                if wOk and objects then
                    for id, obj in pairs(objects) do
                        if tw_isEnemy(myCoal, obj.Coalition) and obj.Type and obj.LatLongAlt then
                            local lvl1 = obj.Type.level1
                            local category = nil
                            local maxRange = TW_MAX_RANGE_M

                            if lvl1 == 4 then          -- Weapon (missile / bomb / rocket)
                                -- Skip artillery shells (level2==1) to avoid spam
                                if obj.Type.level2 ~= 1 then
                                    category = "WEAPON"
                                    maxRange = TW_MAX_WPN_M
                                end
                            elseif lvl1 == 1 then      -- Aircraft / Helicopter
                                category = "AIR"
                            elseif lvl1 == 2 then      -- Ground (SAM, AAA, vehicles)
                                category = "GROUND"
                            end

                            if category then
                                local d = tw_approxDistM(myLat, myLon,
                                                         obj.LatLongAlt.Lat,
                                                         obj.LatLongAlt.Long)
                                if d < maxRange then
                                    tw_send(string.format(
                                        "THREAT:%s|%s|%s|%.6f|%.6f|%.1f|%.4f|%d",
                                        category,
                                        tostring(id),
                                        obj.Name or "Unknown",
                                        obj.LatLongAlt.Lat,
                                        obj.LatLongAlt.Long,
                                        obj.LatLongAlt.Alt,
                                        obj.Heading or 0,
                                        type(obj.Coalition) == "number"
                                            and obj.Coalition or 0))
                                end
                            end
                        end
                    end
                end
            end  -- tw_sp_mode

            -- ── Fallback: TWS contacts (F-15C) ───────────────────────
            local twsOk, twsInfo = pcall(LoGetTWSInfo)
            if twsOk and twsInfo and twsInfo.Targets then
                for i, tgt in ipairs(twsInfo.Targets) do
                    if tgt.Position then
                        tw_send(string.format(
                            "THREAT:AIR|tws_%d|TWS Contact|%.6f|%.6f|%.1f|0|0",
                            i,
                            tgt.Position.Lat or 0,
                            tgt.Position.Long or 0,
                            tgt.Position.Alt or 0))
                    end
                end
            end

            -- ── Fallback: Locked target ───────────────────────────────
            local ltOk, locked = pcall(LoGetLockedTargetInformation)
            if ltOk and locked then
                -- locked may be a table with position info
                if locked.LatLongAlt then
                    tw_send(string.format(
                        "THREAT:AIR|locked_0|Locked Target|%.6f|%.6f|%.1f|0|0",
                        locked.LatLongAlt.Lat or 0,
                        locked.LatLongAlt.Long or 0,
                        locked.LatLongAlt.Alt or 0))
                end
            end
        end

        -- Chain other export scripts & determine next call time
        local nextTime = t + TW_INTERVAL
        if tw_prevNextEvent then
            local otherTime = tw_prevNextEvent(t)
            if otherTime and otherTime < nextTime then
                nextTime = otherTime
            end
        end
        return nextTime
    end

    -- ── Pass-through frame callbacks ──────────────────────────────────
    LuaExportBeforeNextFrame = function()
        if tw_prevBefore then tw_prevBefore() end
    end

    LuaExportAfterNextFrame = function()
        if tw_prevAfter then tw_prevAfter() end
    end

end -- do
