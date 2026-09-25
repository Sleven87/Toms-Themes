#!/usr/bin/env python3
"""Tom's Themes - browse wallpapers and pick a colour theme for KDE Plasma.

Pick a wallpaper, then either choose a well-known theme (Catppuccin, Nord, ...) or
let the app pull contrasting colour families out of the wallpaper itself and build
themes from those.  Applying sets the wallpaper and the KDE colour scheme.
"""
import colorsys
import configparser
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtCore import (QObject, QPoint, QRect, QRectF, QRunnable, QSize, Qt,
                          QThreadPool, QTimer, pyqtSignal)
from PyQt6.QtGui import (QAction, QColor, QFont, QGuiApplication, QIcon, QImage,
                         QImageReader, QPainter, QPainterPath, QPixmap)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QLineEdit,
                             QGridLayout, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox,
                             QMenu, QPushButton, QRadioButton, QScrollArea, QSplitter,
                             QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

APP_NAME = "Tom's Themes"
DESKTOP_ID = "toms-themes"
ICON_FILE = Path.home() / ".local/share/icons/hicolor/scalable/apps/toms-themes.svg"
CONFIG = Path.home() / ".config" / "toms-themes" / "config.json"
SCHEME_DIR = Path.home() / ".local" / "share" / "color-schemes"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif", ".jxl", ".tif", ".tiff"}
DEFAULT_FOLDERS = [Path.home() / "Pictures", Path("/usr/share/wallpapers"),
                   Path.home() / "Wallpapers", Path.home() / ".local/share/wallpapers"]


# --------------------------------------------------------------------------- colour maths
_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb):
    """rgb: Nx3 floats 0..255 -> Nx3 Lab."""
    c = np.asarray(rgb, dtype=float) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = (lin @ _M.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def _lab_to_linear_rgb(L, a, b):
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    inv = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = inv(fx) * _WHITE[0], inv(fy), inv(fz) * _WHITE[2]
    r = 3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
    g = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
    bl = 0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z
    gam = lambda u: 12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055
    return gam(r), gam(g), gam(bl)


def lch_hex(L, C, h):
    """Lab-LCH -> hex, shrinking chroma until the colour fits in sRGB."""
    L = max(0.0, min(100.0, L))
    for _ in range(60):
        rgb = _lab_to_linear_rgb(L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h)))
        if all(-0.002 <= v <= 1.002 for v in rgb):
            break
        C *= 0.94
    return "#%02x%02x%02x" % tuple(int(round(min(1, max(0, v)) * 255)) for v in rgb)


