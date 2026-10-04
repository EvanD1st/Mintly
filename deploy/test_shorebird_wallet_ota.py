"""Regression checks for the asset exception used by the wallet OTA rollout."""
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

spec = importlib.util.spec_from_file_location(
    "wallet_ota", Path(__file__).with_name("shorebird-wallet-ota.py")
)
ota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota)


def font(codepoints=(65, 66), width=600):
    names = [".notdef"] + [f"glyph{n}" for n in codepoints]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({n: f"glyph{n}" for n in codepoints})
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((400, 0))
        pen.lineTo((400, 500))
        pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({n: (width, 0) for n in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Audit font", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200,
                    usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    output = io.BytesIO()
    builder.save(output)
    return output.getvalue()


class AssetGuardTests(unittest.TestCase):
    def check_archives(self, changes=None, additions=None, removals=()):
        old = {ota.FONT: font(), ota.NOTICES: b"old notices",
               "base/assets/logo.png": b"logo", "base/lib/arm64-v8a/plugin.so": b"native"}
        new = {**old, ota.NOTICES: b"embedded new notices", **(changes or {}),
               **(additions or {})}
        for name in removals:
            new.pop(name)
        with tempfile.TemporaryDirectory() as scratch:
            paths = [Path(scratch) / "installed.aab", Path(scratch) / "built.aab"]
            for path, files in zip(paths, (old, new)):
                with zipfile.ZipFile(path, "w") as archive:
                    for name, data in files.items():
                        archive.writestr(name, data)
            return ota.audit(*paths)

    def test_embedded_notices_are_the_only_asset_exception(self):
        self.assertEqual(self.check_archives()["changed_assets"], [ota.NOTICES])

    def test_installed_font_can_provide_a_smaller_identical_subset(self):
        self.assertEqual(ota.check_font(font(), font((65,)))["required_glyphs"], 1)

    def test_missing_glyph_blocks_publication(self):
        with self.assertRaisesRegex(ValueError, "lacks glyphs"):
            ota.check_font(font((65,)), font())

    def test_changed_font_metrics_block_publication(self):
        with self.assertRaisesRegex(ValueError, "glyph changed"):
            ota.check_font(font(), font(width=700))

    def test_changed_vertical_geometry_blocks_publication(self):
        from fontTools.ttLib import TTFont
        changed = TTFont(io.BytesIO(font()))
        changed["hhea"].descent = -300
        output = io.BytesIO()
        changed.save(output)
        with self.assertRaisesRegex(ValueError, "geometry changed"):
            ota.check_font(font(), output.getvalue())

    def test_new_or_removed_asset_blocks_publication(self):
        with self.assertRaisesRegex(ValueError, "added or removed"):
            self.check_archives(additions={"base/assets/new.png": b"new"})
        with self.assertRaisesRegex(ValueError, "added or removed"):
            self.check_archives(removals=["base/assets/logo.png"])

    def test_changed_image_blocks_publication(self):
        with self.assertRaisesRegex(ValueError, "Unsupported asset"):
            self.check_archives(changes={"base/assets/logo.png": b"changed"})

    def test_changed_native_library_blocks_publication(self):
        with self.assertRaisesRegex(ValueError, "Native library"):
            self.check_archives(changes={"base/lib/arm64-v8a/plugin.so": b"changed"})

    def test_failed_legacy_validation_restores_source_and_dependency_graph(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as scratch:
            os.chdir(scratch)
            try:
                Path("lib/services").mkdir(parents=True)
                Path("pubspec.yaml").write_text("dependencies:\n  url_launcher: ^6.3.2\n", encoding="utf-8")
                Path("pubspec.lock").write_text("original lock", encoding="utf-8")
                Path("lib/services/external_url.dart").write_text("native launcher", encoding="utf-8")
                Path("lib/services/external_url_legacy.dart").write_text("copy link", encoding="utf-8")
                def validation(command, **kwargs):
                    if command[1] == "analyze":
                        raise ota.subprocess.CalledProcessError(1, command)
                    native = "url_launcher" in Path("pubspec.yaml").read_text(encoding="utf-8")
                    Path("pubspec.lock").write_text("original lock" if native else "legacy lock", encoding="utf-8")
                    Path("resolved-plugins.txt").write_text(str(native), encoding="utf-8")
                with patch.object(ota.subprocess, "run", side_effect=validation):
                    with self.assertRaises(ota.subprocess.CalledProcessError):
                        with ota.installed_plugin_graph(True):
                            self.fail("An invalid build must never publish")
                self.assertEqual(Path("lib/services/external_url.dart").read_text(encoding="utf-8"), "native launcher")
                self.assertEqual(Path("pubspec.lock").read_text(encoding="utf-8"), "original lock")
                self.assertEqual(Path("resolved-plugins.txt").read_text(encoding="utf-8"), "True")
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
