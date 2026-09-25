# Tom's Themes: instructions for Claude Code

This repo is a wallpaper browser and colour-theme app for **KDE Plasma** and **GNOME/Ubuntu** (`toms_themes.py`, single file, PyQt6 + numpy).

**If the user asks you to install, set up, or fix it on this machine, read `README.md` first**, in particular the section *"Notes for Claude Code"*. It has the procedure, a verification checklist, and the gotchas learned when it was built.

Short version:
1. Identify the distro and desktop (`cat /etc/os-release`, `echo $XDG_CURRENT_DESKTOP`).
2. Run `./install.sh` from a terminal where the user can enter their sudo password (or install `python3-pyqt6 python3-numpy` on Ubuntu / `python-pyqt6 python-numpy` on Arch yourself, then `./install.sh --no-deps`).
3. Run `python3 -m unittest discover -s tests -v` and check the list in the README.
4. Report honestly what you verified. The GNOME backend has only been tested against a fake `gsettings`, not on a real GNOME desktop.

Rules when editing: keep KDE and GNOME both working and covered by `tests/`; never hard-code `/home/<user>` paths; dates shown to the user are dd/MM/yyyy (the user is in Australia).