def hex_rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(h1, h2, t):
    a, b = hex_rgb(h1), hex_rgb(h2)
    return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def luminance(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = hex_rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(h1, h2):
    a, b = sorted((luminance(h1), luminance(h2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def on_colour(h):
    """Readable text colour to put on top of h."""
    return "#101014" if contrast(h, "#101014") >= contrast(h, "#ffffff") else "#ffffff"


# --------------------------------------------------------------------------- known themes
# name, dark?, background, surface, text, dim text, accent, red, green, yellow
KNOWN = [
    ("Catppuccin Mocha", True, "#1e1e2e", "#313244", "#cdd6f4", "#a6adc8", "#cba6f7", "#f38ba8", "#a6e3a1", "#f9e2af"),
    ("Catppuccin Latte", False, "#eff1f5", "#ccd0da", "#4c4f69", "#6c6f85", "#8839ef", "#d20f39", "#40a02b", "#df8e1d"),
    ("Nord", True, "#2e3440", "#3b4252", "#eceff4", "#d8dee9", "#88c0d0", "#bf616a", "#a3be8c", "#ebcb8b"),
    ("Dracula", True, "#282a36", "#44475a", "#f8f8f2", "#9aa2c8", "#bd93f9", "#ff5555", "#50fa7b", "#f1fa8c"),
    ("Gruvbox Dark", True, "#282828", "#3c3836", "#ebdbb2", "#a89984", "#fe8019", "#fb4934", "#b8bb26", "#fabd2f"),
    ("Gruvbox Light", False, "#fbf1c7", "#ebdbb2", "#3c3836", "#665c54", "#af3a03", "#9d0006", "#79740e", "#b57614"),
    ("Tokyo Night", True, "#1a1b26", "#24283b", "#c0caf5", "#9aa5ce", "#7aa2f7", "#f7768e", "#9ece6a", "#e0af68"),
    ("Rosé Pine", True, "#191724", "#26233a", "#e0def4", "#908caa", "#c4a7e7", "#eb6f92", "#9ccfd8", "#f6c177"),
    ("Solarized Dark", True, "#002b36", "#073642", "#93a1a1", "#839496", "#268bd2", "#dc322f", "#859900", "#b58900"),
    ("Solarized Light", False, "#fdf6e3", "#eee8d5", "#586e75", "#657b83", "#268bd2", "#dc322f", "#859900", "#b58900"),
    ("One Dark", True, "#282c34", "#353b45", "#abb2bf", "#7f848e", "#61afef", "#e06c75", "#98c379", "#e5c07b"),
    ("Everforest", True, "#2d353b", "#3d484d", "#d3c6aa", "#9da9a0", "#a7c080", "#e67e80", "#a7c080", "#dbbc7f"),
    ("Kanagawa", True, "#1f1f28", "#2a2a37", "#dcd7ba", "#a6a69c", "#7e9cd8", "#e46876", "#98bb6c", "#e6c384"),
]


def make_theme(name, dark, bg, alt, fg, dim, accent, red, green, yellow, **extra):
    t = dict(name=name, dark=dark, bg=bg, bg_alt=alt, fg=fg, fg_dim=dim, accent=accent,
             red=red, green=green, yellow=yellow, accent_fg=on_colour(accent))
    t.update(extra)
    return t


def known_themes():
    return [make_theme(*k) for k in KNOWN]


def installed_themes():
    """Colour schemes already installed on the system (Breeze, CachyOS Nord, ...)."""
    out = []
    dirs = ["/usr/share/color-schemes", str(SCHEME_DIR)]
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".colors") or f.startswith("TomsThemes"):
                continue
            cp = configparser.ConfigParser(strict=False, interpolation=None)
            cp.optionxform = str
            try:
                cp.read(os.path.join(d, f), encoding="utf-8")

                def col(sec, key):
                    r, g, b = [int(x) for x in cp[sec][key].split(",")[:3]]
                    return "#%02x%02x%02x" % (r, g, b)
                bg = col("Colors:Window", "BackgroundNormal")
                t = make_theme(cp["General"].get("Name", f[:-7]), luminance(bg) < 0.3, bg,
                               col("Colors:Button", "BackgroundNormal"),
                               col("Colors:Window", "ForegroundNormal"),
                               col("Colors:Window", "ForegroundInactive"),
                               col("Colors:Selection", "BackgroundNormal"),
                               col("Colors:Window", "ForegroundNegative"),
                               col("Colors:Window", "ForegroundPositive"),
                               col("Colors:Window", "ForegroundNeutral"),
                               installed_id=f[:-7])
                out.append(t)
            except Exception:
                continue
    return out


# --------------------------------------------------------------------------- KDE colour scheme writer
def _rgb(h):
    return "%d,%d,%d" % hex_rgb(h)


def _section(name, bg, alt, fg, dim, active, focus, hover, link, visited, neg, neu, pos):
    return (f"[Colors:{name}]\nBackgroundAlternate={_rgb(alt)}\nBackgroundNormal={_rgb(bg)}\n"
            f"DecorationFocus={_rgb(focus)}\nDecorationHover={_rgb(hover)}\nForegroundActive={_rgb(active)}\n"
            f"ForegroundInactive={_rgb(dim)}\nForegroundLink={_rgb(link)}\nForegroundNegative={_rgb(neg)}\n"
            f"ForegroundNeutral={_rgb(neu)}\nForegroundNormal={_rgb(fg)}\nForegroundPositive={_rgb(pos)}\n"
            f"ForegroundVisited={_rgb(visited)}\n\n")


def scheme_text(t, scheme_id):
    dark = t["dark"]
    bg, alt, fg, dim, acc = t["bg"], t["bg_alt"], t["fg"], t["fg_dim"], t["accent"]
    view = mix(bg, "#000000", 0.22) if dark else mix(bg, "#ffffff", 0.55)
    hover = mix(acc, "#ffffff", 0.18) if dark else mix(acc, "#000000", 0.15)
    link = acc if contrast(acc, bg) >= 3 else fg
    visited = mix(acc, fg, 0.5)
    r, g, y = t["red"], t["green"], t["yellow"]
    common = (acc, acc, hover, link, visited, r, y, g)
    afg = t["accent_fg"]
    sel_alt = mix(acc, "#000000", 0.15)
    s = ""
    s += _section("View", view, bg, fg, dim, acc, acc, hover, link, visited, r, y, g)
    s += _section("Window", bg, alt, fg, dim, *common)
    s += _section("Button", alt, mix(alt, bg, 0.5), fg, dim, *common)
    s += _section("Tooltip", alt, bg, fg, dim, *common)
    s += _section("Complementary", bg, alt, fg, dim, *common)
    s += _section("Header", alt, bg, fg, dim, *common)
    s += _section("Selection", acc, sel_alt, afg, mix(afg, acc, 0.3), afg, afg, afg, afg, afg, afg, afg, afg)
    s += ("[ColorEffects:Disabled]\nColor=56,56,56\nColorAmount=0\nColorEffect=0\nContrastAmount=0.65\n"
          "ContrastEffect=1\nIntensityAmount=0.1\nIntensityEffect=2\n\n"
          "[ColorEffects:Inactive]\nChangeSelectionColor=true\nColor=112,111,110\nColorAmount=0.025\n"
          "ColorEffect=2\nContrastAmount=0.1\nContrastEffect=2\nEnable=false\nIntensityAmount=0\nIntensityEffect=0\n\n")
    s += (f"[General]\nColorScheme={scheme_id}\nName={APP_NAME} - {t['name']}\nshadeSortColumn=true\n\n"
          f"[KDE]\ncontrast=4\n\n"
          f"[WM]\nactiveBackground={_rgb(alt)}\nactiveBlend={_rgb(fg)}\nactiveForeground={_rgb(fg)}\n"
          f"inactiveBackground={_rgb(bg)}\ninactiveBlend={_rgb(dim)}\ninactiveForeground={_rgb(dim)}\n")
    return s


# --------------------------------------------------------------------------- desktop backends
# The app looks at the running desktop and uses the matching backend to set wallpapers and colours.
def detect_desktop():
    env = (os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("DESKTOP_SESSION", "")).lower()
    if "kde" in env or "plasma" in env:
        return "kde"
    if any(k in env for k in ("gnome", "ubuntu", "unity")):
        return "gnome"
    return "other"


def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(f"'{cmd[0]}' is not installed")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "command failed").strip())
    return r.stdout.strip()


class KdeBackend:
    name = "KDE Plasma"

    def installed_themes(self):
        return installed_themes()

    def snapshot(self):
        try:
            return run_cmd(["kreadconfig6", "--file", "kdeglobals", "--group", "General", "--key", "ColorScheme"])
        except RuntimeError:
            return ""

    def apply_wallpaper(self, path):
        run_cmd(["plasma-apply-wallpaperimage", path])

    def apply_theme(self, t):
        if t.get("installed_id"):
            scheme_id = t["installed_id"]
        else:
            digest = hashlib.md5(json.dumps([t[k] for k in ("bg", "bg_alt", "fg", "accent")]).encode()).hexdigest()[:6]
            stem = "Match" if t.get("match") else re.sub(r"[^A-Za-z0-9]", "", t["name"])
            scheme_id = f"TomsThemes{stem}" + (digest if t.get("match") else "")
            SCHEME_DIR.mkdir(parents=True, exist_ok=True)
            (SCHEME_DIR / f"{scheme_id}.colors").write_text(scheme_text(t, scheme_id), encoding="utf-8")
        # NB: don't pass --accent-color here; with it plasma-apply-colorscheme ignores the scheme name.
        run_cmd(["plasma-apply-colorscheme", scheme_id])
        if t.get("match"):                      # tidy up older generated match schemes
            for f in SCHEME_DIR.glob("TomsThemesMatch*.colors"):
                if f.stem != scheme_id:
                    f.unlink(missing_ok=True)

    def restore(self, snap):
        if not snap:
            raise RuntimeError("No previous colour scheme was recorded.")
        run_cmd(["plasma-apply-colorscheme", snap])
        return f"Restored colour scheme “{snap}”."


GNOME_ACCENTS = {"blue": "#3584e4", "teal": "#2190a4", "green": "#3a944a", "yellow": "#c88800",
                 "orange": "#ed5b00", "red": "#e62d42", "pink": "#d56199", "purple": "#9141ac",
                 "slate": "#6f8396"}
GTK_START, GTK_END = "/* >>> Tom's Themes >>> */", "/* <<< Tom's Themes <<< */"
GTK_BLOCK_RE = re.compile(re.escape(GTK_START) + r".*?" + re.escape(GTK_END) + r"\n?", re.S)


def gtk_css(t):
    """@define-color overrides understood by libadwaita (GTK4) and Adwaita-based GTK3 themes."""
    bg, alt, fg, dim, acc, afg = t["bg"], t["bg_alt"], t["fg"], t["fg_dim"], t["accent"], t["accent_fg"]
    view = mix(bg, "#000000", 0.22) if t["dark"] else mix(bg, "#ffffff", 0.55)
    acc_text = acc if contrast(acc, bg) >= 3 else mix(acc, fg, 0.5)
    red, green, yellow = t["red"], t["green"], t["yellow"]
    pairs = {
        "accent_bg_color": acc, "accent_fg_color": afg, "accent_color": acc_text,
        "destructive_bg_color": red, "destructive_fg_color": on_colour(red), "destructive_color": red,
        "success_bg_color": green, "success_fg_color": on_colour(green), "success_color": green,
        "warning_bg_color": yellow, "warning_fg_color": on_colour(yellow), "warning_color": yellow,
        "error_bg_color": red, "error_fg_color": on_colour(red), "error_color": red,
        "window_bg_color": bg, "window_fg_color": fg, "view_bg_color": view, "view_fg_color": fg,
        "headerbar_bg_color": alt, "headerbar_fg_color": fg, "headerbar_border_color": alt,
        "headerbar_backdrop_color": bg,
        "card_bg_color": alt, "card_fg_color": fg, "dialog_bg_color": alt, "dialog_fg_color": fg,
        "popover_bg_color": alt, "popover_fg_color": fg,
        "sidebar_bg_color": alt, "sidebar_fg_color": fg, "sidebar_backdrop_color": bg,
        "secondary_sidebar_bg_color": bg, "secondary_sidebar_fg_color": fg,
        # names used by GTK3 apps / Adwaita-derived GTK3 themes
        "theme_bg_color": bg, "theme_fg_color": fg, "theme_base_color": view, "theme_text_color": fg,
        "theme_selected_bg_color": acc, "theme_selected_fg_color": afg,
        "theme_unfocused_bg_color": bg, "theme_unfocused_fg_color": dim,
        "theme_unfocused_base_color": view, "theme_unfocused_text_color": dim,
        "theme_unfocused_selected_bg_color": mix(acc, bg, 0.4), "theme_unfocused_selected_fg_color": afg,
        "insensitive_bg_color": mix(bg, fg, 0.06), "insensitive_fg_color": dim, "insensitive_base_color": view,
        "borders": mix(bg, fg, 0.18), "unfocused_borders": mix(bg, fg, 0.12),
    }
    body = "\n".join(f"@define-color {k} {v};" for k, v in pairs.items())
    return f"{GTK_START}\n/* {t['name']} - generated by Tom's Themes; remove this block to undo */\n{body}\n{GTK_END}\n"


def nearest_gnome_accent(hexcol):
    r, g, b = hex_rgb(hexcol)
    return min(GNOME_ACCENTS, key=lambda n: sum((x - y) ** 2 for x, y in zip((r, g, b), hex_rgb(GNOME_ACCENTS[n]))))


class GnomeBackend:
    """GNOME / Ubuntu: wallpaper + dark/light + accent through gsettings, colours through gtk.css."""
    name = "GNOME / Ubuntu"
    IFACE, BG = "org.gnome.desktop.interface", "org.gnome.desktop.background"

    def __init__(self, config_home=None):
        self.config_home = Path(config_home) if config_home else Path.home() / ".config"

    def installed_themes(self):
        return []

    def _get(self, schema, key):
        try:
            return run_cmd(["gsettings", "get", schema, key])
        except RuntimeError:
            return None

    def _set(self, schema, key, value, required=False):
        try:
            run_cmd(["gsettings", "set", schema, key, value])
        except RuntimeError:
            if required:
                raise                      # optional keys may not exist on older GNOME versions

    def snapshot(self):
        return {"color-scheme": self._get(self.IFACE, "color-scheme"),
                "accent-color": self._get(self.IFACE, "accent-color")}

    def apply_wallpaper(self, path):
        uri = Path(path).resolve().as_uri()
        self._set(self.BG, "picture-uri", f"'{uri}'", required=True)
        self._set(self.BG, "picture-uri-dark", f"'{uri}'")
        self._set(self.BG, "picture-options", "'zoom'")

    def _css_files(self):
        return [self.config_home / d / "gtk.css" for d in ("gtk-4.0", "gtk-3.0")]

    def apply_theme(self, t):
        block = gtk_css(t)
        for f in self._css_files():
            f.parent.mkdir(parents=True, exist_ok=True)
            old = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""
            old = GTK_BLOCK_RE.sub("", old).rstrip()
            f.write_text((old + "\n\n" if old else "") + block, encoding="utf-8")
        self._set(self.IFACE, "color-scheme", "'prefer-dark'" if t["dark"] else "'default'")
        self._set(self.IFACE, "accent-color", f"'{nearest_gnome_accent(t['accent'])}'")

    def restore(self, snap):
        for f in self._css_files():          # remove only our block; keep anything else the user had
            if f.exists():
                rest = GTK_BLOCK_RE.sub("", f.read_text(encoding="utf-8", errors="replace")).strip()
                if rest:
                    f.write_text(rest + "\n", encoding="utf-8")
                else:
                    f.unlink()
        for key, value in (snap or {}).items():
            if value:
                self._set(self.IFACE, key, value)
        return "Restored the previous GNOME appearance (restart open apps to see it)."


class UnsupportedBackend:
    name = "unsupported desktop"

    def installed_themes(self):
        return []

    def snapshot(self):
        return None

    def _no(self):
        raise RuntimeError("Tom's Themes can set wallpapers and themes on KDE Plasma and GNOME/Ubuntu. "
                           f"Your desktop ({os.environ.get('XDG_CURRENT_DESKTOP', 'unknown')}) isn't supported yet.")

    def apply_wallpaper(self, path):
        self._no()

    def apply_theme(self, t):
        self._no()

    def restore(self, snap):
        self._no()


def get_backend():
    return {"kde": KdeBackend, "gnome": GnomeBackend}.get(detect_desktop(), UnsupportedBackend)()


# --------------------------------------------------------------------------- wallpaper colour extraction
def load_small(path, maxdim=160):
    r = QImageReader(str(path))
    r.setAutoTransform(True)
    sz = r.size()
    if sz.isValid():
        r.setScaledSize(sz.scaled(maxdim, maxdim, Qt.AspectRatioMode.KeepAspectRatio))
    img = r.read()
    if img.isNull():
        raise ValueError("cannot read image")
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].reshape(h * w, 3)
    return arr.astype(float)


