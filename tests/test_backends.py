"""Tests for the desktop backends and colour matching.  Run:  python3 -m unittest discover -s tests -v

The GNOME backend is tested against a fake `gsettings` (state kept in a JSON file), so nothing on the
real desktop is touched and the tests also run on KDE machines.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402
import toms_themes as T  # noqa: E402

FAKE_GSETTINGS = """#!/usr/bin/env python3
import json, os, sys
state_file = os.environ["FAKE_GS_STATE"]
state = json.load(open(state_file)) if os.path.exists(state_file) else {}
cmd, schema, key = sys.argv[1], sys.argv[2], sys.argv[3]
k = schema + " " + key
if cmd == "get":
    if k not in state:
        sys.exit(1)
    print(state[k])
else:
    state[k] = sys.argv[4]
    json.dump(state, open(state_file, "w"))
"""


def theme(name="Test", dark=True):
    return T.make_theme(name, dark, "#1e1e2e", "#313244", "#cdd6f4", "#a6adc8", "#3a8bdc",
                        "#f38ba8", "#a6e3a1", "#f9e2af")


class GnomeBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / "bin").mkdir()
        gs = base / "bin" / "gsettings"
        gs.write_text(FAKE_GSETTINGS)
        gs.chmod(gs.stat().st_mode | stat.S_IEXEC)
        self.state = base / "state.json"
        self._env = dict(os.environ)
        os.environ["PATH"] = f"{base / 'bin'}:{os.environ['PATH']}"
        os.environ["FAKE_GS_STATE"] = str(self.state)
        self.cfg = base / "config"
        self.backend = T.GnomeBackend(config_home=self.cfg)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def gs(self):
        return json.loads(self.state.read_text()) if self.state.exists() else {}

    def test_wallpaper_uses_encoded_uri_for_light_and_dark(self):
        img = Path(self.tmp.name) / "my wallpaper.png"
        img.write_bytes(b"x")
        self.backend.apply_wallpaper(str(img))
        uri = f"'{img.resolve().as_uri()}'"
        self.assertIn("%20", uri)
        self.assertEqual(self.gs()["org.gnome.desktop.background picture-uri"], uri)
        self.assertEqual(self.gs()["org.gnome.desktop.background picture-uri-dark"], uri)

    def test_theme_writes_gtk_css_and_sets_dark_and_accent(self):
        self.backend.apply_theme(theme(dark=True))
        for d in ("gtk-4.0", "gtk-3.0"):
            css = (self.cfg / d / "gtk.css").read_text()
            self.assertIn("@define-color accent_bg_color #3a8bdc;", css)
            self.assertIn("@define-color window_bg_color #1e1e2e;", css)
            self.assertIn("@define-color theme_selected_bg_color #3a8bdc;", css)
        self.assertEqual(self.gs()["org.gnome.desktop.interface color-scheme"], "'prefer-dark'")
        self.assertEqual(self.gs()["org.gnome.desktop.interface accent-color"], "'blue'")

    def test_light_theme_sets_default_colour_scheme(self):
        self.backend.apply_theme(theme(dark=False))
        self.assertEqual(self.gs()["org.gnome.desktop.interface color-scheme"], "'default'")

    def test_applying_twice_replaces_block_and_keeps_users_own_css(self):
        mine = self.cfg / "gtk-4.0" / "gtk.css"
        mine.parent.mkdir(parents=True)
        mine.write_text("/* my own tweak */\nheaderbar { min-height: 30px; }\n")
        self.backend.apply_theme(theme("First"))
        self.backend.apply_theme(theme("Second"))
        css = mine.read_text()
        self.assertEqual(css.count(T.GTK_START), 1)
        self.assertIn("Second", css)
        self.assertNotIn("First", css)
        self.assertIn("my own tweak", css)

    def test_restore_removes_our_block_and_resets_settings(self):
        self.state.write_text(json.dumps({"org.gnome.desktop.interface color-scheme": "'default'",
                                          "org.gnome.desktop.interface accent-color": "'orange'"}))
        snap = self.backend.snapshot()
        mine = self.cfg / "gtk-4.0" / "gtk.css"
        mine.parent.mkdir(parents=True)
        mine.write_text("a { color: red; }\n")
        self.backend.apply_theme(theme())
        self.backend.restore(snap)
        self.assertEqual(mine.read_text().strip(), "a { color: red; }")
        self.assertFalse((self.cfg / "gtk-3.0" / "gtk.css").exists())   # we created it, so it is removed
        self.assertEqual(self.gs()["org.gnome.desktop.interface color-scheme"], "'default'")
        self.assertEqual(self.gs()["org.gnome.desktop.interface accent-color"], "'orange'")

    def test_missing_accent_key_on_older_gnome_is_not_an_error(self):
        # The fake gsettings accepts any key, so simulate an old GNOME where 'set' fails for accent-color.
        real = self.backend._set

        def picky(schema, key, value, required=False):
            if key == "accent-color":
                if required:
                    raise RuntimeError("no such key")
                return
            real(schema, key, value, required)
        self.backend._set = picky
        self.backend.apply_theme(theme())          # must not raise
        self.assertNotIn("org.gnome.desktop.interface accent-color", self.gs())


class DesktopDetectionTests(unittest.TestCase):
    def check(self, xdg, session, expected):
        old = dict(os.environ)
        try:
            os.environ["XDG_CURRENT_DESKTOP"], os.environ["DESKTOP_SESSION"] = xdg, session
            self.assertEqual(T.detect_desktop(), expected)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_detection(self):
        self.check("KDE", "plasma", "kde")
        self.check("ubuntu:GNOME", "ubuntu", "gnome")
        self.check("GNOME", "gnome", "gnome")
        self.check("XFCE", "xfce", "other")

    def test_unsupported_backend_explains_itself(self):
        with self.assertRaises(RuntimeError):
            T.UnsupportedBackend().apply_wallpaper("/x.png")


class ThemeMathTests(unittest.TestCase):
    def fam(self, hexcol, share):
        L, a, b = T.rgb_to_lab(np.array([T.hex_rgb(hexcol)], float))[0]
        C = float(np.hypot(a, b))
        return dict(L=float(L), C=C, h=float(np.degrees(np.arctan2(b, a)) % 360), share=share,
                    lab=np.array([L, a, b]))

    def test_matched_themes_pair_clearly_different_colours(self):
        fams = [self.fam("#1e963f", .25), self.fam("#235ac8", .25), self.fam("#787c80", .25), self.fam("#0e0e10", .25)]
        names = {t["name"] for t in T.match_themes(fams, True)}
        for expected in ("Green · Black", "Blue · Black", "Green · Grey", "Blue · Grey", "Grey · Black"):
            self.assertIn(expected, names)
        self.assertFalse([n for n in names if n.split(" · ")[0] == n.split(" · ")[1]])

    def test_accent_text_is_readable(self):
        for t in T.match_themes([self.fam("#1e963f", .5), self.fam("#0e0e10", .5)], True) + T.known_themes():
            self.assertGreaterEqual(T.contrast(t["accent"], t["accent_fg"]), 4.5, t["name"])
            self.assertGreaterEqual(T.contrast(t["bg"], t["fg"]), 4.5, t["name"])

    def test_kde_scheme_has_all_sections(self):
        text = T.scheme_text(theme(), "TomsThemesTest")
        for sec in ("Colors:View", "Colors:Window", "Colors:Button", "Colors:Selection", "Colors:Tooltip",
                    "ColorEffects:Disabled", "General", "WM"):
            self.assertIn(f"[{sec}]", text)


if __name__ == "__main__":
    unittest.main()
