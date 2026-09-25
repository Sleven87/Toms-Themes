#!/usr/bin/env bash
# Tom's Themes installer.
# Works on KDE Plasma and GNOME/Ubuntu, on Arch/CachyOS, Ubuntu/Debian/Mint/Pop and Fedora.
# Safe to run again: it just refreshes the installed copy.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/toms-themes"
APP="$APP_DIR/toms_themes.py"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
AUTOSTART_DIR="$HOME/.config/autostart"
INSTALL_DEPS=1; AUTOSTART=1; SHORTCUT=1; START=1

usage() {
  cat <<USAGE
Usage: ./install.sh [options]
  --no-deps        don't try to install PyQt6/numpy (you must have them already)
  --no-autostart   don't start the tray icon at login
  --no-shortcut    don't create the Super+Shift+T shortcut
  --no-start       don't launch the tray icon at the end
USAGE
}
for a in "$@"; do
  case "$a" in
    --no-deps) INSTALL_DEPS=0 ;;
    --no-autostart) AUTOSTART=0 ;;
    --no-shortcut) SHORTCUT=0 ;;
    --no-start) START=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $a"; usage; exit 1 ;;
  esac
done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*"; exit 1; }

command -v python3 >/dev/null || die "python3 is required."

# ---- which distro / desktop ---------------------------------------------------------------
ID_STR=""
[ -r /etc/os-release ] && ID_STR="$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}")"
case " $ID_STR " in
  *arch*|*cachyos*|*manjaro*|*endeavouros*) PM=pacman ;;
  *ubuntu*|*debian*|*mint*|*pop*)           PM=apt ;;
  *fedora*|*rhel*)                          PM=dnf ;;
  *)                                        PM=unknown ;;
esac
DE="$(printf '%s:%s' "${XDG_CURRENT_DESKTOP:-}" "${DESKTOP_SESSION:-}" | tr 'A-Z' 'a-z')"
case "$DE" in
  *kde*|*plasma*)          DESK=kde ;;
  *gnome*|*ubuntu*|*unity*) DESK=gnome ;;
  *)                       DESK=other ;;
esac
say "Package manager: $PM   Desktop: $DESK"

# ---- dependencies -------------------------------------------------------------------------
have_deps() { python3 -c 'import PyQt6.QtWidgets, numpy' 2>/dev/null; }
if ! have_deps; then
  if [ "$INSTALL_DEPS" = 1 ]; then
    say "Installing PyQt6 and numpy (needs sudo)…"
    case "$PM" in
      pacman) sudo pacman -S --needed --noconfirm python-pyqt6 python-numpy ;;
      apt)    sudo apt-get update && sudo apt-get install -y python3-pyqt6 python3-numpy ;;
      dnf)    sudo dnf install -y python3-pyqt6 python3-numpy ;;
      *)      die "Unknown distro: install the Python packages PyQt6 and numpy yourself, then re-run with --no-deps." ;;
    esac
  fi
  have_deps || die "PyQt6 and numpy are still missing. Install them (Arch: python-pyqt6 python-numpy; Ubuntu: python3-pyqt6 python3-numpy) and re-run."
fi
if [ "$INSTALL_DEPS" = 1 ]; then       # optional extras: wallpaper formats like webp/avif, Wayland support
  case "$PM" in
    apt)    sudo apt-get install -y qt6-image-formats-plugins qt6-wayland >/dev/null 2>&1 || warn "Optional Qt plugins not installed (webp/avif wallpapers may not show)." ;;
    pacman) sudo pacman -S --needed --noconfirm qt6-imageformats qt6-wayland >/dev/null 2>&1 || warn "Optional Qt plugins not installed." ;;
    dnf)    sudo dnf install -y qt6-qtimageformats qt6-qtwayland >/dev/null 2>&1 || warn "Optional Qt plugins not installed." ;;
  esac
fi
say "Python deps OK ($(python3 -c 'import PyQt6.QtCore as c; print("Qt", c.QT_VERSION_STR)'))"