def kmeans(X, k, iters=15, seed=1):
    rng = np.random.default_rng(seed)
    first = X[rng.integers(len(X))]
    centers, d = [first], ((X - first) ** 2).sum(1)
    for _ in range(k - 1):
        p = d / d.sum() if d.sum() > 0 else None
        c = X[rng.choice(len(X), p=p)]
        centers.append(c)
        d = np.minimum(d, ((X - c) ** 2).sum(1))
    C = np.array(centers)
    for _ in range(iters):
        lab = ((X[:, None, :] - C[None, :, :]) ** 2).sum(2).argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = X[m].mean(0)
    return C, np.bincount(lab, minlength=k) / len(X)


def colour_families(path):
    """Distinct colour families in the image, biggest first."""
    lab = rgb_to_lab(load_small(path))
    C, w = kmeans(lab, min(14, len(lab)))
    fams = [[C[i], float(w[i])] for i in range(len(C)) if w[i] > 0]
    merged = True
    while merged:                       # fold near-identical clusters together
        merged = False
        for i in range(len(fams)):
            for j in range(i + 1, len(fams)):
                if np.linalg.norm(fams[i][0] - fams[j][0]) < 22:
                    wi, wj = fams[i][1], fams[j][1]
                    fams[i] = [(fams[i][0] * wi + fams[j][0] * wj) / (wi + wj), wi + wj]
                    del fams[j]
                    merged = True
                    break
            if merged:
                break
    out = []
    for c, share in fams:
        L, a, b = c
        chroma = math.hypot(a, b)
        if share >= (0.015 if chroma > 30 else 0.04):   # vivid accents count even when small
            out.append(dict(L=float(L), C=float(chroma), h=math.degrees(math.atan2(b, a)) % 360,
                            share=share, lab=c))
    out.sort(key=lambda f: -f["share"])
    return out[:7]


