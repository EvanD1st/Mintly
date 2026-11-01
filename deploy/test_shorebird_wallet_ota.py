"""Regression checks for the asset exception used by the wallet OTA rollout."""
import importlib.util
import io
import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
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
    release = {'app_id': '11111111-2222-3333-4444-555555555555', 'release_id': 42,
               'release_version': '1.1.4+7', 'dry_run': True}

    def test_dry_run_records_the_exact_cli_selected_release(self):
        output = SimpleNamespace(stdout=json.dumps({'status': 'success', 'data': self.release}))
        with patch.object(ota.subprocess, 'run', return_value=output) as run:
            self.assertEqual(ota.dry_run(['shorebird', '--json', 'patch', 'android'], {}, '1.1.4+7'), self.release)
            self.assertEqual(run.call_args.args[0][-2:], ['--dry-run', '--allow-asset-diffs'])
            self.assertEqual(run.call_args.kwargs['stdout'], ota.subprocess.PIPE)

    def test_dry_run_rejects_an_unconfirmed_or_different_release(self):
        for changes in ({'dry_run': False}, {'release_version': '1.1.3+6'},
                        {'release_id': True}, {'app_id': '../../different-app'}):
            with self.subTest(changes=changes):
                output = SimpleNamespace(stdout=json.dumps({'status': 'success', 'data': {**self.release, **changes}}))
                with patch.object(ota.subprocess, 'run', return_value=output):
                    with self.assertRaisesRegex(ValueError, 'release identity'):
                        ota.dry_run(['shorebird'], {}, '1.1.4+7')

    def original_bundle(self, metadata_changes=None, body=None, files=None, duplicate=False):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, data in (files or {ota.NOTICES: b'original notices'}).items():
                archive.writestr(name, data)
        original = buffer.getvalue()
        artifact = {'id': 100, 'release_id': 42, 'arch': 'aab', 'platform': 'android',
                    'size': len(original), 'hash': hashlib.sha256(original).hexdigest(),
                    'url': 'https://artifacts.example/original?signature=disposable',
                    **(metadata_changes or {})}
        metadata = SimpleNamespace(stdout=json.dumps({'artifacts': [artifact] * (2 if duplicate else 1)}))
        with tempfile.TemporaryDirectory() as scratch:
            with patch.object(ota.subprocess, 'run', return_value=metadata) as run, \
                    patch.object(ota, 'urlopen', return_value=io.BytesIO(original if body is None else body)) as download:
                installed, evidence = ota.release_bundle(self.release, scratch)
                self.assertEqual(installed.read_bytes(), original)
                self.assertEqual(run.call_args.args[0], ['shorebird', 'api', 'GET',
                    '/apps/11111111-2222-3333-4444-555555555555/releases/42/artifacts?arch=aab&platform=android'])
                download.assert_called_once_with(artifact['url'], timeout=60)
                self.assertNotIn('url', evidence)
                self.assertNotIn('signature', json.dumps(evidence))
                return evidence

    def test_original_bundle_is_verified_independently_of_cli_cache_layout(self):
        evidence = self.original_bundle()
        self.assertEqual(evidence['release_id'], 42)
        self.assertEqual(evidence['artifact_id'], 100)
        self.assertEqual(len(evidence['artifact_sha256']), 64)

    def test_original_bundle_rejects_other_release_platform_arch_or_bad_hash(self):
        for changes in ({'release_id': 43}, {'arch': 'arm64'}, {'platform': 'ios'},
                        {'hash': 'invalid'}, {'id': -1}, {'size': 0}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, 'metadata is invalid'):
                    self.original_bundle(metadata_changes=changes)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.original_bundle(duplicate=True)

    def test_original_bundle_rejects_insecure_download_and_corrupt_or_incomplete_bytes(self):
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            self.original_bundle(metadata_changes={'url': 'http://artifacts.example/original'})
        with self.assertRaisesRegex(ValueError, 'SHA256 or size'):
            self.original_bundle(metadata_changes={'hash': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'SHA256 or size'):
            self.original_bundle(body=b'partial')
        with self.assertRaisesRegex(ValueError, 'exceeds its recorded size'):
            self.original_bundle(metadata_changes={'size': 1})
        with self.assertRaisesRegex(ValueError, 'not an Android app bundle'):
            self.original_bundle(files={'other.txt': b'not a bundle'})

    def test_original_bundle_failure_prevents_any_publish_command(self):
        with patch.object(ota, 'dry_run', return_value=self.release), \
                patch.object(ota, 'release_bundle', side_effect=ValueError('invalid original')), \
                patch.object(ota.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'invalid original'):
                ota.patch_release('1.1.4+7', 'stable', False)
            run.assert_not_called()

    def test_launcher_rebuild_cannot_change_the_selected_release_before_audit(self):
        with patch.object(ota, 'installed_native_sources', return_value=nullcontext()), \
                patch.object(ota, 'installed_plugin_graph', return_value=nullcontext()), \
                patch.object(ota, 'installed_launcher_icons', return_value=nullcontext(True)), \
                patch.object(ota, 'dry_run', side_effect=[self.release, {**self.release, 'release_id': 43}]), \
                patch.object(ota, 'release_bundle', return_value=(Path('original.aab'), {})), \
                patch.object(ota, 'audit') as audit, patch.object(ota.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Release identity changed'):
                ota.patch_release('1.0.0+1', 'stable', False)
            audit.assert_not_called()
            run.assert_not_called()

    def test_every_installer_gets_its_tested_icon_variant_without_native_override(self):
        expected = {
            '1.1.4+7': ['--dart-define=MINTLY_RELEASE_5_ICONS=true'],
            '1.1.3+6': ['--dart-define=MINTLY_RELEASE_5_ICONS=true'],
            '1.1.2+5': ['--dart-define=MINTLY_RELEASE_5_ICONS=true'],
            '1.1.1+4': [], '1.1.0+3': [],
            '1.0.1+2': ['--dart-define=MINTLY_LEGACY_ICONS=true'],
            '1.0.0+1': ['--dart-define=MINTLY_LEGACY_ICONS=true'],
        }
        for version, defines in expected.items():
            with self.subTest(version=version):
                self.assertEqual(ota.patch_command(version, 'stable'),
                    ['shorebird', '--json', 'patch', 'android', '--release-version',
                     version, '--track', 'stable', *defines])

    def test_each_older_installer_restores_native_sources_even_after_failure(self):
        for version, baseline in ota.NATIVE_BASELINES.items():
            with self.subTest(version=version), patch.object(ota.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'build failed'):
                    with ota.installed_native_sources(version):
                        raise RuntimeError('build failed')
                self.assertEqual(run.call_args_list[0].args[0],
                    ['git', 'fetch', '--depth=1', 'origin', baseline])
                self.assertEqual(run.call_args_list[1].args[0],
                    ['git', 'restore', '--source='+baseline, '--worktree', '--', 'android'])
                self.assertEqual(run.call_args_list[-1].args[0],
                    ['git', 'restore', '--source=HEAD', '--worktree', '--', 'android'])

    def test_current_installer_uses_current_native_sources(self):
        with patch.object(ota.subprocess, 'run') as run:
            with ota.installed_native_sources('1.1.4+7'):
                pass
            run.assert_not_called()

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

    def test_first_installer_keeps_its_icons_and_restores_checkout_after_failure(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as scratch:
            os.chdir(scratch)
            try:
                densities = ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")
                for density in densities:
                    path = Path(f"android/app/src/main/res/mipmap-{density}/ic_launcher.png")
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b"current icon")
                with zipfile.ZipFile("release.aab", "w") as archive:
                    for density in densities:
                        archive.writestr(f"base/res/mipmap-{density}-v4/ic_launcher.png", b"installed icon")
                with self.assertRaisesRegex(ValueError, "build failed"):
                    with ota.installed_launcher_icons("1.0.0+1", "release.aab") as preserved:
                        self.assertTrue(preserved)
                        for density in densities:
                            self.assertEqual(Path(f"android/app/src/main/res/mipmap-{density}/ic_launcher.png").read_bytes(), b"installed icon")
                        raise ValueError("build failed")
                for density in densities:
                    self.assertEqual(Path(f"android/app/src/main/res/mipmap-{density}/ic_launcher.png").read_bytes(), b"current icon")
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
