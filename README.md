# Tom's Themes

A small desktop app to **browse wallpapers, pick a colour theme, and apply both in one click**.

- Browse wallpapers from any folders you choose, with search, sorting (name, date, resolution, colour, brightness, file size) and filters (colour, size, ultrawide, portrait).
- **Known themes**: Catppuccin, Nord, Dracula, Gruvbox, Tokyo Night, Rosé Pine, Solarized, One Dark, Everforest, Kanagawa, and (on KDE) every colour scheme already installed.
- **Match wallpaper**: pulls the distinct colour families out of the picture and offers contrasting pairs such as *Green · Black*, *Blue · Grey*, *Green · Blue* (never black-on-black). Dark and Light variants; text is always kept readable.
- Lives in the **system tray** (left click toggles the window, close button hides it). Also in the app menu, and on **Super+Shift+T**.
- **Revert colours** puts back whatever you had when you opened the app.

## Supported systems

| Desktop | Distros tested / intended | What gets applied |
|---|---|---|
| **KDE Plasma 6** | Arch / CachyOS (built and tested here), Kubuntu, Fedora KDE | Wallpaper + a full KDE colour scheme (window, button, selection, tooltip colours, accent). Panels follow the scheme. |
| **GNOME** (incl. stock **Ubuntu**) | Ubuntu 22.04+ (written for it; see "GNOME status" below) | Wallpaper (light and dark), dark/light preference, accent colour (GNOME 47+), and colours for GTK4/libadwaita and GTK3 apps via `~/.config/gtk-{3,4}.0/gtk.css` |
| Anything else | | The app opens but says it can't apply themes. Wallpaper browsing/preview still works. |

The app picks the backend automatically from `$XDG_CURRENT_DESKTOP`.

### GNOME status (please read)
The GNOME backend is covered by automated tests using a fake `gsettings` (run on the KDE machine where the app was built) but has **not yet been run on a real GNOME desktop**. Known limits there:
- Colours apply to GTK4/libadwaita and Adwaita-based GTK3 apps. **GNOME Shell itself (the top bar, the Ubuntu dock) is not recoloured**; that needs a Shell theme + the "User Themes" extension.
- Already-open apps need to be restarted to pick up new colours.
- Ubuntu's Yaru GTK3 theme honours most, but not all, of the named colours.
- The accent-colour setting exists on GNOME 47+ only (Ubuntu 24.10+); on older versions it is skipped silently and the dark/light + `gtk.css` colours still apply.
- The tray icon needs the AppIndicator extension (enabled by default on Ubuntu).

## Install

```bash
git clone https://github.com/Sleven87/Toms-Themes
cd Toms-Themes
./install.sh
```

`install.sh` is safe to re-run (it refreshes the installed copy). Options: `--no-deps`, `--no-autostart`, `--no-shortcut`, `--no-start`.

It will:
1. Detect the package manager and desktop.
2. Install the Python packages if missing (asks for your sudo password):
   - Arch/CachyOS: `python-pyqt6 python-numpy` (+ optional `qt6-imageformats qt6-wayland`)
   - Ubuntu/Debian: `python3-pyqt6 python3-numpy` (+ optional `qt6-image-formats-plugins qt6-wayland`)
   - Fedora: `python3-pyqt6 python3-numpy`
3. Copy the app to `~/.local/share/toms-themes/`, the icon to `~/.local/share/icons/hicolor/scalable/apps/`, and create the menu entry (`~/.local/share/applications/toms-themes.desktop`).
4. Add a login autostart entry (`~/.config/autostart/toms-themes.desktop`, runs `--tray`) so the tray icon is always there.
5. Register **Super+Shift+T** (KDE: kglobalaccel over D-Bus. GNOME: a custom keybinding in gsettings).
6. Start the tray icon.

Requirements: Python 3.10+, PyQt6, numpy. No sklearn or Pillow needed.

Uninstall: `./uninstall.sh` (add `--purge` to also delete saved settings).

## Use

1. Click the tray icon (or Super+Shift+T). Pick a wallpaper on the left.
2. Choose **Known themes** or **Match wallpaper**, click a theme card.
3. **Apply wallpaper + theme** (or **Wallpaper only**). **Revert colours** undoes the colour change.

Settings (wallpaper folders, last sort/filter) are in `~/.config/toms-themes/config.json`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
Covers desktop detection, the GNOME backend (fake `gsettings`, temp config dir), the KDE scheme writer, colour matching and text-contrast rules. It never touches your real settings.

Handy without the GUI: `python3 toms_themes.py --self-test path/to/image.jpg` prints the colour families and the matched themes for an image.

## Layout

```
toms_themes.py          the whole app (single file)
install.sh / uninstall.sh
assets/toms-themes.svg  icon
packaging/              .desktop templates (@APP@ is replaced by the installer)
tests/test_backends.py
CLAUDE.md               instructions for Claude Code (read automatically)
```

---

# Notes for Claude Code (installing this on another machine)

If you're Claude Code and the user asked you to install or fix this app, follow this section. `CLAUDE.md` points here.