def colour_name(f):
    L, C, h = f["L"], f["C"], f["h"]
    if C < 14:
        return "Black" if L < 24 else "White" if L > 88 else "Grey"
    name = "Grey"
    for lim, nm in ((28, "Pink"), (55, "Red"), (85, "Orange"), (112, "Yellow"), (165, "Green"),
                    (235, "Cyan"), (300, "Blue"), (335, "Purple"), (361, "Pink")):
        if h < lim:
            name = "Brown" if nm == "Orange" and L < 50 else nm
            break
    return f"Dark {name}" if L < 30 else name


def match_themes(fams, dark=True, limit=10):
    """Turn the wallpaper's colour families into background + accent pairs."""
    cands = []
    for i, A in enumerate(fams):         # A = background family
        for j, B in enumerate(fams):     # B = accent family
            if i == j:
                continue
            de = float(np.linalg.norm(A["lab"] - B["lab"]))
            if de < 38:
                continue
            if A["C"] > 25 and B["C"] < 18:      # a grey accent on a coloured background looks dull
                continue
            neutral_bg = A["C"] < 14 and B["C"] >= 18   # grey/black background with a colourful accent is always fine
            if dark and A["L"] > B["L"] + 5 and not neutral_bg:      # dark: background is the darker family
                continue
            if not dark and A["L"] < B["L"] - 5 and not neutral_bg:  # light: background is the lighter family
                continue
            if B["C"] < 18 and abs(A["L"] - B["L"]) < 40:
                continue
            score = de + 60 * (A["share"] + B["share"]) + 0.4 * B["C"]
            cands.append((score, A, B))
    cands.sort(key=lambda x: -x[0])
    themes, seen = [], set()
    for score, A, B in cands:
        name = f"{colour_name(B)} · {colour_name(A)}"
        t = palette_from(name, A, B, dark)
        key = (t["bg"], t["accent"])
        if name in seen or key in seen:
            continue
        seen.update((name, key))
        themes.append(t)
        if len(themes) >= limit:
            break
    return themes


def palette_from(name, A, B, dark):
    ha, hb = A["h"], B["h"]
    ca = min(A["C"] * 0.5, 14) if A["C"] >= 14 else 0.0
    cb = B["C"] if B["C"] >= 18 else 0.0
    if dark:
        bg = lch_hex(max(10, min(A["L"], 14)) + 2, ca, ha)
        alt = lch_hex(22, ca, ha)
        fg = lch_hex(92, min(6, ca), ha)
        dim = lch_hex(68, min(8, ca), ha)
        accent = lch_hex(max(62, min(B["L"], 78)), max(cb, 45) if cb else 0.0, hb)
        red, green, yellow = "#f38ba8", "#a6e3a1", "#f9e2af"
    else:
        bg = lch_hex(95, min(ca, 8), ha)
        alt = lch_hex(89, min(ca, 10), ha)
        fg = lch_hex(20, min(6, ca), ha)
        dim = lch_hex(42, min(8, ca), ha)
        accent = lch_hex(min(48, max(38, B["L"])), max(cb, 50) if cb else 0.0, hb)
        red, green, yellow = "#c0392b", "#2e7d32", "#b26a00"
    return make_theme(name, dark, bg, alt, fg, dim, accent, red, green, yellow, match=True)


