# DCS Auto-GCI

A standalone companion app for **DCS World** that detects what is shooting at you (or near you) and announces threats with **on-screen text** and **text-to-speech**.

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![DCS](https://img.shields.io/badge/DCS_World-2.8+-green)

---

## What It Does

| Feature | Details |
|---------|---------|
| **Enemy aircraft detection** | Bandits within ~80 nm shown with clock position, distance, altitude |
| **SAM / AAA detection** | Ground threats displayed with bearing and range |
| **Missile warning** | Incoming missiles announced immediately |
| **Formation grouping** | Groups of aircraft announced together — *"Group of 4, Flankers, 3 o'clock, 65 miles, Angels 25"* instead of individual spam |
| **Mission events** | Shot launches, hits, and gun fire detected (with optional hook) |
| **Natural TTS speech** | 350+ DCS unit names converted to spoken-friendly names (e.g. `FA-18C_hornet` → "Hornet") |
| **Text-to-speech** | Spoken callouts like *"Warning! Missile, 3 o'clock, 12 miles"* |
| **Voice & device selection** | Choose any installed SAPI5 voice and audio output device |
| **Volume control** | Adjustable TTS volume slider (0–100) |
| **OneCore voice unlock** | One-click button to unlock ~20 hidden high-quality Windows voices |
| **Visual threat table** | Color-coded list — red for weapons, orange for air, yellow for ground |
| **Event log** | Timestamped history of all threat events |
| **Integrated settings** | All options in a built-in settings panel (no separate dialog) |

---

## Requirements

- **DCS World** (any edition — Stable or Open Beta)
- **Windows 10/11** (SAPI5 TTS is built-in)

For running from source (not needed if using the installer):
- **Python 3.8+** — [Download](https://www.python.org/downloads/)
- **comtypes** — `pip install comtypes`

---

## Installation

### Option A: Setup Installer (Recommended)

1. Run **`DCS_AutoGCI_Setup.exe`**
2. Click **Install** — the installer automatically:
   - Places `DCS Auto-GCI.exe` in your local app data
   - Installs the DCS Lua scripts to both `Saved Games\DCS\Scripts` and `Saved Games\DCS.openbeta\Scripts`
   - Creates Desktop and Start Menu shortcuts
3. Launch **DCS Auto-GCI** from the Desktop or Start Menu

To uninstall, run the Setup.exe again and click **Uninstall**, or use Windows **Settings → Apps → DCS Auto-GCI → Uninstall**.

### Option B: Run from Source

```bash
cd C:\DCS-ThreatWarner
pip install -r requirements.txt
python auto_gci.py
```

Then manually copy the Lua scripts (see below).

### Manual Lua Script Installation

If running from source, copy the scripts yourself:

**Export script (required):**
```
Copy:  dcs_lua\ThreatWarnerExport.lua
To:    %USERPROFILE%\Saved Games\DCS\Scripts\ThreatWarnerExport.lua
       %USERPROFILE%\Saved Games\DCS.openbeta\Scripts\ThreatWarnerExport.lua
```

**Hook script (optional — adds mission event detection):**
```
Copy:  dcs_lua\ThreatWarnerHook.lua
To:    %USERPROFILE%\Saved Games\DCS\Scripts\Hooks\ThreatWarnerHook.lua
       %USERPROFILE%\Saved Games\DCS.openbeta\Scripts\Hooks\ThreatWarnerHook.lua
```

> **Already have an Export.lua?** (e.g., for SRS, Helios, DCS-BIOS)
> Open your existing `Export.lua` in a text editor and paste the contents of `ThreatWarnerExport.lua` at the **end** of the file.

### Hook Script Setup (Optional)

The hook script provides mission event detection (someone fires a missile, you get hit, etc.) on top of the polling-based detection. It needs LuaSocket available:

1. Edit `<DCS Install Dir>\Scripts\MissionScripting.lua`
2. Comment out these two lines (add `--` in front):
```lua
--sanitizeModule('os')
--sanitizeModule('io')
```

> This is the same change required by MOOSE, MIST, and other DCS scripting frameworks.

---

## Usage

1. Start **DCS Auto-GCI** (from shortcut or `python auto_gci.py`)
2. Start a DCS mission — the app shows **"CONNECTED"** when receiving data
3. Threats appear in the color-coded table and are announced via TTS

### Settings Panel

The right side of the app window contains an integrated settings panel:

| Setting | Description |
|---------|-------------|
| **TTS Voice** | Select from all installed Windows SAPI5 voices |
| **Audio Output** | Choose which audio device plays the TTS callouts |
| **Speech Rate** | Adjust TTS speed (words per minute) |
| **Volume** | Adjust TTS volume (0–100) |
| **Max Threat Range** | Detection range in nautical miles |
| **Threat Timeout** | Seconds before a threat is removed from the table |
| **Test TTS** | Speaks a sample callout to verify voice and device |
| **⚡ Unlock OneCore Voices** | One-click button to unlock ~20 hidden high-quality Windows voices (requires admin) |

### Testing Without DCS

1. Start the app: `python auto_gci.py` (or launch the exe)
2. In a second terminal: `python test_sender.py`
3. The test sender runs a scripted 90-second combat scenario with:
   - SAM sites activating (SA-11, S-300, SA-6, Tor, Pantsir)
   - Formation flights (4-ship MiG-29s, 2-ship Flankers, 3x Hinds)
   - Missile launches and events
   - Ships, helicopters, and bombers with escorts
4. Formation grouping callouts play — e.g. *"Group of 4, Mig 29, 3 o'clock, 65 miles, Angels 20"*

---

## How It Works

```
┌─────────────────────┐        UDP (localhost:9876)        ┌─────────────────────┐
│      DCS World      │ ──────────────────────────────────►│   DCS Auto-GCI      │
│                     │   Player position, threats,        │   (Python app)      │
│  Export.lua polls   │   mission events                   │                     │
│  LoGetSelfData()    │                                    │  • Calculates       │
│  LoGetWorldObjects()│                                    │    bearing/distance  │
│                     │                                    │  • Clock position   │
│  Hook script sends  │                                    │  • GUI display      │
│  shot/hit events    │                                    │  • TTS callouts     │
└─────────────────────┘                                    └─────────────────────┘
```

### Detection Methods

| Method | Source | Reliability |
|--------|--------|-------------|
| `LoGetWorldObjects()` | Export.lua | Works in most DCS versions; may be restricted in multiplayer anti-cheat servers |
| `LoGetTWSInfo()` | Export.lua | F-15C specific — provides TWS radar contacts |
| `LoGetLockedTargetInformation()` | Export.lua | Works on most aircraft with radar |
| Mission events (`S_EVENT_SHOT`, etc.) | Hook script | Very reliable; requires MissionScripting.lua modification |

---

## Configuration

Settings are managed directly in the app's integrated settings panel. They are saved to `autogci_settings.json` next to the executable and persist across sessions.

For the DCS Lua scripts, edit the constants at the top of each file:

### ThreatWarnerExport.lua
| Setting | Default | Description |
|---------|---------|-------------|
| `TW_PORT` | 9876 | UDP port (must match the Python app) |
| `TW_INTERVAL` | 0.1 | Polling interval in seconds |
| `TW_MAX_RANGE_M` | 150000 | Max detection range for air/ground (meters) |
| `TW_MAX_WPN_M` | 300000 | Max detection range for weapons (meters) |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| App says "WAITING FOR DCS" | Make sure the Lua scripts are in the correct Saved Games folder and you're in a mission |
| No threats appear | `LoGetWorldObjects()` may be blocked. Install the Hook script for event-based detection |
| TTS not working | Verify a voice is selected in the settings panel. Try the **Test TTS** button |
| No voices in dropdown | Check **Settings → Time & Language → Speech** and install voices |
| Port conflict | Change the UDP port in both the app settings and the Lua script |
| Existing Export.lua breaks | Make sure you **appended** the Auto-GCI export code, not replaced the file |
| Setup.exe won't uninstall | Use **Settings → Apps → DCS Auto-GCI → Uninstall** in Windows |

---

## File Structure

```
DCS-ThreatWarner/
├── auto_gci.py                   # Main Python GUI application
├── build_exe.bat                 # Build script (EXE → MSI → Setup.exe)
├── Package.wxs                   # WiX MSI installer source
├── Bundle.wxs                    # WiX Setup.exe bootstrapper source
├── README.md                     # This file
├── DCS_AutoGCI_README.html       # HTML help / user guide
├── requirements.txt              # Python dependencies (comtypes)
├── test_sender.py                # Test script (scripted combat scenario)
├── dcs_lua/
│   ├── ThreatWarnerExport.lua    # DCS Export script (REQUIRED)
│   └── ThreatWarnerHook.lua      # DCS Hook script (OPTIONAL)
└── release/                      # Clean distributable folder
    ├── DCS Auto-GCI.exe          # Standalone portable executable
    ├── DCS_AutoGCI_Setup.exe     # Installer (Install / Uninstall)
    ├── DCS_AutoGCI_README.html   # Help file (included with release)
    └── dcs_lua/                  # Lua scripts (for manual install)
        ├── ThreatWarnerExport.lua
        └── ThreatWarnerHook.lua
```

---

## Limitations

- **`LoGetWorldObjects()` availability** — Some DCS multiplayer servers with integrity checks may block this function. The hook script provides an alternative detection path.
- **Aircraft-specific RWR** — The current version uses universal detection. Future versions could read aircraft-specific RWR/TEWS cockpit parameters for more detailed threat info.
- **Friendly fire** — The app only tracks objects from a different coalition than the player. Friendly units are ignored.

---

## Building from Source

To rebuild the EXE and installer yourself:

1. Install prerequisites:
   - Python 3.8+ with `pip install pyinstaller comtypes`
   - .NET SDK 8+ (`dotnet --version`)
   - WiX toolset: `dotnet tool install --global wix`
   - WiX extensions: `wix extension add WixToolset.UI.wixext` and `wix extension add WixToolset.Bal.wixext`
2. Run `build_exe.bat` — builds the EXE and Setup.exe, packages docs and Lua scripts into a clean `release\` folder

---

## Adding More TTS Voices

The app lists every SAPI5 voice installed on your Windows system. By default you get **Microsoft David** (male) and **Microsoft Zira** (female).

### Method 1: Windows Speech Settings
1. Open **Settings \u2192 Time & Language \u2192 Speech**
2. Under "Manage voices", click **Add voices**
3. Select and install additional voices
4. Restart the app \u2014 new voices appear in the dropdown

### Method 2: Install Language Packs
1. Open **Settings \u2192 Time & Language \u2192 Language & Region**
2. Click **Add a language** and install a language pack (e.g., English (UK) adds Microsoft Hazel)
3. Each pack adds one or more voices

### Method 3: Unlock OneCore Voices (One-Click)
Windows 10/11 ships with ~20+ hidden "OneCore" voices (Aria, Jenny, Guy, Ryan, etc.) used by Narrator. DCS Auto-GCI can unlock them automatically:

1. Open the app and go to the **Settings** panel
2. Click the green **⚡ Unlock OneCore Voices** button
3. Click **Yes** on the Windows admin (UAC) prompt
4. The Voice dropdown refreshes automatically — select your new voice!

See the [HTML help file](DCS_AutoGCI_README.html) for a detailed manual method with step-by-step screenshots.

---

## License

Free to use and modify. No warranty. Not affiliated with Eagle Dynamics.