## Procedure
1. `cat /etc/os-release; echo $XDG_CURRENT_DESKTOP $XDG_SESSION_TYPE; python3 --version` to learn the distro and desktop.
2. Run `./install.sh` **in a terminal the user can type a sudo password into** (or, if you can't, tell the user to run `! ./install.sh`, or run it with `--no-deps` after installing the packages listed above yourself).
3. Run the tests: `python3 -m unittest discover -s tests -v`. They should all pass on any Linux with PyQt6.
4. Verify the install (see checklist). Then have the user open the app and try Apply with a known theme, then **Revert colours**.
5. Report honestly what you could and could not verify. On GNOME, say that visual results were not checked unless you looked.

## Verification checklist
- `python3 -c "import PyQt6.QtWidgets, numpy; print('ok')"`
- `ls ~/.local/share/toms-themes/toms_themes.py ~/.local/share/applications/toms-themes.desktop`
- Tray icon registered: `qdbus6 org.kde.StatusNotifierWatcher /StatusNotifierWatcher org.freedesktop.DBus.Properties.Get org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems` (KDE) or look at the top bar (GNOME).
- KDE only: `plasma-apply-colorscheme --list-schemes` runs; applying then reverting a scheme changes `kreadconfig6 --file kdeglobals --group General --key ColorScheme`.
- GNOME only: `gsettings get org.gnome.desktop.interface color-scheme` changes after Apply; `~/.config/gtk-4.0/gtk.css` contains a `/* >>> Tom's Themes >>> */` block; Revert removes the block.
- A screenshot helps: `spectacle -b -n -f -o file.png` (KDE) or `gnome-screenshot -f file.png` (GNOME).

## How it was built and what it depends on (learned on the original machine)
Original machine: **CachyOS (Arch), KDE Plasma 6, Wayland**, Python 3.14, PyQt6 6.11, numpy 2.5.

- **KDE backend** shells out to `plasma-apply-wallpaperimage <file>` and `plasma-apply-colorscheme <id>`. Generated schemes are written to `~/.local/share/color-schemes/TomsThemes*.colors` (full sections: View, Window, Button, Tooltip, Complementary, Header, Selection, ColorEffects, General, WM, KDE). Panels and widgets follow the scheme. The current scheme is read with `kreadconfig6` for the Revert button.
- **Do not pass `--accent-color` to `plasma-apply-colorscheme` together with a scheme name.** With that flag it applies *only* the accent and silently ignores the scheme. The schemes already carry their own accent.
- **GNOME backend** uses `gsettings` (`org.gnome.desktop.background picture-uri` and `picture-uri-dark` with a `file://` URI, `org.gnome.desktop.interface color-scheme` and `accent-color`) plus an owned, marker-delimited block in `~/.config/gtk-4.0/gtk.css` and `~/.config/gtk-3.0/gtk.css` made of `@define-color` overrides. Anything else the user has in those files is preserved on apply and restore.
- **Wallpaper colour matching** (numpy only): k-means in CIE Lab on a 160px thumbnail, merge clusters closer than ΔE 22, keep families with enough share (vivid ones can be small), then build background+accent pairs with ΔE ≥ 38. Neutral (low chroma) families get no hue tint. Dark themes use the darker family as background; a grey/black background with a coloured accent is always allowed. Duplicate palettes are dropped.
- **Images** load through `QImageReader` (not PIL) so `.avif`/`.webp`/`.jxl` work when Qt's image plugins are installed.
- **Tray**: `QSystemTrayIcon` (StatusNotifierItem). Close hides to tray. **Single instance** via a `QLocalServer` named `toms-themes`; a second launch tells the running copy to show itself. `--tray` starts hidden.
- **Global shortcut on KDE**: register the service action first, then set the key. `gdbus ... org.kde.KGlobalAccel.doRegister "['toms-themes.desktop','_launch','toms-themes.desktop',\"Tom's Themes\"]"` then `setShortcut` with the key code `[301989972]` (Meta+Shift+T) and flags `4`. The action name `_launch` runs the desktop file. Test it with `qdbus6 org.kde.kglobalaccel /component/toms_themes_desktop org.kde.kglobalaccel.Component.invokeShortcut _launch`.
- **Wayland**: the app sets its desktop file name to `toms-themes` so the taskbar/tray match `toms-themes.desktop`.

## Gotchas
- When killing a running copy, don't `pkill -f toms_themes.py` from a shell whose own command line contains that text; it can kill your own shell. `install.sh` matches `/proc/<pid>/cmdline` exactly instead.
- `.desktop` `Exec` paths are generated by the installer (`@APP@` placeholder); never hard-code `/home/<user>`.
- The user is in Australia and wants dates as **dd/MM/yyyy**. The app itself shows no dates, but keep this in mind for any output you write.
- It's fine to open a PR or edit the app for the user's other machines' quirks, but keep the KDE and GNOME behaviour covered by `tests/`.

## Updating an existing install
```bash
cd Toms-Themes && git pull && ./install.sh
```
`install.sh` stops the running tray copy and starts the new one.