# --------------------------------------------------------------------------- wallpaper scanning + thumbnails
def scan_folder(folder, cap=2500):
    folder = str(folder)
    res = []
    for root, dirs, files in os.walk(folder):
        if root[len(folder):].count(os.sep) > 4:
            dirs[:] = []
            continue
        dirs.sort()
        if root.endswith(os.path.join("contents", "images")):     # KDE wallpaper packages
            imgs = [f for f in files if os.path.splitext(f)[1].lower() in IMG_EXT]
            if imgs:
                best = max(imgs, key=lambda f: os.path.getsize(os.path.join(root, f)))
                res.append((os.path.join(root, best), os.path.basename(os.path.dirname(os.path.dirname(root)))))
            dirs[:] = []
            continue
        if os.sep + "contents" + os.sep in root + os.sep:
            continue
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in IMG_EXT:
                res.append((os.path.join(root, f), os.path.splitext(f)[0]))
        if len(res) >= cap:
            break
    return res


HUE_LIMITS = [28, 55, 85, 112, 165, 235, 300, 335]
HUE_NAMES = ["Pink", "Red", "Orange", "Yellow", "Green", "Cyan", "Blue", "Purple", "Pink"]


def colour_signature(img):
    """Cheap colour summary of a thumbnail: which colour tags it has, its average hue and lightness."""
    small = img.scaled(48, 27, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB888)
    w, h = small.width(), small.height()
    ptr = small.constBits()
    ptr.setsize(small.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, small.bytesPerLine())[:, :w * 3].reshape(-1, 3).astype(float)
    lab = rgb_to_lab(arr)
    L, C = lab[:, 0], np.hypot(lab[:, 1], lab[:, 2])
    H = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    n = len(L)
    chrom = C >= 18
    idx = np.digitize(H, HUE_LIMITS)
    tags = {name for i, name in enumerate(HUE_NAMES) if (chrom & (idx == i)).sum() / n >= 0.10}
    if ((~chrom) & (L < 30)).sum() / n >= 0.25 or L.mean() < 30:
        tags.add("Dark")
    if ((~chrom) & (L > 80)).sum() / n >= 0.25 or L.mean() > 72:
        tags.add("Light")
    if ((~chrom) & (L >= 30) & (L <= 80)).sum() / n >= 0.25:
        tags.add("Grey")
    hue = 0.0
    if chrom.any():
        ang, wts = np.radians(H[chrom]), C[chrom]
        hue = math.degrees(math.atan2((np.sin(ang) * wts).sum(), (np.cos(ang) * wts).sum())) % 360
    return dict(tags=sorted(tags), hue=float(hue), chroma=float(chrom.mean()), L=float(L.mean()))


class ThumbSignals(QObject):
    ready = pyqtSignal(str, QImage, object)


