#!/usr/bin/env bash
# Removes Tom's Themes. Add --purge to also delete its saved settings (~/.config/toms-themes).
set -uo pipefail
APP_DIR="$HOME/.local/share/toms-themes"
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

python3 - <<'PY' || true                     # stop running copies
import os, signal
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
    except OSError:
        continue
    if argv and argv[0].endswith(b"python3") and any(a.endswith(b"/toms-themes/toms_themes.py") for a in argv[1:]):
        os.kill(int(pid), signal.SIGTERM)
PY

# Take our colours back out of the GTK css (GNOME) but keep anything else the user had in those files.
python3 - <<'PY' || true
import re
from pathlib import Path
rx = re.compile(re.escape("/* >>> Tom's Themes >>> */") + r".*?" + re.escape("/* <<< Tom's Themes <<< */") + r"\n?", re.S)
for d in ("gtk-4.0", "gtk-3.0"):
    f = Path.home() / ".config" / d / "gtk.css"
    if f.exists():
        rest = rx.sub("", f.read_text(errors="replace")).strip()
        f.write_text(rest + "\n") if rest else f.unlink()
PY

rm -rf "$APP_DIR"
rm -f "$HOME/.local/share/applications/toms-themes.desktop" \
      "$HOME/.config/autostart/toms-themes.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/toms-themes.svg" \
      "$HOME"/.local/share/color-schemes/TomsThemes*.colors
command -v gdbus >/dev/null && gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
  --method org.kde.KGlobalAccel.unregister "toms-themes.desktop" "_launch" >/dev/null 2>&1
command -v gsettings >/dev/null && python3 - <<'PY' 2>/dev/null
import ast, subprocess
BASE = "org.gnome.settings-daemon.plugins.media-keys"
PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/toms-themes/"
raw = subprocess.check_output(["gsettings", "get", BASE, "custom-keybindings"], text=True).strip()
items = [p for p in ast.literal_eval(raw[4:] if raw.startswith("@as ") else raw) if p != PATH]
subprocess.check_call(["gsettings", "set", BASE, "custom-keybindings", str(items)])
PY
[ "${1:-}" = "--purge" ] && rm -rf "$HOME/.config/toms-themes" && say "Removed saved settings."
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
say "Tom's Themes removed. (Your wallpaper and the last applied colour scheme are left as they are.)"
