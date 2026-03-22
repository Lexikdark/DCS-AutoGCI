#!/usr/bin/env python3
"""
DCS Auto-GCI - Standalone threat awareness application for DCS World.
Receives telemetry from DCS via UDP and provides visual + audio threat warnings.
"""

import socket
import threading
import math
import time
import json
import re
import os
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass, field
from typing import Dict, Set
import queue
import sys

try:
    import comtypes
    import comtypes.client
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("comtypes not installed. TTS disabled. Install with: pip install pyttsx3")

# --- Configuration ---
APP_VERSION = "1.0.0"
GITHUB_REPO = ""  # e.g. "YourUsername/DCS-AutoGCI"
UDP_HOST = "127.0.0.1"
UDP_PORT = 9876
GUI_UPDATE_MS = 500
NM_PER_METER = 0.000539957

# Settings file location (next to the exe / script)
SETTINGS_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]))
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "autogci_settings.json")

DEFAULT_SETTINGS = {
    "missile_range_nm": 80,
    "air_range_nm": 80,
    "ground_range_nm": 40,
    "track_missiles": True,
    "track_air": True,
    "track_ground": True,
    "tts_enabled": True,
    "tts_rate": 180,
    "announce_missiles": True,
    "announce_air": True,
    "announce_ground": True,
    "announce_events": True,
    "threat_timeout": 10,
    "weapon_timeout": 30,
    "tts_voice": "",
    "tts_device": "",
    "tts_volume": 100,
    "radio_filter": False,
    "radio_static_vol": 40,
    "radio_crackle_vol": 30,
    "theme": "Stealth Dark",
}