class ThumbJob(QRunnable):
    def __init__(self, path, signals):
        super().__init__()
        self.path, self.signals = path, signals

    def run(self):
        r = QImageReader(self.path)
        r.setAutoTransform(True)
        sz = r.size()
        if sz.isValid():
            r.setScaledSize(sz.scaled(320, 180, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        img = r.read()
        if img.isNull():
            return
        meta = colour_signature(img)
        meta["size"] = (sz.width(), sz.height()) if sz.isValid() else (img.width(), img.height())
        self.signals.ready.emit(self.path, img, meta)


SORTS = [("Name (A–Z)", "name", False), ("Name (Z–A)", "name", True),
         ("Newest first", "date", True), ("Oldest first", "date", False),
         ("Largest resolution", "res", True), ("Smallest resolution", "res", False),
         ("Colour (rainbow)", "hue", False), ("Brightest first", "light", True),
         ("Darkest first", "light", False), ("File size (largest)", "fsize", True),
         ("File size (smallest)", "fsize", False)]
COLOUR_FILTERS = [("Any colour", None), ("Red", "#e5484d"), ("Orange", "#f5883b"), ("Yellow", "#f2c94c"),
                  ("Green", "#46b96b"), ("Cyan", "#2fbfc4"), ("Blue", "#3b82f6"), ("Purple", "#9b5de5"),
                  ("Pink", "#ec6fa8"), ("Dark", "#1a1a1a"), ("Grey", "#808080"), ("Light", "#f2f2f2")]
SIZE_FILTERS = [("Any size", None), ("Full HD or larger", (1920, 1080)), ("1440p or larger", (2560, 1440)),
                ("4K or larger", (3840, 2160)), ("Ultrawide (21:9 or wider)", "ultra"), ("Portrait", "portrait")]


# --------------------------------------------------------------------------- widgets
class ThemeCard(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, theme):
        super().__init__()
        self.theme, self.selected = theme, False
        self.setFixedSize(196, 136)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{theme['name']}\nBackground {theme['bg']}   Accent {theme['accent']}   Text {theme['fg']}")

    def set_selected(self, on):
        self.selected = on
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit(self)

    def paintEvent(self, _):
        t = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(4, 4, self.width() - 8, 100)
        clip = QPainterPath()
        clip.addRoundedRect(card, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.fillRect(card, QColor(t["bg"]))
        p.fillRect(QRectF(card.left(), card.top(), card.width(), 16), QColor(t["bg_alt"]))
        p.setPen(Qt.PenStyle.NoPen)
        for i, c in enumerate((t["red"], t["yellow"], t["green"])):
            p.setBrush(QColor(c))
            p.drawEllipse(QPoint(int(card.left()) + 11 + i * 11, int(card.top()) + 8), 3, 3)
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(t["fg"]))
        p.drawText(QRect(int(card.left()) + 10, int(card.top()) + 20, int(card.width()) - 20, 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Aa  Sample text")
        f.setBold(False)
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QColor(t["fg_dim"]))
        p.drawText(QRect(int(card.left()) + 10, int(card.top()) + 40, int(card.width()) - 20, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Secondary text")
        bar = QRectF(card.left() + 8, card.top() + 62, card.width() - 16, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["accent"]))
        p.drawRoundedRect(bar, 5, 5)
        p.setPen(QColor(t["accent_fg"]))
        p.drawText(bar.adjusted(8, 0, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Highlighted item")
        p.restore()
        p.setPen(QColor(self.palette().color(self.foregroundRole())))
        f.setPointSize(9)
        f.setBold(self.selected)
        p.setFont(f)
        p.drawText(QRect(4, 108, self.width() - 8, 24), Qt.AlignmentFlag.AlignCenter,
                   p.fontMetrics().elidedText(t["name"], Qt.TextElideMode.ElideRight, self.width() - 12))
        pen_col = self.palette().color(self.palette().ColorRole.Highlight) if self.selected \
            else QColor(128, 128, 128, 90)
        from PyQt6.QtGui import QPen
        p.setPen(QPen(pen_col, 3 if self.selected else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card, 8, 8)


class CardGrid(QWidget):
    """Scrollable grid of theme cards with optional section headings."""
    selected = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll)
        self.cards = []
        self.columns = 2

    def set_sections(self, sections, note=None):
        """sections: list of (heading or None, [themes])"""
        body = QWidget()
        lay = QGridLayout(body)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(6)
        self.cards = []
        row = 0
        if note:
            lb = QLabel(note)
            lb.setWordWrap(True)
            lb.setStyleSheet("opacity:0.7;")
            lay.addWidget(lb, row, 0, 1, self.columns)
            row += 1
        for heading, themes in sections:
            if heading:
                lb = QLabel(f"<b>{heading}</b>")
                lay.addWidget(lb, row, 0, 1, self.columns)
                row += 1
            for i, t in enumerate(themes):
                c = ThemeCard(t)
                c.clicked.connect(self._pick)
                self.cards.append(c)
                lay.addWidget(c, row + i // self.columns, i % self.columns)
            row += (len(themes) + self.columns - 1) // self.columns
        self.scroll.setWidget(body)

    def _pick(self, card):
        for c in self.cards:
            c.set_selected(c is card)
        self.selected.emit(card.theme)

    def clear_selection(self):
        for c in self.cards:
            c.set_selected(False)


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}")
        self.resize(1400, 820)
        self.cfg = self.load_config()
        self.wallpaper = None
        self.theme = None
        self.items = {}
        self.fam_cache = {}
        self.backend = get_backend()
        self.snapshot = self.backend.snapshot()
        self.pool = QThreadPool.globalInstance()
        self.signals = ThumbSignals()
        self.signals.ready.connect(self.on_thumb)

        split = QSplitter()
        self.setCentralWidget(split)

        # left: folders
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Wallpaper folders</b>"))
        self.folders = QListWidget()
        self.folders.currentRowChanged.connect(self.folder_changed)
        ll.addWidget(self.folders)
        b = QPushButton("Add folder…")
        b.clicked.connect(self.add_folder)
        ll.addWidget(b)
        b = QPushButton("Open image file…")
        b.clicked.connect(self.open_file)
        ll.addWidget(b)
        b = QPushButton("Remove selected folder")
        b.clicked.connect(self.remove_folder)
        ll.addWidget(b)
        split.addWidget(left)

        # middle: wallpaper grid
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(240, 135))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSpacing(8)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.currentItemChanged.connect(self.wallpaper_picked)

        mid = QWidget()
        ml_ = QVBoxLayout(mid)
        ml_.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search wallpapers…")
        self.search.setClearButtonEnabled(True)
        ml_.addWidget(self.search)
        bar = QHBoxLayout()
        self.sort_combo, self.colour_combo, self.size_combo = QComboBox(), QComboBox(), QComboBox()
        for label, *_ in SORTS:
            self.sort_combo.addItem(label)
        for label, hexcol in COLOUR_FILTERS:
            if hexcol:
                pm = QPixmap(14, 14)
                pm.fill(QColor(hexcol))
                self.colour_combo.addItem(QIcon(pm), label)
            else:
                self.colour_combo.addItem(label)
        for label, _ in SIZE_FILTERS:
            self.size_combo.addItem(label)
        for text, combo in (("Sort", self.sort_combo), ("Colour", self.colour_combo), ("Size", self.size_combo)):
            bar.addWidget(QLabel(text))
            bar.addWidget(combo, 1)
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset_filters)
        bar.addWidget(reset)
        ml_.addLayout(bar)
        ml_.addWidget(self.grid, 1)
        split.addWidget(mid)

        self.records = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh_grid)
        self.sort_combo.setCurrentIndex(min(self.cfg.get("sort", 0), len(SORTS) - 1))
        self.colour_combo.setCurrentIndex(min(self.cfg.get("colour", 0), len(COLOUR_FILTERS) - 1))
        self.size_combo.setCurrentIndex(min(self.cfg.get("size", 0), len(SIZE_FILTERS) - 1))
        self.search.textChanged.connect(self.schedule_refresh)
        for c in (self.sort_combo, self.colour_combo, self.size_combo):
            c.currentIndexChanged.connect(self.filters_changed)

        # right: preview + themes
        right = QWidget()
        rl = QVBoxLayout(right)
        self.preview = QLabel("Pick a wallpaper")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(190)
        self.preview.setMaximumHeight(230)
        self.preview.setStyleSheet("background:#00000030;border-radius:8px;")
        rl.addWidget(self.preview)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        rl.addWidget(self.path_label)

        self.tabs = QTabWidget()
        self.known_grid = CardGrid()
        self.known_grid.selected.connect(self.theme_picked)
        sections = [("Popular themes", known_themes())]
        if self.backend.installed_themes():
            sections.append(("Installed on this system", self.backend.installed_themes()))
        self.known_grid.set_sections(sections)
        self.tabs.addTab(self.known_grid, "Known themes")

        match = QWidget()
        ml = QVBoxLayout(match)
        row = QHBoxLayout()
        row.addWidget(QLabel("Style:"))
        self.dark_btn, self.light_btn = QRadioButton("Dark"), QRadioButton("Light")
        self.dark_btn.setChecked(True)
        grp = QButtonGroup(self)
        for rb in (self.dark_btn, self.light_btn):
            grp.addButton(rb)
            rb.toggled.connect(self.rebuild_matches)
            row.addWidget(rb)
        row.addStretch()
        ml.addLayout(row)
        self.match_grid = CardGrid()
        self.match_grid.selected.connect(self.theme_picked)
        ml.addWidget(self.match_grid)
        self.tabs.addTab(match, "Match wallpaper")
        self.tabs.currentChanged.connect(lambda _: self.theme_picked(None))
        rl.addWidget(self.tabs, 1)

        btns = QHBoxLayout()
        self.apply_btn = QPushButton("Apply wallpaper + theme")
        self.apply_btn.clicked.connect(self.apply_all)
        self.wall_btn = QPushButton("Wallpaper only")
        self.wall_btn.clicked.connect(self.apply_wallpaper_only)
        self.revert_btn = QPushButton("Revert colours")
        self.revert_btn.clicked.connect(self.revert)
        btns.addWidget(self.apply_btn)
        btns.addWidget(self.wall_btn)
        btns.addWidget(self.revert_btn)
        rl.addLayout(btns)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([210, 700, 480])

        self.statusBar().showMessage("Choose a wallpaper to see themes for it.")
        self.refresh_folders()
        self.update_buttons()
        self.quitting = False
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.setup_tray()

    # ---- system tray
    def setup_tray(self):
        icon = QIcon(str(ICON_FILE)) if ICON_FILE.exists() else QIcon.fromTheme(DESKTOP_ID)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        open_act = QAction(f"Open {APP_NAME}", menu)
        open_act.triggered.connect(self.bring_to_front)
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.quit_app)
        menu.addAction(open_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self.tray_clicked)
        self.tray.show()

    def tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:       # normal left click: toggle
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.bring_to_front()

    def bring_to_front(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.quitting = True
        QApplication.quit()

    def closeEvent(self, e):
        if self.tray is not None and not self.quitting:               # close button = hide to tray
            e.ignore()
            self.hide()
        else:
            e.accept()

    # ---- config
    def load_config(self):
        try:
            return json.loads(CONFIG.read_text())
        except Exception:
            return {"folders": [str(f) for f in DEFAULT_FOLDERS if f.is_dir()]}

    def save_config(self):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(self.cfg, indent=2))

    # ---- folders
    def refresh_folders(self):
        self.folders.blockSignals(True)
        self.folders.clear()
        self.folders.addItem("All wallpapers")
        for f in self.cfg["folders"]:
            self.folders.addItem(f)
        self.folders.blockSignals(False)
        self.folders.setCurrentRow(0)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a wallpaper folder", str(Path.home()))
        if d and d not in self.cfg["folders"]:
            self.cfg["folders"].append(d)
            self.save_config()
            self.refresh_folders()
            self.folders.setCurrentRow(self.folders.count() - 1)

    def remove_folder(self):
        r = self.folders.currentRow()
        if r > 0:
            del self.cfg["folders"][r - 1]
            self.save_config()
            self.refresh_folders()

    def open_file(self):
        exts = " ".join("*" + e for e in sorted(IMG_EXT))
        f, _ = QFileDialog.getOpenFileName(self, "Open a wallpaper image", str(Path.home() / "Pictures"),
                                           f"Images ({exts})")
        if f:
            self.select_path(f)

    def folder_changed(self, row):
        folders = self.cfg["folders"] if row <= 0 else [self.cfg["folders"][row - 1]]
        self.records = {}
        for folder in folders:
            for path, label in scan_folder(folder):
                if path in self.records:
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                self.records[path] = dict(label=label, mtime=st.st_mtime, fsize=st.st_size, meta=None, pix=None)
        self.refresh_grid()
        for path in self.records:
            self.pool.start(ThumbJob(path, self.signals))

    def on_thumb(self, path, img, meta):
        rec = self.records.get(path)
        if rec is None:
            return
        rec["pix"], rec["meta"] = QPixmap.fromImage(img), meta
        it = self.items.get(path)
        if it is not None:
            it.setIcon(QIcon(rec["pix"]))
            it.setText(f"{rec['label']}\n{meta['size'][0]}×{meta['size'][1]}")
        kind = SORTS[self.sort_combo.currentIndex()][1]
        if kind in ("res", "hue", "light") or COLOUR_FILTERS[self.colour_combo.currentIndex()][1] \
                or SIZE_FILTERS[self.size_combo.currentIndex()][1]:
            self._refresh_timer.start()            # order/filter depends on data that just arrived

    def schedule_refresh(self, *_):
        self._refresh_timer.start()

    def filters_changed(self, *_):
        self.cfg.update(sort=self.sort_combo.currentIndex(), colour=self.colour_combo.currentIndex(),
                        size=self.size_combo.currentIndex())
        self.save_config()
        self.refresh_grid()

    def reset_filters(self):
        self.search.clear()
        self.colour_combo.setCurrentIndex(0)
        self.size_combo.setCurrentIndex(0)

    def refresh_grid(self):
        q = self.search.text().strip().lower()
        colour = COLOUR_FILTERS[self.colour_combo.currentIndex()][0]
        size = SIZE_FILTERS[self.size_combo.currentIndex()][1]
        _label, kind, rev = SORTS[self.sort_combo.currentIndex()]
        waiting = 0
        paths = []
        for path, r in self.records.items():
            if q and q not in r["label"].lower() and q not in path.lower():
                continue
            m = r["meta"]
            if (colour != "Any colour" or size) and m is None:
                waiting += 1
                continue
            if colour != "Any colour" and colour not in m["tags"]:
                continue
            if size:
                w, h = m["size"]
                if size == "ultra" and w < h * 2.2:
                    continue
                if size == "portrait" and h <= w:
                    continue
                if isinstance(size, tuple) and (w < size[0] or h < size[1]):
                    continue
            paths.append(path)

        def key(path):
            r = self.records[path]
            m = r["meta"]
            if kind == "date":
                v = r["mtime"]
            elif kind == "fsize":
                v = r["fsize"]
            elif m is None:
                return (True, 0)                     # unmeasured wallpapers go last
            elif kind == "res":
                v = m["size"][0] * m["size"][1]
            elif kind == "light":
                v = m["L"]
            else:                                    # hue: colourful ones by hue, greys/blacks after
                return (False, m["chroma"] < 0.25, m["hue"] if m["chroma"] >= 0.25 else m["L"])
            return (False, -v if rev else v)
        if kind == "name":
            paths.sort(key=lambda p: self.records[p]["label"].lower(), reverse=rev)
        else:
            paths.sort(key=key)

        keep = self.wallpaper
        self.grid.blockSignals(True)
        self.grid.clear()
        self.items = {}
        for path in paths:
            r = self.records[path]
            m = r["meta"]
            it = QListWidgetItem(r["label"] + (f"\n{m['size'][0]}×{m['size'][1]}" if m else ""))
            it.setData(Qt.ItemDataRole.UserRole, path)
            it.setToolTip(f"{path}\n{r['fsize'] / 1048576:.1f} MB" + (f"\n{', '.join(m['tags'])}" if m else ""))
            it.setSizeHint(QSize(256, 190))
            if r["pix"] is not None:
                it.setIcon(QIcon(r["pix"]))
            self.grid.addItem(it)
            self.items[path] = it
        if keep in self.items:
            self.grid.setCurrentItem(self.items[keep])
        self.grid.blockSignals(False)
        msg = f"{len(paths)} of {len(self.records)} wallpapers"
        if waiting:
            msg += f"  (still reading colours/sizes of {waiting} more…)"
        self.statusBar().showMessage(msg)

    # ---- selection
    def select_path(self, path):
        it = self.items.get(path)
        if it:
            self.grid.setCurrentItem(it)
        else:
            self.wallpaper_chosen(path)

    def wallpaper_picked(self, item, _prev=None):
        if item:
            self.wallpaper_chosen(item.data(Qt.ItemDataRole.UserRole))

    def wallpaper_chosen(self, path):
        self.wallpaper = path
        pm = QPixmap(path)
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(self.preview.width() - 4, self.preview.maximumHeight(),
                                             Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        self.path_label.setText(path)
        self.rebuild_matches()
        self.theme_picked(None)
        self.statusBar().showMessage("Pick a theme (or match the wallpaper), then Apply.")

    def rebuild_matches(self, *_):
        if not self.wallpaper:
            self.match_grid.set_sections([], "Choose a wallpaper first.")
            return
        try:
            if self.wallpaper not in self.fam_cache:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    self.fam_cache[self.wallpaper] = colour_families(self.wallpaper)
                finally:
                    QApplication.restoreOverrideCursor()
            fams = self.fam_cache[self.wallpaper]
            themes = match_themes(fams, dark=self.dark_btn.isChecked())
        except Exception as e:
            self.match_grid.set_sections([], f"Could not read colours from this image: {e}")
            return
        chips = "  ".join(f"<span style='color:{lch_hex(f['L'], f['C'], f['h'])}'>■</span> "
                          f"{colour_name(f)} {f['share'] * 100:.0f}%" for f in fams)
        note = ("Colour families found in this wallpaper: " + chips +
                "<br>Each option pairs two clearly different families.") if themes else \
            "This wallpaper doesn't have enough distinct colours to build contrasting themes."
        self.match_grid.set_sections([(None, themes)], note)

    def theme_picked(self, theme):
        if theme is None:                      # tab or wallpaper changed: drop selection
            self.theme = None
            self.known_grid.clear_selection()
            self.match_grid.clear_selection()
        else:
            self.theme = theme
            other = self.match_grid if self.known_grid.cards and theme in \
                [c.theme for c in self.known_grid.cards] else self.known_grid
            other.clear_selection()
        self.update_buttons()

    def update_buttons(self):
        self.apply_btn.setEnabled(bool(self.wallpaper or self.theme))
        self.wall_btn.setEnabled(bool(self.wallpaper))
        self.apply_btn.setText("Apply wallpaper + theme" if self.theme else "Apply wallpaper")

    # ---- applying
    def do_wallpaper(self):
        self.backend.apply_wallpaper(self.wallpaper)

    def do_theme(self, t):
        self.backend.apply_theme(t)

    def guarded(self, fn, ok):
        try:
            fn()
            self.statusBar().showMessage(ok)
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, str(e))

    def apply_all(self):
        def go():
            if self.wallpaper:
                self.do_wallpaper()
            if self.theme:
                self.do_theme(self.theme)
        what = "Applied wallpaper" + (f" and theme “{self.theme['name']}”" if self.theme else "")
        self.guarded(go, what + ".")

    def apply_wallpaper_only(self):
        self.guarded(self.do_wallpaper, "Wallpaper applied.")

    def revert(self):
        try:
            self.statusBar().showMessage(self.backend.restore(self.snapshot))
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, str(e))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--self-test":       # print themes for an image, no GUI
        app = QGuiApplication(sys.argv[:1])
        fams = colour_families(sys.argv[2])
        for f in fams:
            print(f"family {colour_name(f):7s} share {f['share'] * 100:5.1f}%  L{f['L']:.0f} C{f['C']:.0f} h{f['h']:.0f}")
        for dark in (True, False):
            for t in match_themes(fams, dark):
                print(("dark " if dark else "light"), f"{t['name']:20s}", t["bg"], t["bg_alt"], t["fg"], t["accent"])
        return
    QGuiApplication.setDesktopFileName(DESKTOP_ID)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_FILE)) if ICON_FILE.exists() else QIcon.fromTheme(DESKTOP_ID))

    # Only one copy runs: a second launch (shortcut, menu, ...) just shows the running window.
    sock = QLocalSocket()
    sock.connectToServer(DESKTOP_ID)
    if sock.waitForConnected(300):
        if "--tray" not in sys.argv:
            sock.write(b"show")
            sock.waitForBytesWritten(500)
        return
    QLocalServer.removeServer(DESKTOP_ID)
    server = QLocalServer()
    server.listen(DESKTOP_ID)

    app.setQuitOnLastWindowClosed(False)
    w = MainWindow()

    def on_connect():
        conn = server.nextPendingConnection()
        conn.readyRead.connect(w.bring_to_front)
        conn.disconnected.connect(conn.deleteLater)
    server.newConnection.connect(on_connect)

    if w.tray is None or "--tray" not in sys.argv:    # no tray available -> always show the window
        w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
