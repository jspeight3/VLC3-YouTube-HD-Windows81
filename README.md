# YouTubeVLC - High-Res YouTube Playback in VLC 3.x on Win 8.1

**Keep VLC 3.x alive for YouTube playback on Windows 8.1.**

YouTubeVLC enables VLC 3.x to play supported high-resolution YouTube videos using a local Python HLS gateway, yt-dlp, QuickJS, and FFmpeg.

Designed particularly for Windows 8.1 users who want to continue using VLC 3 without replacing their familiar media player.

## Why this project exists

Changes to YouTube's streaming formats can prevent reliable playback in VLC 3.x on Windows 8.1, especially for high-resolution videos requiring separate audio and video streams.

YouTubeVLC uses modern tools and a local HLS gateway to restore high-resolution playback, synchronized audio, and smooth seeking without replacing VLC.

## Features

- High-resolution YouTube playback in VLC 3.x
- Synchronized audio and video
- Smooth forward and backward seeking
- Multiple video sessions
- Automatic gateway startup and reuse
- Authenticated local streaming
- Recovery safeguards and idle-session cleanup
- Automatic and manual installation options

**Current maximum playback resolution is 1080p.** YouTubeVLC selects H.264 video and AAC audio for compatibility with VLC 3. Higher-resolution VP9 and AV1 streams are not currently supported.

## Requirements

- Windows with VLC 3.x
- Python 3.10 or newer, including pythonw.exe
- yt-dlp.exe
- qjs.exe (QuickJS)
- ffmpeg.exe

The three third-party executables are **not included** in this repository. Obtain them separately from their respective distributors.

Place `yt-dlp.exe`, `qjs.exe`, and `ffmpeg.exe` in the `app` directory, or install them in directories included in the persistent Windows User or Machine PATH. A temporary Command Prompt or Git Bash PATH entry is insufficient for reliable VLC startup.

### Dependency download sources

Obtain the required software from its official project:

| Dependency | Official source |
| --- | --- |
| VLC 3 | https://www.videolan.org/vlc/ |
| Python | https://www.python.org/ |
| yt-dlp | https://github.com/yt-dlp/yt-dlp |
| QuickJS | https://bellard.org/quickjs/ |
| FFmpeg | https://ffmpeg.org/ |

The installer does not download these tools. Make sure your
QuickJS distribution provides `qjs.exe`.

## Tested configurations

| Operating system | VLC | Python | Verification |
| --- | --- | --- | --- |
| Windows 8.1, 64-bit | 3.0.24, 64-bit | 3.10.6 | Installation, playback, synchronized audio/video, seeking, second video, automatic startup |
| Windows 8.1, 64-bit | 3.0.21, 64-bit | 3.10.11 | Clean VM installation, playback, seeking, shutdown, idle cleanup |
| Windows 8.1 | 3.0.17 | 3.10.6 | Development and integration testing |

The primary validated platform is **Windows 8.1 with VLC 3 (64-bit)**.

Other Windows versions and VLC releases may work, but have not
all been independently tested. VLC 4 and 32-bit VLC are not
validated release targets.

## Option 1: Automatic installation

1. Download or clone this repository.
2. Install Python and the required dependencies.
3. Open Git Bash, PowerShell, or Command Prompt in the repository directory.
4. Check the installation requirements:

   `python setup_youtube_vlc.py --check`

5. Install:

   `python setup_youtube_vlc.py --install`

If an existing YouTubeVLC bridge is detected, the installer
will refuse to overwrite it without explicit permission.

To authorize replacement:

`python setup_youtube_vlc.py --install --replace`

Close VLC before installing or replacing the bridge.
Restart VLC afterward.

### What the automatic installer does

The installer:

- Checks the required application files and executable dependencies.
- Checks Python and `pythonw.exe` availability.
- Copies the Lua playlist bridge into VLC's user configuration.
- Configures the application directory and Python interpreter paths.
- Creates or reuses the local installation authentication token.
- Refuses to overwrite an existing integration unless `--replace`
  is explicitly supplied.

For a disposable installation test that does not modify your real
VLC configuration, run:

`python setup_youtube_vlc.py --test`

### What the installer does NOT do