def load_settings():
    if os.path.isfile(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(saved)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


# --- DCS Export.lua auto-setup ---
DOFILE_LINE = "local twlfs=require('lfs');dofile(twlfs.writedir()..[[Scripts\\ThreatWarnerExport.lua]])"

def ensure_dcs_export():
    """Ensure Export.lua in each DCS Saved Games folder loads ThreatWarnerExport.lua."""
    results = []
    user = os.path.expanduser("~")
    for variant in ("DCS", "DCS.openbeta"):
        scripts_dir = os.path.join(user, "Saved Games", variant, "Scripts")
        export_lua = os.path.join(scripts_dir, "Export.lua")
        tw_lua = os.path.join(scripts_dir, "ThreatWarnerExport.lua")
        if not os.path.isfile(tw_lua):
            continue  # script not installed for this variant
        # Check if Export.lua already has the dofile line
        existing = ""
        if os.path.isfile(export_lua):
            try:
                with open(export_lua, "r", encoding="utf-8", errors="replace") as f:
                    existing = f.read()
            except OSError:
                continue
        if "ThreatWarnerExport.lua" in existing:
            results.append((variant, "ok"))
            continue
        # Append the dofile line
        try:
            os.makedirs(scripts_dir, exist_ok=True)
            with open(export_lua, "a", encoding="utf-8") as f:
                f.write(("\n" if existing and not existing.endswith("\n") else "") + DOFILE_LINE + "\n")
            results.append((variant, "added"))
        except OSError:
            results.append((variant, "error"))
    return results


# --- Theme Definitions ---
THEMES = {
    "GitHub Dark": {
        "BG": "#0d1117", "FG": "#e6edf3", "BG2": "#161b22", "BG3": "#21262d",
        "ACCENT": "#58a6ff", "RED": "#f85149", "ORANGE": "#f0883e",
        "YELLOW": "#d29922", "GREEN": "#3fb950", "DIM": "#484f58",
        "LIGHT": "#a5d6ff", "PURPLE": "#d2a8ff", "SUBTLE": "#8b949e",
        "HEADER": "#79c0ff",
    },
    "Midnight Tactical": {
        "BG": "#0a0e1a", "FG": "#e2e8f0", "BG2": "#111827", "BG3": "#1e293b",
        "ACCENT": "#f59e0b", "RED": "#ef4444", "ORANGE": "#f59e0b",
        "YELLOW": "#fbbf24", "GREEN": "#22c55e", "DIM": "#374151",
        "LIGHT": "#fde68a", "PURPLE": "#a78bfa", "SUBTLE": "#64748b",
        "HEADER": "#fbbf24",
    },
    "Stealth Dark": {
        "BG": "#000000", "FG": "#e0e0e0", "BG2": "#0a0a0a", "BG3": "#1a1a1a",
        "ACCENT": "#f59e0b", "RED": "#ff1744", "ORANGE": "#ff6d00",
        "YELLOW": "#ffea00", "GREEN": "#00e676", "DIM": "#333333",
        "LIGHT": "#80deea", "PURPLE": "#e040fb", "SUBTLE": "#616161",
        "HEADER": "#00b8d4",
    },
    "Operator Green": {
        "BG": "#0c1008", "FG": "#d4e7c5", "BG2": "#141e0f", "BG3": "#1e2d16",
        "ACCENT": "#4ade80", "RED": "#f87171", "ORANGE": "#fb923c",
        "YELLOW": "#facc15", "GREEN": "#86efac", "DIM": "#2d3b24",
        "LIGHT": "#bbf7d0", "PURPLE": "#c084fc", "SUBTLE": "#6b7c5e",
        "HEADER": "#22c55e",
    },
    "Cobalt Pro": {
        "BG": "#1e1e2e", "FG": "#cdd6f4", "BG2": "#181825", "BG3": "#313244",
        "ACCENT": "#89b4fa", "RED": "#f38ba8", "ORANGE": "#fab387",
        "YELLOW": "#f9e2af", "GREEN": "#a6e3a1", "DIM": "#45475a",
        "LIGHT": "#b4befe", "PURPLE": "#cba6f7", "SUBTLE": "#6c7086",
        "HEADER": "#74c7ec",
    },
    "Crimson Command": {
        "BG": "#121212", "FG": "#f5f5f5", "BG2": "#1a1a1a", "BG3": "#2a2a2a",
        "ACCENT": "#ff4c4c", "RED": "#ff6b6b", "ORANGE": "#ff8787",
        "YELLOW": "#ffd43b", "GREEN": "#51cf66", "DIM": "#3a3a3a",
        "LIGHT": "#ffa8a8", "PURPLE": "#da77f2", "SUBTLE": "#757575",
        "HEADER": "#ff8787",
    },
}

THEME_NAMES = list(THEMES.keys())

def _apply_theme(name):
    """Set module-level colour globals from a named theme."""
    global BG, FG, BG2, BG3, ACCENT, RED, ORANGE, YELLOW, GREEN
    global DIM, LIGHT, PURPLE, SUBTLE, HEADER
    t = THEMES.get(name, THEMES["Stealth Dark"])
    BG = t["BG"]; FG = t["FG"]; BG2 = t["BG2"]; BG3 = t["BG3"]
    ACCENT = t["ACCENT"]; RED = t["RED"]; ORANGE = t["ORANGE"]
    YELLOW = t["YELLOW"]; GREEN = t["GREEN"]; DIM = t["DIM"]
    LIGHT = t["LIGHT"]; PURPLE = t["PURPLE"]; SUBTLE = t["SUBTLE"]
    HEADER = t["HEADER"]

# Apply default theme at import time
_apply_theme(load_settings().get("theme", "Stealth Dark"))

FONT_UI = 'Segoe UI'
FONT_MONO = 'Consolas'


# --- Data Classes ---
@dataclass
class PlayerState:
    name: str = ""
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    heading_rad: float = 0.0


@dataclass
class Threat:
    uid: str
    category: str       # WEAPON, AIR, GROUND
    name: str
    lat: float
    lon: float
    alt: float
    heading: float
    coalition: int
    bearing_deg: float = 0.0
    distance_m: float = 0.0
    clock: str = "12"
    aspect: str = ""
    last_announced_nm: float = -1.0
    first_seen: float = 0.0
    last_seen: float = 0.0
    announced: bool = False


# --- Math Helpers ---
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calc_bearing(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def bearing_to_clock(relative_bearing_deg):
    clock = round(relative_bearing_deg / 30) % 12
    return str(clock if clock != 0 else 12)


def alt_to_angels(alt_m):
    ft = int(alt_m * 3.28084)
    if ft < 1000:
        return f"{ft} feet" if ft > 0 else "on the deck"
    return f"Angels {ft // 1000}"


def calc_aspect(bearing_to_bandit_deg, bandit_heading_rad):
    """Return target aspect: hot, cold, flanking left, or flanking right."""
    reverse = (bearing_to_bandit_deg + 180) % 360
    bandit_hdg = math.degrees(bandit_heading_rad) % 360
    raw_ta = (bandit_hdg - reverse + 360) % 360
    ta = raw_ta if raw_ta <= 180 else 360 - raw_ta
    if ta <= 30:
        return "hot"
    if ta >= 150:
        return "cold"
    crossing = (bandit_hdg - bearing_to_bandit_deg + 360) % 360
    return "flanking right" if crossing <= 180 else "flanking left"


RANGE_GATE_NM = 10  # re-announce air threats every 10 nm of closure


def clean_speech(text):
    """Make TTS-spoken text sound natural by expanding abbreviations,
    cleaning up DCS internal names, and adding pauses."""
    # Strip DCS weapon path prefixes
    text = re.sub(r'weapons\.missiles\.', '', text)
    text = re.sub(r'weapons\.bombs\.', '', text)
    text = re.sub(r'weapons\.nurs\.', '', text)
    text = re.sub(r'weapons\.torpedoes\.', '', text)
    text = re.sub(r'weapons\.shells\.', '', text)

    # ── AIRCRAFT (fixed-wing) ─────────────────────────────────────
    _aircraft = {
        # --- US / NATO Fighters ---
        'F-14A': 'Tomcat', 'F-14A-135-GR': 'Tomcat',
        'F-14B': 'Tomcat',
        'F-15C': 'Eagle', 'F-15ESE': 'Strike Eagle', 'F-15E': 'Strike Eagle',
        'F-16C_50': 'Viper', 'F-16C': 'Viper', 'F-16A': 'Viper',
        'F-16A MLU': 'Viper',
        'FA-18C_hornet': 'Hornet', 'F/A-18C': 'Hornet', 'F/A-18A': 'Hornet',
        'F-5E': 'F 5 Tiger', 'F-5E-3': 'F 5 Tiger',
        'F-4E': 'Phantom', 'F-4E-45MC': 'Phantom',
        'F-86F Sabre': 'Sabre',
        'F-117A': 'Nighthawk',
        # --- US Attack / CAS ---
        'A-10C': 'Warthog', 'A-10C_2': 'Warthog', 'A-10A': 'Warthog',
        'A-4E-C': 'Skyhawk',
        'AV8BNA': 'Harrier',
        # --- US Bombers ---
        'B-52H': 'B 52', 'B-1B': 'B 1 Lancer',
        'B-2A': 'Spirit',
        # --- US Support ---
        'E-3A': 'AWACS', 'E-2C': 'Hawkeye', 'E-2D': 'Hawkeye',
        'KC-135': 'Tanker', 'KC135MPRS': 'Tanker',
        'KC130': 'Tanker', 'KC-10': 'Tanker',
        'C-130': 'Hercules', 'C-17A': 'Globemaster',
        'C-5': 'Galaxy', 'C-2A': 'Greyhound',
        'S-3B': 'Viking', 'S-3B Tanker': 'Viking Tanker',
        'P-3C': 'Orion', 'EP-3': 'Orion',
        'U-2S': 'U 2 Dragon Lady', 'RQ-1A Predator': 'Predator',
        'MQ-9 Reaper': 'Reaper', 'MQ-1A Predator': 'Predator',
        # --- Russian Fighters ---
        'MiG-29A': 'Mig 29', 'MiG-29S': 'Mig 29 sierra',
        'MiG-29G': 'Mig 29', 'MiG-29K': 'Mig 29 kilo',
        'MiG-21Bis': 'Mig 21', 'MiG-23MLD': 'Mig 23',
        'MiG-25PD': 'Mig 25', 'MiG-25RBT': 'Mig 25',
        'MiG-31': 'Mig 31 Foxhound', 'MiG-19P': 'Mig 19',
        'MiG-15bis': 'Mig 15',
        'Su-27': 'Flanker', 'Su-30': 'Flanker',
        'Su-33': 'Flanker', 'J-11A': 'Flanker',
        'Su-34': 'Fullback', 'Su-57': 'Felon',
        # --- Russian Attack / Bombers ---
        'Su-25': 'Frogfoot', 'Su-25T': 'Frogfoot',
        'Su-25TM': 'Frogfoot',
        'Su-24M': 'Fencer', 'Su-24MR': 'Fencer',
        'Su-17M4': 'Fitter',
        'Tu-22M3': 'Backfire', 'Tu-95MS': 'Bear',
        'Tu-160': 'Blackjack', 'Tu-142': 'Bear',
        # --- Russian Support ---
        'A-50': 'Mainstay', 'Il-76MD': 'Candid', 'Il-78M': 'Midas',
        'An-26B': 'Curl', 'An-30M': 'Clank', 'Yak-40': 'Codling',
        # --- European ---
        'Tornado GR4': 'Tornado', 'Tornado IDS': 'Tornado', 'Tornado': 'Tornado',
        'Typhoon': 'Typhoon', 'EF-2000': 'Typhoon',
        'Rafale_M': 'Rafale', 'Rafale_B': 'Rafale',
        'M-2000C': 'Mirage 2000', 'Mirage-F1CE': 'Mirage F 1',
        'Mirage-F1BE': 'Mirage F 1', 'Mirage-F1EE': 'Mirage F 1',
        'Mirage-F1': 'Mirage F 1', 'Mirage-F1M': 'Mirage F 1',
        'Mirage 2000-5': 'Mirage 2000',
        'AJS37': 'Viggen', 'JA37': 'Viggen',
        'JAS39Gripen': 'Gripen', 'JAS39Gripen_AG': 'Gripen',
        'C-101CC': 'C 101', 'C-101EB': 'C 101',
        'L-39C': 'Albatross', 'L-39ZA': 'Albatross',
        'Hawk': 'Hawk trainer',
        'Alpha Jet': 'Alpha Jet',
        'Buccaneer S.2B': 'Buccaneer',
        # --- Chinese ---
        'J-11A': 'Flanker', 'J-10A': 'J 10',
        'J-16': 'J 16', 'JH-7A': 'J H 7 Flounder',
        'JF-17': 'Thunder', 'JF-17-AG': 'Thunder',
        'H-6J': 'H 6 Badger',
        'KJ-2000': 'K J 2000 AWACS',
        # --- Other ---
        'F-4E': 'Phantom', 'Mirage-F1': 'Mirage F 1',
        'WingLoong-I': 'Wing Loong drone',
        'Yak-52': 'Yak 52', 'Yak-130': 'Yak 130',
        'MB-339A': 'M B 339', 'MB-339APAN': 'M B 339',
        'T-45': 'Goshawk',
        # --- WW2 ---
        'SpitfireLFMkIX': 'Spitfire', 'SpitfireLFMkIXCW': 'Spitfire',
        'Bf-109K-4': 'Messerschmitt 109', 'Bf-109': 'Messerschmitt 109',
        'FW-190D9': 'Focke Wulf 190', 'FW-190A8': 'Focke Wulf 190',
        'P-51D': 'Mustang', 'P-51D-30-NA': 'Mustang',
        'P-51D-25-NA': 'Mustang',
        'P-47D-30': 'Thunderbolt', 'P-47D-30bl1': 'Thunderbolt',
        'P-47D-40': 'Thunderbolt',
        'TF-51D': 'Mustang trainer',
        'I-16': 'I 16 Rata',
        'A-20G': 'Havoc bomber',
        'B-17G': 'Flying Fortress',
        'Mosquito': 'Mosquito', 'MosquitoFBMkVI': 'Mosquito',
        'Ju-88A4': 'Junkers 88',
        'Me-262A': 'Messerschmitt 262',
    }
    for dcs_name, spoken in _aircraft.items():
        text = text.replace(dcs_name, spoken)

    # ── HELICOPTERS ───────────────────────────────────────────────
    _heli = {
        # US / NATO
        'AH-64D_BLK_II': 'Apache', 'AH-64D': 'Apache', 'AH-64A': 'Apache',
        'UH-60A': 'Blackhawk', 'UH-60L': 'Blackhawk',
        'CH-47D': 'Chinook', 'CH-53E': 'Super Stallion',
        'OH58D': 'Kiowa', 'SH-60B': 'Seahawk',
        'AH-1W': 'Super Cobra', 'UH-1H': 'Huey',
        'SA342M': 'Gazelle', 'SA342L': 'Gazelle',
        'SA342Minigun': 'Gazelle', 'SA342Mistral': 'Gazelle',
        'Bo-105': 'Bo 105',
        # Russian
        'Ka-50': 'Hokum', 'Ka-50_3': 'Hokum',
        'Ka-52': 'Alligator', 'Ka-27': 'Helix',
        'Mi-8MT': 'Hip', 'Mi-8MTV2': 'Hip',
        'Mi-24P': 'Hind', 'Mi-24V': 'Hind',
        'Mi-26': 'Halo', 'Mi-28N': 'Havoc',
        'Mi-6A': 'Hook',
    }
    for dcs_name, spoken in _heli.items():
        text = text.replace(dcs_name, spoken)

    # ── SAM SYSTEMS & GROUND THREATS ──────────────────────────────
    _ground = {
        # --- Russian / Soviet Long-range SAMs ---
        'S-300PS': 'S 300', 'S-300PMU1': 'S 300',
        'S-300PMU2': 'S 300', 'S-300PT': 'S 300',
        'S-300V': 'S 300 V', 'SA-10': 'S 300',
        'SA-12': 'S A 12 Gladiator',
        'SA-20': 'S 300 P M U',
        'SA-23': 'S A 23 Gladiator',
        'SA-5': 'S A 5 Gammon', 'S-200': 'S 200 Gammon',
        # --- Russian Medium-range SAMs ---
        'SA-11 Buk': 'S A 11 Buk', 'SA-11': 'S A 11 Buk',
        'Buk-M2': 'Buk M 2', 'SA-17': 'Buk M 2',
        'SA-6': 'S A 6 Gainful', 'Kub': 'Kub',
        '2S6 Tunguska': 'Tunguska', 'SA-19': 'Tunguska',
        'Tor': 'Tor M 1', 'SA-15': 'Tor M 1',
        'Osa': 'Osa', 'SA-8': 'Osa',
        # --- Russian Short-range SAMs ---
        'SA-2': 'S A 2 Guideline',
        'SA-3': 'S A 3 Goa',
        'SA-13 Strela-10': 'Strela 10', 'SA-13': 'Strela 10',
        'Strela-10M3': 'Strela 10',
        'Strela-1 9P31': 'Strela 1',
        'SA-9': 'Strela 1',
        'SA-18 Igla': 'Igla', 'SA-18': 'Igla',
        'SA-24 Igla-S': 'Igla S', 'SA-24': 'Igla S',
        'Igla manridge': 'Igla manpad',
        '9K33 Osa': 'Osa',
        # --- Russian Pantsir ---
        'Pantsir-S1': 'Pantsir',
        'SA-22': 'Pantsir',
        # --- Russian AAA ---
        'ZSU-23-4 Shilka': 'Shilka', 'ZSU-23-4': 'Shilka',
        'ZU-23': 'Zoo 23',
        'ZSU-57-2': 'Z S U 57',
        'S-60': 'S 60 anti air',
        'KS-19': 'K S 19 anti air',
        '2S38': 'Derivatsiya',
        # --- Western SAMs ---
        'Patriot': 'Patriot', 'Patriot ln': 'Patriot',
        'Patriot AMG': 'Patriot',
        'Hawk ln': 'Hawk', 'Hawk sr': 'Hawk radar',
        'Hawk pcp': 'Hawk', 'Hawk tr': 'Hawk radar',
        'Hawk cwar': 'Hawk',
        'NASAMS': 'NASAMS', 'NASAMS_LN_C': 'NASAMS',
        'NASAMS_LN_B': 'NASAMS',
        'Rapier': 'Rapier', 'rapier_fsa_launcher': 'Rapier',
        'Crotale': 'Crotale', 'HQ-7': 'Crotale',
        'Roland ADS': 'Roland', 'Roland Radar': 'Roland radar',
        'Gepard': 'Gepard',
        'Vulcan': 'Vulcan',
        'M6 Linebacker': 'Linebacker',
        'M1097 Avenger': 'Avenger',
        'Stinger manridge': 'Stinger manpad',
        'M48 Chaparral': 'Chaparral',
        'M163 Vulcan': 'Vulcan',
        'HEMTT_TFLAR': 'HEMTT anti air',
        # --- Naval SAMs ---
        'SM-2': 'Standard Missile', 'RIM-7': 'Sea Sparrow',
        'RIM-116': 'RAM', 'Phalanx': 'Phalanx CIWS',
        'Mk13': 'Standard Missile',
        'AK-630': 'A K 630 CIWS', 'Kashtan': 'Kashtan CIWS',
        '3M45 Granit': 'Granit', '3M-54 Klub': 'Klub',
        # --- Other ---
        'Flak18': 'Flak 18', 'Flak30': 'Flak 30',
        'Flak36': 'Flak 36', 'Flak37': 'Flak 37',
        'Flak38': 'Flak 38', 'Flakvierling38': 'Flak 38 quad',
        'bofors40': 'Bofors 40 mill', 'Bofors': 'Bofors',
        'Oerlikon': 'Oerlikon',
        'flak18': 'Flak 18',
    }
    for dcs_name, spoken in _ground.items():
        text = text.replace(dcs_name, spoken)

    # ── MISSILES (air-to-air) ─────────────────────────────────────
    _aam = {
        # US
        'AIM_120C': 'AMRAAM', 'AIM_120B': 'AMRAAM', 'AIM_120D': 'AMRAAM',
        'AIM-120C': 'AMRAAM', 'AIM-120B': 'AMRAAM', 'AIM-120': 'AMRAAM',
        'AIM_54A_Mk47': 'Phoenix', 'AIM_54A_Mk60': 'Phoenix',
        'AIM_54C_Mk47': 'Phoenix', 'AIM-54': 'Phoenix', 'AIM_54': 'Phoenix',
        'AIM_7M': 'Sparrow', 'AIM_7F': 'Sparrow', 'AIM_7MH': 'Sparrow',
        'AIM_7P': 'Sparrow', 'AIM-7': 'Sparrow',
        'AIM_9M': 'Sidewinder', 'AIM_9X': 'Sidewinder',
        'AIM_9L': 'Sidewinder', 'AIM_9P': 'Sidewinder',
        'AIM_9P5': 'Sidewinder', 'AIM-9': 'Sidewinder',
        # Russian
        'R-77': 'R 77 Adder', 'R-77-1': 'R 77',
        'R_77': 'R 77 Adder', 'R_77_1': 'R 77',
        'R-27ER': 'R 27 E R', 'R-27ET': 'R 27 heat',
        'R-27R': 'R 27', 'R-27T': 'R 27 heat',
        'R_27ER': 'R 27 E R', 'R_27ET': 'R 27 heat',
        'R_27R': 'R 27', 'R_27T': 'R 27 heat',
        'R-73': 'R 73 Archer', 'R_73': 'R 73 Archer',
        'R-60M': 'R 60', 'R_60M': 'R 60',
        'R-37M': 'R 37', 'R_37M': 'R 37',
        'R-33': 'R 33 Amos', 'R_33': 'R 33 Amos',
        'R-40R': 'R 40', 'R-40T': 'R 40 heat',
        # European
        'Meteor': 'Meteor',
        'MICA_IR': 'Meeka heat', 'MICA_EM': 'Meeka radar',
        'MICA': 'Meeka', 'MICA-IR': 'Meeka heat',
        'Matra R550': 'Magic', 'R550': 'Magic',
        'Matra Super 530D': 'Super 530', 'Super 530D': 'Super 530',
        'Super530D': 'Super 530',
        'ASRAAM': 'A S RAAM',
        'IRIS-T': 'Iris T',
        'AIM-132': 'A S RAAM',
        'Skyflash': 'Skyflash',
        # Chinese
        'SD-10': 'S D 10', 'SD_10': 'S D 10',
        'PL-5E': 'P L 5', 'PL-5': 'P L 5',
        'PL_5EII': 'P L 5', 'PL-12': 'P L 12',
        'PL-15': 'P L 15',
        # Israeli / other
        'Derby': 'Derby', 'Python-5': 'Python 5',
        'Python-4': 'Python 4',
    }
    for dcs_name, spoken in _aam.items():
        text = text.replace(dcs_name, spoken)

    # ── MISSILES (air-to-ground, cruise, anti-ship) ───────────────
    _agm = {
        # US AGM
        'AGM-65D': 'Maverick', 'AGM-65E': 'Maverick',
        'AGM-65F': 'Maverick', 'AGM-65G': 'Maverick',
        'AGM-65H': 'Maverick', 'AGM-65K': 'Maverick',
        'AGM-65L': 'Maverick', 'AGM_65': 'Maverick',
        'AGM-88C': 'HARM', 'AGM-88': 'HARM', 'AGM_88': 'HARM',
        'AGM-84A': 'Harpoon', 'AGM-84D': 'Harpoon',
        'AGM-84E': 'SLAM', 'AGM-84H': 'SLAM ER',
        'AGM_84': 'Harpoon',
        'AGM-154A': 'J SOW', 'AGM-154C': 'J SOW',
        'AGM_154': 'J SOW',
        'AGM-62': 'Walleye',
        'SLAM-ER': 'SLAM E R',
        'AGM-114K': 'Hellfire',
        'BGM-71': 'TOW',
        'JSOW': 'J SOW', 'JDAM': 'J DAM', 'JASSM': 'J A S M',
        # Russian AGM
        'Kh-29T': 'K H 29', 'Kh-29L': 'K H 29',
        'Kh_29T': 'K H 29', 'Kh_29L': 'K H 29',
        'Kh-31A': 'K H 31 anti ship', 'Kh-31P': 'K H 31 anti radar',
        'Kh_31A': 'K H 31 anti ship', 'Kh_31P': 'K H 31 anti radar',
        'Kh-58U': 'K H 58 anti radar', 'Kh_58U': 'K H 58 anti radar',
        'Kh-25ML': 'K H 25', 'Kh-25MPU': 'K H 25',
        'Kh_25ML': 'K H 25', 'Kh_25MPU': 'K H 25',
        'Kh-65': 'K H 65 cruise missile', 'Kh-55': 'K H 55 cruise missile',
        'Kh-59M': 'K H 59', 'Kh_59M': 'K H 59',
        'Kh-35': 'K H 35 anti ship', 'Kh_35': 'K H 35 anti ship',
        'Kh-41': 'Sunburn',
        'Kh-22': 'K H 22 Kitchen',
        '3M-54': 'Kalibr', '3M54': 'Kalibr',
        '3M-45': 'Granit', 'P-270': 'Moskit',
        'P-800': 'Oniks',
        # Vikhr (Ka-50)
        '9M127-1 Vikhr M': 'Vikhr', '9M120 Ataka': 'Ataka',
        'Vikhr': 'Vikhr', 'Ataka': 'Ataka',
        '9K114 Shturm': 'Shturm',
        # European AGM
        'Exocet': 'Exocet',
        'AS-30L': 'A S 30 laser',
        'HOT-3': 'HOT missile',
        'Brimstone': 'Brimstone',
        'Storm Shadow': 'Storm Shadow',
        'SCALP': 'Scalp',
        'Mistral': 'Mistral',
        'Sea Eagle': 'Sea Eagle',
    }
    for dcs_name, spoken in _agm.items():
        text = text.replace(dcs_name, spoken)

    # ── SAM MISSILES (surface-to-air missile names) ───────────────
    _sam_missiles = {
        '5V55': 'S 300 missile', '48N6': 'S 300 missile',
        '48N6E2': 'S 300 missile',
        '9M38': 'Buk missile', '9M317': 'Buk missile',
        '9M311': 'Tunguska missile', '57E6': 'Pantsir missile',
        '9M330': 'Tor missile', '9M331': 'Tor missile',
        '9M33': 'Osa missile',
        '9M311-1': 'Tunguska missile',
        '53T6': 'Gazelle interceptor',
        'V-601P': 'S A 2 missile',
        'V-759': 'S A 3 missile',
        '3M9': 'S A 6 missile',
        '5V27': 'S A 5 missile',
        '9M335': 'Tor missile',
        'MIM-104': 'Patriot missile',
        'MIM-23': 'Hawk missile',
        'FIM-92': 'Stinger',
        '9K38 Igla': 'Igla',
    }
    for dcs_name, spoken in _sam_missiles.items():
        text = text.replace(dcs_name, spoken)

    # ── BOMBS & GUIDED MUNITIONS ──────────────────────────────────
    _bombs = {
        'GBU-10': 'G B U 10 Paveway', 'GBU-12': 'G B U 12 Paveway',
        'GBU-16': 'G B U 16', 'GBU-24': 'G B U 24',
        'GBU-31': 'J DAM', 'GBU-38': 'J DAM',
        'GBU-32': 'J DAM', 'GBU-54': 'Laser J DAM',
        'GBU-27': 'Bunker buster',
        'CBU-87': 'Cluster bomb', 'CBU-97': 'Cluster bomb',
        'CBU-103': 'Wind corrected cluster', 'CBU-105': 'Sensor fuzed weapon',
        'Mk-82': 'Mark 82', 'Mk-83': 'Mark 83', 'Mk-84': 'Mark 84',
        'Mk-20': 'Rockeye',
        'FAB-100': 'Fab 100', 'FAB-250': 'Fab 250',
        'FAB-500': 'Fab 500', 'FAB-1500': 'Fab 1500',
        'KAB-500Kr': 'K A B 500 guided',
        'KAB-500L': 'K A B 500 laser',
        'KAB-1500': 'K A B 1500',
        'KMGU-2': 'K M G U cluster',
        'BetAB-500': 'Penetration bomb',
        'RBK-250': 'Cluster bomb', 'RBK-500': 'Cluster bomb',
        'OFAB-250': 'O Fab 250',
    }
    for dcs_name, spoken in _bombs.items():
        text = text.replace(dcs_name, spoken)

    # ── ROCKETS ───────────────────────────────────────────────────
    _rockets = {
        'S-8KOM': 'S 8 rockets', 'S-8OFP2': 'S 8 rockets',
        'S-13OF': 'S 13 rockets', 'S-5K': 'S 5 rockets',
        'S-24B': 'S 24 rocket', 'S-25OFM': 'S 25 rocket',
        'B-8M1': 'B 8 rocket pod', 'B-8V20A': 'B 8 rocket pod',
        'B-13L': 'B 13 rocket pod',
        'UB-32A-24': 'U B 32 pod',
        'HYDRA-70 M151': 'Hydra rockets', 'LAU-61': 'Hydra rockets',
        'LAU-68': 'Hydra rockets', 'LAU-10': 'Zuni rockets',
        'Zuni': 'Zuni rockets',
        'SNEB': 'Sneb rockets',
    }
    for dcs_name, spoken in _rockets.items():
        text = text.replace(dcs_name, spoken)

    # ── SHIPS (common hostile vessels) ────────────────────────────
    _ships = {
        'KUZNECOW': 'Kuznetsov carrier',
        'CV_1143_5': 'Kuznetsov carrier',
        'VINSON': 'Carl Vinson carrier',
        'Stennis': 'Stennis carrier',
        'CVN_71': 'Roosevelt carrier',
        'CVN_72': 'Lincoln carrier',
        'CVN_73': 'Washington carrier',
        'CVN_74': 'Stennis carrier',
        'CVN_75': 'Truman carrier',
        'LHA_Tarawa': 'Tarawa',
        'MOSCOW': 'Moskva cruiser',
        'PERRY': 'Perry class frigate',
        'TICONDEROG': 'Ticonderoga cruiser',
        'ALBATROS': 'Grisha corvette',
        'MOLNIYA': 'Molniya corvette',
        'NEUSTRASH': 'Neustrashimy frigate',
        'REZKY': 'Krivak frigate',
        'Type_052B': 'Chinese destroyer',
        'Type_052C': 'Chinese destroyer',
        'Type_054A': 'Chinese frigate',
    }
    for dcs_name, spoken in _ships.items():
        text = text.replace(dcs_name, spoken)

    # ── GROUND VEHICLES (armor, etc.) ─────────────────────────────
    _vehicles = {
        'T-72B': 'T 72 tank', 'T-72B3': 'T 72 tank',
        'T-80UD': 'T 80 tank', 'T-90': 'T 90 tank',
        'T-55': 'T 55 tank',
        'M-1 Abrams': 'Abrams', 'M1A2': 'Abrams',
        'Leopard-2': 'Leopard 2', 'Leopard1A3': 'Leopard 1',
        'Challenger2': 'Challenger 2',
        'Leclerc': 'Leclerc',
        'Merkava_Mk4': 'Merkava',
        'BMP-1': 'B M P 1', 'BMP-2': 'B M P 2', 'BMP-3': 'B M P 3',
        'BTR-80': 'B T R 80', 'BTR-82A': 'B T R 82',
        'BRDM-2': 'B R D M',
        'BMD-1': 'B M D',
        'M-2 Bradley': 'Bradley', 'LAV-25': 'L A V 25',
        'M1126 Stryker': 'Stryker', 'AAV7': 'A A V 7',
        'Marder': 'Marder', 'Warrior': 'Warrior',
    }
    for dcs_name, spoken in _vehicles.items():
        text = text.replace(dcs_name, spoken)

    # Expand remaining dash-separated alphanumerics (e.g. "F-16C" -> "F 16 C")
    text = re.sub(r'([A-Za-z])-([0-9])', r'\1 \2', text)
    text = re.sub(r'([0-9])-([A-Za-z])', r'\1 \2', text)

    # Expand underscores to spaces
    text = text.replace('_', ' ')

    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# --- TTS Enumeration ---
def enumerate_tts_options():
    """Return (voices, devices) as lists of (token_id, display_name)."""
    voices, devices = [], []
    if not TTS_AVAILABLE:
        return voices, devices
    try:
        sp = comtypes.client.CreateObject("SAPI.SpVoice")
        for i in range(sp.GetVoices().Count):
            v = sp.GetVoices().Item(i)
            voices.append((v.Id, v.GetDescription()))
        for i in range(sp.GetAudioOutputs().Count):
            d = sp.GetAudioOutputs().Item(i)
            devices.append((d.Id, d.GetDescription()))
        del sp
    except Exception:
        pass
    return voices, devices


# --- Radio Filter ---
def _apply_radio_filter(wav_path, static_vol=40, crackle_vol=30):
    """Apply military radio effect: bandpass 300-3400 Hz, static, crackle, soft clip."""
    import wave
    import struct
    import random

    with wave.open(wav_path, 'rb') as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth != 2:
        return  # only handle 16-bit PCM

    n_samples = len(raw) // 2
    samples = list(struct.unpack(f'<{n_samples}h', raw))

    # Mix to mono if stereo
    if n_channels == 2:
        mono = []
        for i in range(0, len(samples), 2):
            mono.append((samples[i] + samples[i + 1]) // 2)
        samples = mono
        n_channels = 1

    dt = 1.0 / framerate

    # High-pass filter ~300 Hz (single-pole IIR)
    import math
    rc_hp = 1.0 / (2.0 * math.pi * 300.0)
    alpha_hp = rc_hp / (rc_hp + dt)
    hp_out = [0.0] * len(samples)
    hp_out[0] = float(samples[0])
    for i in range(1, len(samples)):
        hp_out[i] = alpha_hp * (hp_out[i - 1] + samples[i] - samples[i - 1])

    # Low-pass filter ~3400 Hz (single-pole IIR)
    rc_lp = 1.0 / (2.0 * math.pi * 3400.0)
    alpha_lp = dt / (rc_lp + dt)
    lp_out = [0.0] * len(hp_out)
    lp_out[0] = hp_out[0]
    for i in range(1, len(hp_out)):
        lp_out[i] = lp_out[i - 1] + alpha_lp * (hp_out[i] - lp_out[i - 1])

    # Second pass of each filter for steeper rolloff
    hp2 = [0.0] * len(lp_out)
    hp2[0] = lp_out[0]
    for i in range(1, len(lp_out)):
        hp2[i] = alpha_hp * (hp2[i - 1] + lp_out[i] - lp_out[i - 1])

    lp2 = [0.0] * len(hp2)
    lp2[0] = hp2[0]
    for i in range(1, len(hp2)):
        lp2[i] = lp2[i - 1] + alpha_lp * (hp2[i] - lp2[i - 1])

    filtered = lp2

    # Attenuate filtered signal (radio sounds thinner)
    for i in range(len(filtered)):
        filtered[i] *= 0.75

    # Add continuous static/noise (scaled by static_vol 0-100)
    if static_vol > 0:
        noise_level = max(1, int(300 * static_vol / 100.0))
        for i in range(len(filtered)):
            filtered[i] += random.randint(-noise_level, noise_level)

    # Add radio crackle pops (scaled by crackle_vol 0-100)
    if crackle_vol > 0:
        density = max(1, len(filtered) // 1200)
        num_crackles = max(1, int(density * crackle_vol / 100.0))
        amp_base = int(800 * crackle_vol / 100.0)
        amp_peak = int(2000 * crackle_vol / 100.0)
        for _ in range(num_crackles):
            pos = random.randint(0, len(filtered) - 1)
            burst_len = random.randint(1, 4)
            for j in range(burst_len):
                if pos + j < len(filtered):
                    filtered[pos + j] += random.choice([-1, 1]) * random.randint(amp_base, max(amp_base + 1, amp_peak))

    # Soft clipping (tanh-style compression)
    clip_threshold = 24000.0
    result = []
    for s in filtered:
        s = s * 1.15  # mild gain recovery
        if abs(s) > clip_threshold:
            sign = 1 if s > 0 else -1
            s = sign * (clip_threshold + (32767 - clip_threshold) *
                        math.tanh((abs(s) - clip_threshold) / 8000.0))
        result.append(max(-32767, min(32767, int(s))))

    out_raw = struct.pack(f'<{len(result)}h', *result)

    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(out_raw)


# --- TTS Manager ---
class TTSManager:
    def __init__(self):
        self.available = TTS_AVAILABLE
        self.enabled = TTS_AVAILABLE
        self._queue = queue.Queue()
        self._running = False
        self._thread = None
        self.voice_id = ""
        self.device_id = ""
        self.rate = 0  # SAPI5 rate: -10 to 10
        self.volume = 100  # SAPI5 volume: 0-100
        self.radio_filter = False
        self.radio_static_vol = 40
        self.radio_crackle_vol = 30

    def start(self):
        if not self.available:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._queue.put(None)

    def speak(self, text):
        if self.enabled and self._running:
            self._queue.put(("speak", text))

    def configure(self, voice_id=None, device_id=None, rate=None, volume=None):
        if self._running:
            self._queue.put(("config", (voice_id, device_id, rate, volume)))

    def _worker(self):
        try:
            comtypes.CoInitialize()
            sp = comtypes.client.CreateObject("SAPI.SpVoice")
            sp.Rate = self.rate
            sp.Volume = self.volume
            self._apply_voice(sp, self.voice_id)
            self._apply_device(sp, self.device_id)
            # Keep reference to original audio output for radio filter
            original_output = sp.AudioOutput
        except Exception as e:
            print(f"TTS init error: {e}")
            self.available = False
            return

        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
                if item is None:
                    break
                cmd, data = item
                if cmd == "speak":
                    if self.radio_filter:
                        self._speak_radio(sp, data, original_output,
                                          self.radio_static_vol, self.radio_crackle_vol)
                    else:
                        sp.Speak(data, 0)
                elif cmd == "config":
                    vid, did, r, vol = data
                    if vid is not None:
                        self._apply_voice(sp, vid)
                    if did is not None:
                        self._apply_device(sp, did)
                        original_output = sp.AudioOutput
                    if r is not None:
                        sp.Rate = r
                    if vol is not None:
                        sp.Volume = vol
            except queue.Empty:
                continue
            except Exception:
                pass

        try:
            del sp
            comtypes.CoUninitialize()
        except Exception:
            pass

    @staticmethod
    def _apply_voice(sp, voice_id):
        if not voice_id:
            return
        try:
            voices = sp.GetVoices()
            for i in range(voices.Count):
                if voices.Item(i).Id == voice_id:
                    sp.Voice = voices.Item(i)
                    break
        except Exception:
            pass

    @staticmethod
    def _apply_device(sp, device_id):
        if not device_id:
            return
        try:
            outputs = sp.GetAudioOutputs()
            for i in range(outputs.Count):
                if outputs.Item(i).Id == device_id:
                    sp.AudioOutput = outputs.Item(i)
                    break
        except Exception:
            pass

    @staticmethod
    def _speak_radio(sp, text, original_output, static_vol=40, crackle_vol=30):
        """Render TTS to WAV, apply radio filter, play result."""
        import tempfile
        import winsound
        tmp = os.path.join(tempfile.gettempdir(), "autogci_radio.wav")
        try:
            # Render speech to WAV file
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            stream.Open(tmp, 3, False)  # SSFMCreateForWrite = 3
            sp.AudioOutputStream = stream
            sp.Speak(text, 0)
            stream.Close()
            # Restore normal output
            sp.AudioOutput = original_output

            # Apply radio effect
            _apply_radio_filter(tmp, static_vol=static_vol, crackle_vol=crackle_vol)

            # Play the processed audio
            winsound.PlaySound(tmp, winsound.SND_FILENAME)
        except Exception:
            # Fallback to normal speech
            try:
                sp.AudioOutput = original_output
                sp.Speak(text, 0)
            except Exception:
                pass
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass


# --- UDP Receiver ---
class UDPReceiver:
    def __init__(self, host, port, callback):
        self.callback = callback
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.settimeout(1.0)
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass

    def _listen(self):
        while self._running:
            try:
                data, _ = self.sock.recvfrom(8192)
                msg = data.decode('utf-8', errors='replace')
                self.callback(msg)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                pass


# --- Main Application ---
class ThreatWarnerApp:
    def __init__(self):
        self.player = PlayerState()
        self.threats: Dict[str, Threat] = {}
        self.connected = False
        self.last_data_time = 0.0

        # Pending new-threat announcements for formation grouping
        self._pending_new: list = []          # [(Threat, dist_nm, angels), ...]
        self._pending_timer: str | None = None
        self._GROUP_DELAY_MS = 400           # wait this long to batch a formation

        # Load saved settings
        self.settings = load_settings()
        self.tts_enabled = self.settings["tts_enabled"]

        # Thread-safe queue for log messages -> GUI
        self.log_queue: queue.Queue = queue.Queue()

        # TTS — enumerate voices & devices, then start
        self._voices, self._devices = enumerate_tts_options()
        self._voice_map = {name: vid for vid, name in self._voices}
        self._device_map = {name: did for did, name in self._devices}
        self._voice_names = [name for _, name in self._voices]
        self._device_names = [name for _, name in self._devices]

        self.tts = TTSManager()
        self.tts.voice_id = self.settings.get("tts_voice", "")
        self.tts.device_id = self.settings.get("tts_device", "")
        self.tts.rate = max(-10, min(10, round((self.settings["tts_rate"] - 180) / 20)))
        self.tts.volume = self.settings.get("tts_volume", 100)
        self.tts.radio_filter = self.settings.get("radio_filter", False)
        self.tts.radio_static_vol = self.settings.get("radio_static_vol", 40)
        self.tts.radio_crackle_vol = self.settings.get("radio_crackle_vol", 30)
        self.tts.start()

        # ── Root window ──
        self.root = tk.Tk()
        self.root.title("DCS Auto-GCI")
        self.root.geometry("1120x700")
        self.root.minsize(800, 500)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Make the root fully resizable
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_gui()

        # Start UDP
        self.receiver = UDPReceiver(UDP_HOST, UDP_PORT, self._on_message)
        self.receiver.start()
        self._tick()

    # ══════════════════════════════════════════════════════════════════
    #  GUI Construction — grid-based, fully resizable
    # ══════════════════════════════════════════════════════════════════

    def _build_gui(self):
        style = ttk.Style()
        style.theme_use('clam')

        # ── Remove ugly borders from all ttk widgets ──
        style.configure('Treeview', background=BG2, foreground=FG,
                        fieldbackground=BG2, font=(FONT_MONO, 10), rowheight=26,
                        borderwidth=0, relief=tk.FLAT)
        style.configure('Treeview.Heading', background=BG3, foreground=HEADER,
                        font=(FONT_UI, 10, 'bold'), borderwidth=0, relief=tk.FLAT)
        style.map('Treeview', background=[('selected', '#1f6feb')])
        style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nsew'})])

        style.configure('TFrame', background=BG)
        style.configure('TPanedwindow', background=BG3)

        style.configure('TCombobox', font=(FONT_UI, 9),
                        borderwidth=0, relief=tk.FLAT,
                        background=BG3, foreground=FG,
                        arrowcolor=FG, padding=3)
        style.map('TCombobox',
                  fieldbackground=[('readonly', BG2)],
                  foreground=[('readonly', FG)],
                  background=[('readonly', BG3)],
                  bordercolor=[('focus', BG3), ('!focus', BG3)],
                  lightcolor=[('focus', BG3), ('!focus', BG3)],
                  darkcolor=[('focus', BG3), ('!focus', BG3)],
                  arrowcolor=[('readonly', FG)])

        style.configure('Vertical.TScrollbar', background=BG3,
                        troughcolor=BG2, borderwidth=0, relief=tk.FLAT,
                        arrowcolor=BG3)
        style.map('Vertical.TScrollbar',
                  background=[('active', DIM), ('!active', BG3)])

        # Notebook tab borders
        style.configure('TNotebook', borderwidth=0)
        style.configure('TNotebook.Tab', borderwidth=0)

        # ── Outer container (grid row 0 of root) ──
        outer = tk.Frame(self.root, bg=BG)
        outer.grid(row=0, column=0, sticky='nsew')
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # ── Row 0: Top bar ──
        top = tk.Frame(outer, bg=BG)
        top.grid(row=0, column=0, sticky='ew', padx=14, pady=(10, 0))

        tk.Label(top, text="DCS AUTO-GCI", bg=BG, fg=ACCENT,
                 font=(FONT_UI, 16, 'bold')).pack(side=tk.LEFT)
        tk.Label(top, text=f"v{APP_VERSION}", bg=BG, fg=SUBTLE,
                 font=(FONT_UI, 9)).pack(side=tk.LEFT, padx=(8, 0))

        self.status_lbl = tk.Label(top, text="\u25cf  WAITING FOR DCS",
                                   bg=BG, fg=ORANGE, font=(FONT_UI, 10))
        self.status_lbl.pack(side=tk.RIGHT)

        self.player_lbl = tk.Label(top, text="", bg=BG, fg=FG,
                                   font=(FONT_UI, 9))
        self.player_lbl.pack(side=tk.RIGHT, padx=(0, 20))

        # Separator under top bar
        tk.Frame(outer, bg=BG3, height=1).grid(row=0, column=0, sticky='ew',
                                                padx=14, pady=(38, 0))

        # ── Row 1: Tabbed notebook ──
        style.configure('Dark.TNotebook', background=BG, borderwidth=0)
        style.configure('Dark.TNotebook.Tab', background=BG3, foreground=SUBTLE,
                        font=(FONT_UI, 10, 'bold'), padding=[16, 5],
                        borderwidth=0)
        style.map('Dark.TNotebook.Tab',
                  background=[('selected', BG2)],
                  foreground=[('selected', ACCENT)])
        style.layout('Dark.TNotebook', [('Dark.TNotebook.client',
                     {'sticky': 'nsew', 'border': 0})])

        self.notebook = ttk.Notebook(outer, style='Dark.TNotebook')
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=14, pady=(6, 10))

        # ── Tab 1: Monitor (threats + log) ──
        monitor_tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(monitor_tab, text='  \U0001F4E1 Monitor  ')
        monitor_tab.rowconfigure(0, weight=0)  # buttons
        monitor_tab.rowconfigure(1, weight=3)  # threat tree
        monitor_tab.rowconfigure(2, weight=2)  # log
        monitor_tab.columnconfigure(0, weight=1)

        # Button bar
        btn_bar = tk.Frame(monitor_tab, bg=BG)
        btn_bar.grid(row=0, column=0, sticky='ew', pady=(6, 4), padx=8)
        tk.Label(btn_bar, text="ACTIVE THREATS", bg=BG, fg=RED,
                 font=(FONT_UI, 12, 'bold')).pack(side=tk.LEFT)
        tk.Button(btn_bar, text="Clear Log", command=self._clear_log,
                  bg=BG3, fg=SUBTLE, font=(FONT_UI, 9), relief=tk.FLAT,
                  activebackground='#30363d', cursor='hand2',
                  padx=10, pady=2).pack(side=tk.RIGHT, padx=2)

        # Threat table
        tree_frame = tk.Frame(monitor_tab, bg=BG)
        tree_frame.grid(row=1, column=0, sticky='nsew', padx=8)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        cols = ('clock', 'type', 'name', 'distance', 'altitude', 'bearing')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        for cid, hdr, w in [
            ('clock', 'Clock', 80), ('type', 'Type', 70),
            ('name', 'Name', 200), ('distance', 'Dist (nm)', 85),
            ('altitude', 'Altitude', 95), ('bearing', 'Bearing\u00b0', 75)
        ]:
            self.tree.heading(cid, text=hdr)
            self.tree.column(cid, width=w, minwidth=50,
                             anchor=tk.CENTER if cid != 'name' else tk.W)

        tree_sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_sb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        tree_sb.grid(row=0, column=1, sticky='ns')

        # Event log
        log_frame = tk.Frame(monitor_tab, bg=BG)
        log_frame.grid(row=2, column=0, sticky='nsew', pady=(8, 6), padx=8)
        log_frame.rowconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)

        tk.Label(log_frame, text="EVENT LOG", bg=BG, fg=ACCENT,
                 font=(FONT_UI, 12, 'bold')).grid(row=0, column=0,
                                                    columnspan=2, sticky='w',
                                                    pady=(0, 4))

        self.log_txt = tk.Text(log_frame, bg=BG2, fg=SUBTLE,
                               font=(FONT_MONO, 9), wrap=tk.WORD,
                               state=tk.DISABLED, insertbackground=FG,
                               selectbackground='#1f6feb',
                               padx=8, pady=6,
                               borderwidth=0, relief=tk.FLAT,
                               highlightbackground=BG3, highlightthickness=1)
        log_sb = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=log_sb.set)
        self.log_txt.grid(row=1, column=0, sticky='nsew')
        log_sb.grid(row=1, column=1, sticky='ns')

        for tag, color in [('weapon', RED), ('air', ORANGE), ('ground', YELLOW),
                           ('info', ACCENT), ('gone', DIM), ('event', LIGHT)]:
            self.log_txt.tag_configure(tag, foreground=color)

        # ── Tab 2: Settings ──
        self._build_settings_panel(self.notebook)

    # ── Settings Panel (right side, always visible) ───────────────────

    def _build_settings_panel(self, parent):
        # Settings tab frame
        settings_tab = tk.Frame(parent, bg=BG2)
        parent.add(settings_tab, text='  \u2699 Settings  ')
        settings_tab.rowconfigure(0, weight=1)
        settings_tab.columnconfigure(0, weight=1)

        # Canvas + scrollbar for settings content
        canvas = tk.Canvas(settings_tab, bg=BG2, highlightthickness=0)
        csb = ttk.Scrollbar(settings_tab, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=csb.set)
        canvas.grid(row=0, column=0, sticky='nsew')
        csb.grid(row=0, column=1, sticky='ns')

        sf = tk.Frame(canvas, bg=BG2)
        canvas.create_window((0, 0), window=sf, anchor='nw')
        sf.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        # Mouse-wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all('<MouseWheel>', _on_mousewheel, add='+')

        # Two-column layout
        sf.columnconfigure(0, weight=1)
        sf.columnconfigure(1, weight=1)

        left_col = tk.Frame(sf, bg=BG2)
        left_col.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        right_col = tk.Frame(sf, bg=BG2)
        right_col.grid(row=0, column=1, sticky='nsew', padx=(10, 0))

        PAD = 8

        # ══ LEFT COLUMN ══

        # ── Theme Selector ──
        self._settings_section(left_col, "THEME")
        current_theme = self.settings.get("theme", "Stealth Dark")
        self.theme_var, self._theme_cb = self._settings_dropdown(
            left_col, "Style:", THEME_NAMES, current_theme)
        self._theme_cb.bind('<<ComboboxSelected>>', self._on_theme_change)

        # ── Detection Range ──
        self._settings_section(left_col, "DETECTION RANGE (nm)")
        self.missile_range = self._settings_slider(left_col, "Missiles:", 1, 150,
                                                    self.settings["missile_range_nm"])
        self.air_range = self._settings_slider(left_col, "Aircraft:", 1, 150,
                                                self.settings["air_range_nm"])
        self.ground_range = self._settings_slider(left_col, "Ground:", 1, 150,
                                                   self.settings["ground_range_nm"])

        # ── Threat Filters ──
        self._settings_section(left_col, "THREAT FILTERS")
        self.track_missiles = self._settings_check(left_col, "Missiles / Weapons",
                                                    self.settings["track_missiles"])
        self.track_air = self._settings_check(left_col, "Enemy Aircraft",
                                               self.settings["track_air"])
        self.track_ground = self._settings_check(left_col, "Ground (SAM/AAA)",
                                                  self.settings["track_ground"])

        # ── Timeouts ──
        self._settings_section(left_col, "TIMEOUTS (seconds)")
        self.threat_timeout = self._settings_slider(left_col, "Threats:", 3, 60,
                                                     self.settings["threat_timeout"])
        self.weapon_timeout = self._settings_slider(left_col, "Weapons:", 5, 120,
                                                     self.settings["weapon_timeout"])

        # ── Buttons ──
        btn_frame = tk.Frame(left_col, bg=BG2)
        btn_frame.pack(fill=tk.X, padx=PAD, pady=(16, 8))
        tk.Button(btn_frame, text="Apply & Save", command=self._save_settings,
                  bg='#238636', fg='white', font=(FONT_UI, 9, 'bold'),
                  relief=tk.FLAT, activebackground='#2ea043',
                  cursor='hand2', padx=12, pady=3,
                  width=14).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Reset", command=self._reset_settings,
                  bg=BG3, fg=ORANGE, font=(FONT_UI, 9),
                  relief=tk.FLAT, activebackground='#30363d',
                  cursor='hand2', padx=12, pady=3,
                  width=8).pack(side=tk.RIGHT, padx=2)

        # ── Update check ──
        update_frame = tk.Frame(left_col, bg=BG2)
        update_frame.pack(fill=tk.X, padx=PAD, pady=(4, 8))
        self._update_btn = tk.Button(
            update_frame, text="\U0001F504 Check for Updates",
            command=self._check_for_updates,
            bg='#1f6feb', fg='white', font=(FONT_UI, 9),
            relief=tk.FLAT, activebackground='#388bfd',
            cursor='hand2', padx=10, pady=3,
            width=20)
        self._update_btn.pack(side=tk.LEFT, padx=2)
        self._update_status = tk.Label(update_frame, text="", bg=BG2, fg=FG,
                                        font=(FONT_UI, 8))
        self._update_status.pack(side=tk.LEFT, padx=(8, 0))

        # ══ RIGHT COLUMN ══

        # ── TTS ──
        self._settings_section(right_col, "TEXT-TO-SPEECH")
        self.tts_var = self._settings_check(right_col, "TTS Enabled",
                                             self.settings["tts_enabled"])
        self.announce_missiles = self._settings_check(right_col, "  Announce Missiles",
                                                       self.settings["announce_missiles"])
        self.announce_air = self._settings_check(right_col, "  Announce Aircraft",
                                                  self.settings["announce_air"])
        self.announce_ground = self._settings_check(right_col, "  Announce Ground",
                                                     self.settings["announce_ground"])
        self.announce_events = self._settings_check(right_col, "  Announce Events",
                                                     self.settings["announce_events"])
        self.tts_rate = self._settings_slider(right_col, "Speech Rate:", 80, 300,
                                               self.settings["tts_rate"])
        self.tts_volume = self._settings_slider(right_col, "Volume:", 0, 100,
                                                self.settings.get("tts_volume", 100))
        self.radio_filter_var = self._settings_check(right_col, "\U0001F4FB Radio Filter",
                                                      self.settings.get("radio_filter", False))
        self.radio_static_vol_var = self._settings_slider(right_col, "  Static:", 0, 100,
                                                          self.settings.get("radio_static_vol", 40))
        self.radio_crackle_vol_var = self._settings_slider(right_col, "  Crackle:", 0, 100,
                                                           self.settings.get("radio_crackle_vol", 30))

        # Voice and audio output device
        voice_display = self._id_to_display(self.settings.get("tts_voice", ""), self._voices)
        self.tts_voice_var, self._voice_cb = self._settings_dropdown(right_col, "Voice:",
            self._voice_names, voice_display)
        device_display = self._id_to_display(self.settings.get("tts_device", ""), self._devices)
        self.tts_device_var, self._device_cb = self._settings_dropdown(right_col, "Audio Out:",
            self._device_names, device_display)

        # TTS action buttons
        btn_row = tk.Frame(right_col, bg=BG2)
        btn_row.pack(fill=tk.X, padx=10, pady=(8, 0))
        tk.Button(btn_row, text="Test TTS", command=self._test_tts,
                  bg=ACCENT, fg='white', font=(FONT_UI, 9),
                  relief=tk.FLAT, activebackground='#388bfd',
                  cursor='hand2', padx=12, pady=3,
                  width=14).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="\u26a1 Unlock OneCore Voices",
                  command=self._unlock_onecore_voices,
                  bg='#238636', fg='white', font=(FONT_UI, 9),
                  relief=tk.FLAT, activebackground='#2ea043',
                  cursor='hand2', padx=10, pady=3,
                  width=22).pack(side=tk.LEFT)

    # ── Settings widget helpers ───────────────────────────────────────

    def _settings_section(self, parent, title):
        tk.Label(parent, text=title, bg=BG2, fg=HEADER,
                 font=(FONT_UI, 10, 'bold')).pack(anchor='w', padx=10, pady=(14, 0))
        tk.Frame(parent, bg=BG3, height=1).pack(fill=tk.X, padx=10, pady=(3, 6))

    def _settings_slider(self, parent, label, from_, to, value):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row, text=label, bg=BG2, fg=FG, font=(FONT_UI, 9),
                 width=13, anchor='w').pack(side=tk.LEFT)
        var = tk.IntVar(value=int(value))
        # Wrap scale in a frame so DIM bg only applies to the scale itself
        sc_frame = tk.Frame(row, bg=BG2)
        sc_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sc = tk.Scale(sc_frame, from_=from_, to=to, orient=tk.HORIZONTAL,
                      variable=var, bg=DIM, fg=FG, troughcolor=BG3,
                      highlightthickness=0, font=(FONT_UI, 8),
                      length=160, sliderrelief=tk.FLAT,
                      activebackground=ACCENT, borderwidth=0,
                      showvalue=True)
        sc.pack(fill=tk.X, expand=True)
        return var

    def _settings_check(self, parent, label, value):
        var = tk.BooleanVar(value=value)
        tk.Checkbutton(parent, text=label, variable=var, bg=BG2, fg=FG,
                       selectcolor=BG3, activebackground=BG2,
                       activeforeground=FG, font=(FONT_UI, 9),
                       cursor='hand2', highlightthickness=0,
                       borderwidth=0, relief=tk.FLAT
                       ).pack(anchor='w', padx=10, pady=2)
        return var

    def _settings_dropdown(self, parent, label, choices, current):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row, text=label, bg=BG2, fg=FG, font=(FONT_UI, 9),
                 width=13, anchor='w').pack(side=tk.LEFT)
        var = tk.StringVar(value=current)
        cb = ttk.Combobox(row, textvariable=var, values=choices,
                          state='readonly', font=(FONT_UI, 9), width=24)
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return var, cb

    def _id_to_display(self, token_id, options):
        for vid, name in options:
            if vid == token_id:
                return name
        return options[0][1] if options else ""

    # ── Settings actions ──────────────────────────────────────────────

    def _on_theme_change(self, event=None):
        """Switch theme and rebuild the entire GUI."""
        name = self.theme_var.get()
        # Gather current settings before rebuild so we don't lose them
        self.settings = self._gather_settings()
        self.settings["theme"] = name
        save_settings(self.settings)
        _apply_theme(name)
        # Destroy all widgets inside root and rebuild
        for w in self.root.winfo_children():
            w.destroy()
        self.root.configure(bg=BG)
        self._build_gui()
        # Re-populate widget vars from saved settings
        self._restore_settings_widgets()
        self._queue_log(f"Theme changed to {name}.", 'info')

    def _restore_settings_widgets(self):
        """Restore settings widget values from self.settings after a GUI rebuild."""
        s = self.settings
        self.theme_var.set(s.get("theme", "Stealth Dark"))
        self.missile_range.set(s["missile_range_nm"])
        self.air_range.set(s["air_range_nm"])
        self.ground_range.set(s["ground_range_nm"])
        self.track_missiles.set(s["track_missiles"])
        self.track_air.set(s["track_air"])
        self.track_ground.set(s["track_ground"])
        self.tts_var.set(s["tts_enabled"])
        self.tts_rate.set(s["tts_rate"])
        self.tts_volume.set(s.get("tts_volume", 100))
        self.radio_filter_var.set(s.get("radio_filter", False))
        self.radio_static_vol_var.set(s.get("radio_static_vol", 40))
        self.radio_crackle_vol_var.set(s.get("radio_crackle_vol", 30))
        self.announce_missiles.set(s["announce_missiles"])
        self.announce_air.set(s["announce_air"])
        self.announce_ground.set(s["announce_ground"])
        self.announce_events.set(s["announce_events"])
        self.threat_timeout.set(s["threat_timeout"])
        self.weapon_timeout.set(s["weapon_timeout"])
        voice_display = self._id_to_display(s.get("tts_voice", ""), self._voices)
        self.tts_voice_var.set(voice_display)
        device_display = self._id_to_display(s.get("tts_device", ""), self._devices)
        self.tts_device_var.set(device_display)
        # Switch to Settings tab so user sees the result
        self.notebook.select(1)

    def _gather_settings(self):
        return {
            "missile_range_nm": self.missile_range.get(),
            "air_range_nm": self.air_range.get(),
            "ground_range_nm": self.ground_range.get(),
            "track_missiles": self.track_missiles.get(),
            "track_air": self.track_air.get(),
            "track_ground": self.track_ground.get(),
            "tts_enabled": self.tts_var.get(),
            "tts_rate": self.tts_rate.get(),
            "tts_volume": self.tts_volume.get(),
            "announce_missiles": self.announce_missiles.get(),
            "announce_air": self.announce_air.get(),
            "announce_ground": self.announce_ground.get(),
            "announce_events": self.announce_events.get(),
            "threat_timeout": self.threat_timeout.get(),
            "weapon_timeout": self.weapon_timeout.get(),
            "tts_voice": self._voice_map.get(self.tts_voice_var.get(), ""),
            "tts_device": self._device_map.get(self.tts_device_var.get(), ""),
            "radio_filter": self.radio_filter_var.get(),
            "radio_static_vol": self.radio_static_vol_var.get(),
            "radio_crackle_vol": self.radio_crackle_vol_var.get(),
            "theme": self.theme_var.get(),
        }

    def _save_settings(self):
        self.settings = self._gather_settings()
        self.tts_enabled = self.settings["tts_enabled"]
        self.tts.enabled = self.tts_enabled
        self.tts.radio_filter = self.settings.get("radio_filter", False)
        self.tts.radio_static_vol = self.settings.get("radio_static_vol", 40)
        self.tts.radio_crackle_vol = self.settings.get("radio_crackle_vol", 30)
        self._apply_tts_config()
        save_settings(self.settings)
        self._queue_log("Settings saved.", 'info')

    def _reset_settings(self):
        d = DEFAULT_SETTINGS
        self.theme_var.set(d.get("theme", "Stealth Dark"))
        self.missile_range.set(d["missile_range_nm"])
        self.air_range.set(d["air_range_nm"])
        self.ground_range.set(d["ground_range_nm"])
        self.track_missiles.set(d["track_missiles"])
        self.track_air.set(d["track_air"])
        self.track_ground.set(d["track_ground"])
        self.tts_var.set(d["tts_enabled"])
        self.tts_rate.set(d["tts_rate"])
        self.tts_volume.set(d.get("tts_volume", 100))
        self.radio_filter_var.set(d.get("radio_filter", False))
        self.radio_static_vol_var.set(d.get("radio_static_vol", 40))
        self.radio_crackle_vol_var.set(d.get("radio_crackle_vol", 30))
        self.announce_missiles.set(d["announce_missiles"])
        self.announce_air.set(d["announce_air"])
        self.announce_ground.set(d["announce_ground"])
        self.announce_events.set(d["announce_events"])
        self.threat_timeout.set(d["threat_timeout"])
        self.weapon_timeout.set(d["weapon_timeout"])
        if self._voice_names:
            self.tts_voice_var.set(self._voice_names[0])
        if self._device_names:
            self.tts_device_var.set(self._device_names[0])
        self._queue_log("Settings reset to defaults.", 'info')

    # ── Update Check ──────────────────────────────────────────────────

    def _check_for_updates(self):
        """Check GitHub Releases API for a newer version."""
        if not GITHUB_REPO:
            self._update_status.config(text="Set GITHUB_REPO first", fg='#f85149')
            return
        self._update_btn.config(state=tk.DISABLED)
        self._update_status.config(text="Checking...", fg='#8b949e')
        threading.Thread(target=self._do_update_check, daemon=True).start()

    def _do_update_check(self):
        import urllib.request
        import urllib.error
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": "DCS-AutoGCI"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            tag = data.get("tag_name", "").lstrip("vV")
            if not tag:
                self.root.after(0, self._update_result, "No release found", '#f85149', None)
                return

            if self._version_tuple(tag) > self._version_tuple(APP_VERSION):
                # Find the Setup.exe asset
                dl_url = None
                for asset in data.get("assets", []):
                    if asset["name"].lower().endswith("setup.exe") or \
                       asset["name"].lower().endswith(".7z"):
                        dl_url = asset["browser_download_url"]
                        break
                self.root.after(0, self._update_result,
                                f"v{tag} available!", '#3fb950', dl_url)
            else:
                self.root.after(0, self._update_result,
                                f"Up to date (v{APP_VERSION})", '#8b949e', None)
        except urllib.error.URLError:
            self.root.after(0, self._update_result,
                            "Network error", '#f85149', None)
        except Exception:
            self.root.after(0, self._update_result,
                            "Check failed", '#f85149', None)

    def _update_result(self, message, color, download_url):
        self._update_btn.config(state=tk.NORMAL)
        self._update_status.config(text=message, fg=color)
        if download_url:
            self._update_btn.config(
                text="\u2B07 Download Update",
                command=lambda: self._open_download(download_url))

    def _open_download(self, url):
        """Open the download URL in the default browser."""
        import webbrowser
        webbrowser.open(url)
        self._update_status.config(text="Opening browser...", fg='#8b949e')

    @staticmethod
    def _version_tuple(v):
        try:
            return tuple(int(x) for x in v.split('.'))
        except ValueError:
            return (0,)

    # ── TTS Actions ───────────────────────────────────────────────────

    def _test_tts(self):
        self._apply_tts_config()
        self.tts.speak("Bandit, 3 o'clock, 25 miles, Angels 20")

    def _unlock_onecore_voices(self):
        """Copy OneCore voice registry keys to standard SAPI5 location."""
        import subprocess
        import tempfile
        import ctypes

        onecore_key = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
        tmp = os.path.join(tempfile.gettempdir(), "autogci_onecore.reg")

        # Export OneCore keys via reg.exe
        result = subprocess.run(
            ["reg", "export", onecore_key, tmp, "/y"],
            capture_output=True, text=True)
        if result.returncode != 0:
            self._queue_log("No OneCore voices found on this system.", 'warning')
            return

        # Read exported .reg file and replace paths
        try:
            with open(tmp, 'r', encoding='utf-16-le') as f:
                content = f.read()
        except UnicodeError:
            with open(tmp, 'r', encoding='utf-8') as f:
                content = f.read()
        content = content.replace("Speech_OneCore", "Speech")
        try:
            with open(tmp, 'w', encoding='utf-16-le') as f:
                f.write(content)
        except Exception as e:
            self._queue_log(f"Failed to write reg file: {e}", 'warning')
            return

        # Import with elevation (requires admin UAC prompt)
        self._queue_log("Requesting admin access to unlock OneCore voices...", 'info')
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "reg.exe", f'import "{tmp}"', None, 0)

        if ret > 32:
            # Give the elevated process a moment to finish
            self.root.after(2000, self._refresh_voices_after_unlock)
        else:
            self._queue_log("Elevation cancelled or failed.", 'warning')

    def _refresh_voices_after_unlock(self):
        """Re-enumerate voices and update the dropdown after OneCore unlock."""
        old_count = len(self._voices)
        self._voices, self._devices = enumerate_tts_options()
        self._voice_map = {name: vid for vid, name in self._voices}
        self._device_map = {name: did for did, name in self._devices}
        self._voice_names = [name for _, name in self._voices]
        self._device_names = [name for _, name in self._devices]

        # Update combobox values
        self._voice_cb['values'] = self._voice_names
        self._device_cb['values'] = self._device_names

        new_count = len(self._voices)
        added = new_count - old_count
        if added > 0:
            self._queue_log(f"Unlocked {added} OneCore voice(s)! "
                            f"Total voices: {new_count}", 'info')
        else:
            self._queue_log("OneCore voices already unlocked "
                            "(or restart app to detect them).", 'info')

    def _apply_tts_config(self):
        voice_id = self._voice_map.get(self.tts_voice_var.get(), "")
        device_id = self._device_map.get(self.tts_device_var.get(), "")
        rate = max(-10, min(10, round((self.tts_rate.get() - 180) / 20)))
        volume = self.tts_volume.get()
        self.tts.configure(voice_id=voice_id, device_id=device_id, rate=rate, volume=volume)

    # ── GUI Helpers ───────────────────────────────────────────────────

    def _clear_log(self):
        self.log_txt.configure(state=tk.NORMAL)
        self.log_txt.delete('1.0', tk.END)
        self.log_txt.configure(state=tk.DISABLED)

    def _append_log(self, message, tag='info'):
        ts = time.strftime("%H:%M:%S")
        self.log_txt.configure(state=tk.NORMAL)
        self.log_txt.insert(tk.END, f"[{ts}] {message}\n", tag)
        self.log_txt.see(tk.END)
        self.log_txt.configure(state=tk.DISABLED)

    def _queue_log(self, message, tag='info'):
        self.log_queue.put((message, tag))

    # ── Periodic GUI Update ───────────────────────────────────────────

    def _tick(self):
        now = time.time()

        # Flush log queue
        while True:
            try:
                msg, tag = self.log_queue.get_nowait()
                self._append_log(msg, tag)
            except queue.Empty:
                break

        # Live-read settings from panel widgets (no need for explicit Apply for filters)
        self.settings = self._gather_settings()
        self.tts_enabled = self.settings["tts_enabled"]
        self.tts.enabled = self.tts_enabled
        self.tts.radio_filter = self.settings.get("radio_filter", False)
        self.tts.radio_static_vol = self.settings.get("radio_static_vol", 40)
        self.tts.radio_crackle_vol = self.settings.get("radio_crackle_vol", 30)

        # Connection status
        if self.connected and (now - self.last_data_time < 5):
            self.status_lbl.configure(text="\u25cf  CONNECTED", fg=GREEN)
            hdg = math.degrees(self.player.heading_rad) % 360
            alt_ft = self.player.alt * 3.28084
            self.player_lbl.configure(
                text=f"{self.player.name}  |  "
                     f"Alt: {alt_ft:,.0f} ft  |  Hdg: {hdg:.0f}\u00b0")
        else:
            self.connected = False
            self.status_lbl.configure(text="\u25cf  WAITING FOR DCS", fg=ORANGE)
            self.player_lbl.configure(text="")

        # Expire stale threats
        stale_ids = []
        for uid, t in self.threats.items():
            timeout = self.settings["weapon_timeout"] if t.category == "WEAPON" else self.settings["threat_timeout"]
            if now - t.last_seen > timeout:
                stale_ids.append(uid)
        for uid in stale_ids:
            t = self.threats.pop(uid)
            self._append_log(f"  Threat gone: {t.name} ({t.category})", 'gone')

        # Rebuild threat table
        self.tree.delete(*self.tree.get_children())
        sorted_threats = sorted(
            self.threats.values(),
            key=lambda t: (
                0 if t.category == "WEAPON" else 1 if t.category == "AIR" else 2,
                t.distance_m))

        for t in sorted_threats:
            dist_nm = t.distance_m * NM_PER_METER
            alt_ft = t.alt * 3.28084
            tag = t.category.lower()
            self.tree.insert('', tk.END, values=(
                f"{t.clock} o'clock", t.category, t.name,
                f"{dist_nm:.1f}", f"{alt_ft:,.0f} ft",
                f"{t.bearing_deg:.0f}\u00b0"), tags=(tag,))

        self.tree.tag_configure('weapon', foreground=RED)
        self.tree.tag_configure('air', foreground=ORANGE)
        self.tree.tag_configure('ground', foreground=YELLOW)

        self.root.after(GUI_UPDATE_MS, self._tick)

    # ── Message Parsing (called from receiver thread) ─────────────────

    def _on_message(self, msg):
        try:
            if msg.startswith("STATUS:"):
                self.connected = msg[7:].strip() == "CONNECTED"
                self.last_data_time = time.time()
                self._queue_log("DCS connected." if self.connected else "DCS disconnected.", 'info')

            elif msg.startswith("SELF:"):
                parts = msg[5:].split("|")
                if len(parts) >= 5:
                    self.player.name = parts[0]
                    self.player.lat = float(parts[1])
                    self.player.lon = float(parts[2])
                    self.player.alt = float(parts[3])
                    self.player.heading_rad = float(parts[4])
                    self.last_data_time = time.time()
                    self.connected = True

            elif msg.startswith("THREAT:"):
                self._parse_threat(msg[7:])

            elif msg.startswith("EVENT:"):
                self._parse_event(msg[6:])

        except (ValueError, IndexError):
            pass

    def _parse_threat(self, payload):
        parts = payload.split("|")
        if len(parts) < 8:
            return

        category, uid, name = parts[0], parts[1], parts[2]
        lat, lon, alt = float(parts[3]), float(parts[4]), float(parts[5])
        heading, coalition = float(parts[6]), int(parts[7])

        bearing = calc_bearing(self.player.lat, self.player.lon, lat, lon)
        distance = haversine_distance(self.player.lat, self.player.lon, lat, lon)
        dist_nm = distance * NM_PER_METER

        # Per-category range and enable filters
        if category == "WEAPON":
            if not self.settings["track_missiles"]:
                return
            if dist_nm > self.settings["missile_range_nm"]:
                return
        elif category == "AIR":
            if not self.settings["track_air"]:
                return
            if dist_nm > self.settings["air_range_nm"]:
                return
        elif category == "GROUND":
            if not self.settings["track_ground"]:
                return
            if dist_nm > self.settings["ground_range_nm"]:
                return

        player_hdg_deg = math.degrees(self.player.heading_rad) % 360
        rel_bearing = (bearing - player_hdg_deg + 360) % 360
        clock = bearing_to_clock(rel_bearing)

        # Aspect (air threats only)
        aspect = calc_aspect(bearing, heading) if category == "AIR" else ""

        now = time.time()
        is_new = uid not in self.threats
        prev_announced_nm = self.threats[uid].last_announced_nm if not is_new else -1.0

        threat = Threat(
            uid=uid, category=category, name=name,
            lat=lat, lon=lon, alt=alt, heading=heading,
            coalition=coalition, bearing_deg=bearing,
            distance_m=distance, clock=clock, aspect=aspect,
            last_announced_nm=prev_announced_nm,
            first_seen=(now if is_new else self.threats[uid].first_seen),
            last_seen=now,
            announced=(not is_new and self.threats[uid].announced))

        self.threats[uid] = threat

        if is_new:
            threat.announced = True
            threat.last_announced_nm = dist_nm
            angels = alt_to_angels(alt)
            # Buffer this new threat for group announcement
            self._pending_new.append((threat, dist_nm, angels))
            # Start (or restart) the group-batch timer
            if self._pending_timer is not None:
                self.root.after_cancel(self._pending_timer)
            self._pending_timer = self.root.after(
                self._GROUP_DELAY_MS, self._process_pending_announcements)
        elif category == "AIR" and threat.last_announced_nm > 0:
            # Re-announce every RANGE_GATE_NM of closure
            closed = threat.last_announced_nm - dist_nm
            if closed >= RANGE_GATE_NM:
                threat.last_announced_nm = dist_nm
                angels = alt_to_angels(alt)
                self._announce_range_update(threat, dist_nm, angels)

    def _announce_range_update(self, threat, dist_nm, angels):
        """Re-announce an air threat at a new range gate with aspect."""
        spoken_name = clean_speech(threat.name)
        aspect = threat.aspect
        speech = f"{spoken_name}, {threat.clock} o'clock, {dist_nm:.0f} miles, {angels}, {aspect}"
        self._queue_log(
            f">> UPDATE: {threat.name} now {threat.clock} o'clock, {dist_nm:.1f} nm, {angels}, {aspect}",
            'air')
        if self.tts_enabled and self.settings["announce_air"]:
            self.tts.speak(clean_speech(speech))

    def _process_pending_announcements(self):
        """Batch-announce new threats, grouping same-type at same clock."""
        self._pending_timer = None
        pending = self._pending_new
        self._pending_new = []
        if not pending:
            return

        # Group by (category, name, clock)
        groups: Dict[tuple, list] = {}
        for threat, dist_nm, angels in pending:
            key = (threat.category, threat.name, threat.clock)
            groups.setdefault(key, []).append((threat, dist_nm, angels))

        for (category, name, clock), members in groups.items():
            count = len(members)
            # Use the closest threat's distance & average altitude for the group
            members.sort(key=lambda m: m[1])
            closest_dist = members[0][1]
            avg_alt_m = sum(t.alt for t, _, _ in members) / count
            angels = alt_to_angels(avg_alt_m)
            aspect = members[0][0].aspect  # aspect from closest member

            if category == "WEAPON":
                if count > 1:
                    speech = f"Warning, {count} missiles, {clock} o'clock, {closest_dist:.0f} miles"
                    self._queue_log(
                        f"!! MISSILES: {count}x {name} at {clock} o'clock, {closest_dist:.1f} nm, {angels}",
                        'weapon')
                else:
                    speech = f"Warning, Missile, {clock} o'clock, {closest_dist:.0f} miles"
                    self._queue_log(
                        f"!! MISSILE: {name} at {clock} o'clock, {closest_dist:.1f} nm, {angels}",
                        'weapon')
            elif category == "AIR":
                spoken_name = clean_speech(name)
                if count > 1:
                    speech = f"Group of {count}, {spoken_name}, {clock} o'clock, {closest_dist:.0f} miles, {angels}, {aspect}"
                    self._queue_log(
                        f">> GROUP {count}x {name} at {clock} o'clock, {closest_dist:.1f} nm, {angels}, {aspect}",
                        'air')
                else:
                    speech = f"Bandit, {spoken_name}, {clock} o'clock, {closest_dist:.0f} miles, {angels}, {aspect}"
                    self._queue_log(
                        f">> BANDIT: {name} at {clock} o'clock, {closest_dist:.1f} nm, {angels}, {aspect}",
                        'air')
            elif category == "GROUND":
                spoken_name = clean_speech(name)
                if count > 1:
                    speech = f"{count} ground threats, {spoken_name}, {clock} o'clock, {closest_dist:.0f} miles"
                    self._queue_log(
                        f"^^ {count}x SAM/AAA: {name} at {clock} o'clock, {closest_dist:.1f} nm",
                        'ground')
                else:
                    speech = f"Ground threat, {spoken_name}, {clock} o'clock, {closest_dist:.0f} miles"
                    self._queue_log(
                        f"^^ SAM/AAA: {name} at {clock} o'clock, {closest_dist:.1f} nm",
                        'ground')
            else:
                speech = f"Contact, {clock} o'clock, {closest_dist:.0f} miles"
                self._queue_log(
                    f"?? THREAT: {name} at {clock} o'clock, {closest_dist:.1f} nm",
                    'info')

            if self.tts_enabled:
                should_speak = (
                    (category == "WEAPON" and self.settings["announce_missiles"]) or
                    (category == "AIR" and self.settings["announce_air"]) or
                    (category == "GROUND" and self.settings["announce_ground"])
                )
                if should_speak:
                    self.tts.speak(clean_speech(speech))

    def _parse_event(self, payload):
        parts = payload.split("|")
        if not parts:
            return
        event_type = parts[0]
        data = parts[1:]

        if event_type == "SHOT":
            shooter = data[0] if data else "Unknown"
            weapon = data[1] if len(data) > 1 else "Unknown"
            self._queue_log(f"LAUNCH: {shooter} fired {weapon}", 'weapon')
            if self.tts_enabled and self.settings["announce_events"]:
                self.tts.speak(clean_speech(f"Launch, {weapon}, from {shooter}"))

        elif event_type == "HIT":
            target = data[0] if data else "Unknown"
            weapon = data[1] if len(data) > 1 else "Unknown"
            self._queue_log(f"HIT: {target} hit by {weapon}", 'weapon')
            if self.tts_enabled and self.settings["announce_events"]:
                self.tts.speak(clean_speech(f"Hit on {target}"))

        elif event_type == "SHOOTING":
            shooter = data[0] if data else "Unknown"
            self._queue_log(f"GUNS: {shooter} firing", 'event')
            if self.tts_enabled and self.settings["announce_events"]:
                self.tts.speak(clean_speech(f"Guns, guns, {shooter}"))

        elif event_type == "PILOT_DEAD":
            self._queue_log("PILOT KILLED", 'weapon')
            if self.tts_enabled and self.settings["announce_events"]:
                self.tts.speak("Pilot killed")

    # ── Shutdown ──────────────────────────────────────────────────────

    def _on_close(self):
        # Auto-save current settings on exit
        self.settings = self._gather_settings()
        save_settings(self.settings)
        self.receiver.stop()
        self.tts.stop()
        self.root.destroy()

    def run(self):
        self._queue_log(f"Listening on UDP {UDP_HOST}:{UDP_PORT} ...", 'info')
        # Auto-setup Export.lua dofile entries
        for variant, status in ensure_dcs_export():
            if status == "added":
                self._queue_log(f"Linked Export.lua in {variant} — restart DCS to activate.", 'info')
            elif status == "ok":
                self._queue_log(f"Export.lua OK for {variant}.", 'info')
            elif status == "error":
                self._queue_log(f"Could not update Export.lua in {variant}.", 'warn')
        self._queue_log("Start a DCS mission with the export script installed.", 'info')
        self.root.mainloop()


# ── Entry Point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ThreatWarnerApp()
    app.run()