# ---- desktop tools the app calls -----------------------------------------------------------
case "$DESK" in
  kde)   for t in plasma-apply-colorscheme plasma-apply-wallpaperimage kreadconfig6; do
           command -v "$t" >/dev/null || warn "KDE tool '$t' not found: applying themes may fail (needs Plasma 6)."; done ;;
  gnome) command -v gsettings >/dev/null || warn "'gsettings' not found: applying wallpapers/themes will fail." ;;
  other) warn "Desktop '${XDG_CURRENT_DESKTOP:-unknown}' isn't supported for applying themes (KDE Plasma and GNOME/Ubuntu are). The app will still open." ;;
esac

# ---- install files -------------------------------------------------------------------------
say "Installing to $APP_DIR"
mkdir -p "$APP_DIR" "$APPS_DIR" "$ICON_DIR"
cp "$HERE/toms_themes.py" "$APP"
cp "$HERE/assets/toms-themes.svg" "$ICON_DIR/toms-themes.svg"
sed "s|@APP@|$APP|g" "$HERE/packaging/toms-themes.desktop" > "$APPS_DIR/toms-themes.desktop"
if [ "$AUTOSTART" = 1 ]; then
  mkdir -p "$AUTOSTART_DIR"
  sed "s|@APP@|$APP|g" "$HERE/packaging/toms-themes-tray.desktop" > "$AUTOSTART_DIR/toms-themes.desktop"
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache  >/dev/null && gtk-update-icon-cache -q -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true

# ---- Super+Shift+T shortcut ----------------------------------------------------------------
if [ "$SHORTCUT" = 1 ]; then
  case "$DESK" in
    kde)
      if command -v gdbus >/dev/null; then
        ID="['toms-themes.desktop','_launch','toms-themes.desktop',\"Tom's Themes\"]"
        gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
          --method org.kde.KGlobalAccel.doRegister "$ID" >/dev/null 2>&1 || true
        gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
          --method org.kde.KGlobalAccel.setShortcut "$ID" "[301989972]" 4 >/dev/null 2>&1 \
          && say "Shortcut Super+Shift+T set (KDE)" || warn "Could not set the KDE shortcut; set it in System Settings > Shortcuts."
      fi ;;
    gnome)
      python3 - "$APP" <<'PY' && say "Shortcut Super+Shift+T set (GNOME)" || warn "Could not set the GNOME shortcut; add it in Settings > Keyboard."
import ast, subprocess, sys
app = sys.argv[1]
BASE = "org.gnome.settings-daemon.plugins.media-keys"
PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/toms-themes/"
raw = subprocess.check_output(["gsettings", "get", BASE, "custom-keybindings"], text=True).strip()
items = ast.literal_eval(raw[4:] if raw.startswith("@as ") else raw)
if PATH not in items:
    items.append(PATH)
subprocess.check_call(["gsettings", "set", BASE, "custom-keybindings", str(items)])
schema = f"{BASE}.custom-keybinding:{PATH}"
subprocess.check_call(["gsettings", "set", schema, "name", "Tom’s Themes"])
subprocess.check_call(["gsettings", "set", schema, "command", f"python3 {app}"])
subprocess.check_call(["gsettings", "set", schema, "binding", "<Super><Shift>t"])
PY
      ;;
  esac
fi

# ---- start the tray icon now ---------------------------------------------------------------
if [ "$START" = 1 ] && [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
  python3 - <<'PY' || true
import os, signal
for pid in filter(str.isdigit, os.listdir("/proc")):          # stop an older copy so the new code runs
    try:
        argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
    except OSError:
        continue
    if argv and argv[0].endswith(b"python3") and any(a.endswith(b"/toms-themes/toms_themes.py") for a in argv[1:]) \
            and int(pid) != os.getpid():
        os.kill(int(pid), signal.SIGTERM)
PY
  sleep 1
  nohup setsid python3 "$APP" --tray >/dev/null 2>&1 &
  say "Started. Look for the Tom's Themes icon in your system tray (or press Super+Shift+T)."
fi

say "Done."
if [ "$DESK" = gnome ]; then
  echo "    GNOME/Ubuntu note: the tray icon needs the AppIndicator extension (Ubuntu has it on by default)."
fi