The installer does **not**:

- Install or upgrade VLC or Python.
- Download or install yt-dlp, QuickJS, or FFmpeg.
- Add executable directories to the permanent Windows PATH.
- Upgrade Windows or modify the VLC program installation.
- Automatically update external dependencies.
- Guarantee playback of every YouTube video or resolution.

You must install VLC and Python separately, obtain the three external
executables, place them in `app` or persistent Windows PATH, and
restart VLC after installing the integration.

## Option 2: Manual installation

1. Install Python, yt-dlp, QuickJS, and FFmpeg.
2. Keep the files from `app` together in an application folder.
3. Create `youtube_vlc_pythonw.txt` inside that application folder.
   Its first line must be the absolute path to `pythonw.exe`.
4. Copy `youtube_bridge.lua` to:

   `%APPDATA%\vlc\lua\playlist\00_youtube_bridge.lua`

5. Create `youtube_vlc_path.txt` in that same VLC playlist directory.
   Its first line must be the absolute path to the application folder.
6. Generate the installation token by running this command
   from the repository directory:

   `python -c "import sys; sys.path.insert(0, 'app'); from youtube_vlc_security import get_install_token; get_install_token()"`

   This creates or reuses:

   `%LOCALAPPDATA%\YouTubeVLC\install.token`

7. Restart VLC.

The installation token is local and must not be published,
shared, or committed to Git.

## Playback

Open VLC and press Ctrl+N.

Paste a supported YouTube video URL and press Play.

The Lua bridge starts the local gateway automatically when needed.
The gateway then creates an HLS session for the video.

The Python gateway runs on localhost port 18761.
Child video sessions use localhost ports 18960-18979.

The gateway may remain running after VLC closes.

### First playback may take longer

**The first startup may take longer because Python must start the
local gateway and yt-dlp must resolve the YouTube video's streams.**

Subsequent videos can reuse the running gateway, reducing some
startup overhead. Actual loading time depends on available formats,
network conditions, and the installed dependencies.

## Security

- HTTP servers bind to 127.0.0.1.
- Video requests require a locally generated installation token.
- Each child session has a separate temporary access token.
- The shutdown interface has separate token authentication.
- Installation tokens and machine-specific paths are excluded
  from Git using `.gitignore`.

Do not expose the local HTTP ports to the internet.

## Troubleshooting

If playback does not begin:

1. Confirm Python, pythonw.exe, yt-dlp, qjs, and FFmpeg are installed.
2. Run `python setup_youtube_vlc.py --check`.
3. Verify both local configuration files contain correct Windows paths.
4. Verify the installation token exists.
5. Restart VLC.

## Common playback problems

**YouTube videos do not open in VLC 3:** Check the dependencies
using `python setup_youtube_vlc.py --check`, verify the application
path, and restart VLC.

**YouTube playback starts slowly:** The local Python gateway may
need to start and yt-dlp must resolve the video's streams. This
is particularly noticeable on the first request.

**Seeking does not work as expected:** Available media formats
vary between videos. Playback also depends on network conditions
and decoding performance.

**Previously working videos stop playing:** YouTube can change
its extraction requirements. Updating yt-dlp and its required
JavaScript runtime may restore compatibility.

**VLC 3 on Windows 8.1:** This project is specifically intended
to provide an alternative YouTube playback pipeline for users
who wish to keep using VLC 3 on Windows 8.1.

## Testing and limitations

The configurations listed above have been tested on Windows 8.1.

Verified functionality includes authenticated playback, synchronized
audio/video, forward and backward seeking, multiple video sessions,
automatic gateway startup and reuse, graceful shutdown, and
idle-session cleanup on subsequent video requests.

The Windows launcher has been tested with dependencies supplied
through the application directory or persistent Windows PATH.

Recovery safeguards have been checked using simulated process
records and actual Windows process command lines. However, a
complete unexpected-crash-and-restart integration test has not
been performed.

Manual installation instructions are based on the verified
automatic installer's configuration format, but the manual procedure
has not been independently integration-tested.

YouTube streaming requirements and third-party tools can change.
Compatibility with every video, resolution, or future dependency
version is not guaranteed.
