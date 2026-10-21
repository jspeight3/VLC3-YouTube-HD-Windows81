-- YouTube network-stream bridge for VLC 3.x
-- Uses the existing local Python / yt-dlp / FFmpeg pipeline.

local function to_hex(s)
    return (s:gsub(".", function(c)
        return string.format("%02x", string.byte(c))
    end))
end

function probe()
    if vlc.access ~= "https" then
        return false
    end

    local path = vlc.path or ""

    return (
        path:match("^www%.youtube%.com/watch%?")
        or path:match("^m%.youtube%.com/watch%?")
        or path:match("^music%.youtube%.com/watch%?")
        or path:match("^youtube%.com/watch%?")
        or path:match("^youtu%.be/[%w_-]+")
    ) ~= nil
end



local function gateway_running()
    if type(vlc.stream) ~= "function" then
        return false
    end

    local ok, stream = pcall(
        vlc.stream,
        "http://127.0.0.1:18761/health"
    )

    return ok and stream ~= nil and stream ~= false
end

local function read_app_directory()
    local appdata = os.getenv("APPDATA")

    if not appdata or appdata == "" then
        return nil
    end

    local config_path =
        appdata .. "\\vlc\\lua\\playlist\\youtube_vlc_path.txt"

    local file = io.open(config_path, "r")

    if not file then
        return nil
    end

    local directory = file:read("*l")
    file:close()

    if not directory then
        return nil
    end

    directory = directory:match("^%s*(.-)%s*$")

    if directory == "" then
        return nil
    end

    return directory
end

local function ensure_gateway()
    if gateway_running() then
        return true
    end

    local directory = read_app_directory()

    if not directory then
        vlc.msg.err("YouTubeVLC: Installation path missing")
        return false
    end

    local launcher =
        directory .. "\\VLC-AutoStart-18761-CANDIDATE.vbs"

    local command =
        'wscript.exe //B //Nologo "' .. launcher .. '"'

    local result = os.execute(command)

    return result ~= false and result ~= nil
end

local function read_install_token()
    local localappdata = os.getenv("LOCALAPPDATA")

    if not localappdata or localappdata == "" then
        return nil
    end

    local token_path =
        localappdata .. "\\YouTubeVLC\\install.token"

    local file = io.open(token_path, "r")

    if not file then
        return nil
    end

    local token = file:read("*l")
    file:close()

    if not token then
        return nil
    end

    if #token ~= 43 or token:find("[^%w_-]") then
        return nil
    end

    return token
end

function parse()
    local url = vlc.access .. "://" .. vlc.path
    local token = read_install_token()

    if not token then
        vlc.msg.err("YouTubeVLC: Installation token missing")
        return {}
    end

    if not ensure_gateway() then
        vlc.msg.err("YouTube HLS startup failed")
        return {}
    end


    return {
        {
            path =
                "http://127.0.0.1:18761/video/"
                .. token .. "/" .. to_hex(url),
            name = "YouTube HLS Candidate",
            options = {
                "network-caching=1500",
                "no-lua"
            }
        }
    }
end
