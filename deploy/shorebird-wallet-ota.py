"""Audit unchanged installed assets before publishing a wallet Dart patch.

NOTICES.Z can differ because all newly added package notices are embedded in
wallet_licenses.dart. A tree-shaken Material font may shrink only when every
required glyph has identical outlines and metrics in the installed font.
Nothing else is exempted, and Shorebird's native checks remain enabled.
"""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import zipfile

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

NOTICES = "base/assets/flutter_assets/NOTICES.Z"
FONT = "base/assets/flutter_assets/fonts/MaterialIcons-Regular.otf"


@contextmanager
def installed_native_sources(version):
    """Old installers get Dart fallback only; never replace their native secure store."""
    if version not in {'1.1.1+4','1.1.0+3','1.0.1+2','1.0.0+1'}:
        yield
        return
    baseline='6c9c5a83cff9fb35ca0bbef8c4ad2c2fb43ae235'
    subprocess.run(['git','fetch','--depth=1','origin',baseline],check=True)
    try:
        subprocess.run(['git','restore','--source='+baseline,'--worktree','--','android'],check=True)
        yield
    finally:
        subprocess.run(['git','restore','--source=HEAD','--worktree','--','android'],check=True)


def check_font(installed_bytes, built_bytes):
    installed = TTFont(io.BytesIO(installed_bytes))
    built = TTFont(io.BytesIO(built_bytes))
    old_map, new_map = installed.getBestCmap(), built.getBestCmap()
    missing = set(new_map) - set(old_map)
    if missing:
        raise ValueError(f"Installed font lacks glyphs: {sorted(missing)}")
    for tag, fields in (("head", ("unitsPerEm",)),
                        ("hhea", ("ascent", "descent", "lineGap"))):
        # Table checksums and glyph counts change during subsetting; geometry
        # and per-glyph advance widths are the compatibility requirements.
        for field in fields:
            if getattr(installed[tag], field) != getattr(built[tag], field):
                raise ValueError("Font geometry changed")
    old_glyphs, new_glyphs = installed.getGlyphSet(), built.getGlyphSet()
    for codepoint, new_name in new_map.items():
        old_name = old_map[codepoint]
        old_pen = DecomposingRecordingPen(old_glyphs)
        new_pen = DecomposingRecordingPen(new_glyphs)
        old_glyphs[old_name].draw(old_pen)
        new_glyphs[new_name].draw(new_pen)
        if old_pen.value != new_pen.value or (
            installed["hmtx"][old_name] != built["hmtx"][new_name]
        ):
            raise ValueError(f"Font glyph changed: {codepoint}")
    return {"installed_glyphs": len(old_map), "required_glyphs": len(new_map)}


def audit(installed_path, built_path):
    with zipfile.ZipFile(installed_path) as old, zipfile.ZipFile(built_path) as new:
        def assets(archive):
            return {n: archive.read(n) for n in archive.namelist()
                    if not n.endswith("/") and ("/assets/" in n or "/res/" in n)}
        old_assets, new_assets = assets(old), assets(new)
        if old_assets.keys() != new_assets.keys():
            raise ValueError("Asset files added or removed")
        changed = sorted(n for n in old_assets if old_assets[n] != new_assets[n])
        unexpected = set(changed) - {NOTICES, FONT}
        if unexpected:
            raise ValueError(f"Unsupported asset changes: {sorted(unexpected)}")
        fonts = check_font(old_assets[FONT], new_assets[FONT])
        # Also refuse changes in plugin libraries; libapp.so is the Dart patch.
        libs = lambda z: {n: z.read(n) for n in z.namelist()
                          if n.endswith(".so") and not n.endswith("/libapp.so")}
        if libs(old) != libs(new):
            raise ValueError("Native library files changed")
        return {"changed_assets": changed, "font_compatibility": fonts,
                "installed_sha256": hashlib.sha256(Path(installed_path).read_bytes()).hexdigest(),
                "built_sha256": hashlib.sha256(Path(built_path).read_bytes()).hexdigest()}


@contextmanager
def installed_plugin_graph(legacy):
    if not legacy:
        yield
        return
    # Only the CI checkout changes: remove the plugin absent in 1.0.x and use
    # its reviewed Dart-only browser-link fallback. Other packages stay locked.
    manifest = Path("pubspec.yaml")
    lock = Path("pubspec.lock")
    launcher = Path("lib/services/external_url.dart")
    original = {p: p.read_bytes() for p in (manifest, lock, launcher)}
    try:
        text = manifest.read_text(encoding="utf-8")
        text, count = re.subn(r"(?m)^  url_launcher:.*\n", "", text)
        if count != 1:
            raise ValueError("Expected one url_launcher dependency")
        manifest.write_text(text, encoding="utf-8")
        launcher.write_bytes(Path("lib/services/external_url_legacy.dart").read_bytes())
        subprocess.run(["flutter", "pub", "get", "--offline"], check=True)
        subprocess.run(["flutter", "analyze", "--no-pub"], check=True)
        subprocess.run(["flutter", "test", "--no-pub",
                        "--dart-define=MINTLY_LEGACY_ICONS=true"], check=True)
        yield
    finally:
        for path, data in original.items():
            path.write_bytes(data)
        subprocess.run(["flutter", "pub", "get", "--offline"], check=True)


@contextmanager
def installed_launcher_icons(version, release_archive):
    if version != "1.0.0+1":
        yield False
        return
    # The first installer predates Mintly's launcher icon. Keep its five exact
    # installed PNGs in this build; a wallet OTA does not need a launcher change.
    densities = ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")
    paths = {density: Path(f"android/app/src/main/res/mipmap-{density}/ic_launcher.png")
             for density in densities}
    original = {path: path.read_bytes() for path in paths.values()}
    try:
        with zipfile.ZipFile(release_archive) as archive:
            for density, path in paths.items():
                path.write_bytes(archive.read(f"base/res/mipmap-{density}-v4/ic_launcher.png"))
        yield True
    finally:
        for path, data in original.items():
            path.write_bytes(data)


def patch_release(version, track, audit_only):
    command = ["shorebird", "--json", "patch", "android", "--release-version",
               version, "--track", track]
    legacy_icons = version in {"1.0.0+1", "1.0.1+2"}
    if legacy_icons:
        command.append("--dart-define=MINTLY_LEGACY_ICONS=true")
    # Isolate Shorebird downloads so the archive audited is the exact release
    # selected by the CLI, rather than a guessed or stale release artifact.
    with installed_native_sources(version), installed_plugin_graph(legacy_icons), tempfile.TemporaryDirectory(prefix="mintly-ota-") as scratch:
        env = {**os.environ, "TMPDIR": scratch, "TMP": scratch, "TEMP": scratch}
        subprocess.run(command + ["--dry-run", "--allow-asset-diffs"], env=env, check=True)
        candidates = []
        for path in Path(scratch).rglob("artifact"):
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    if NOTICES in archive.namelist():
                        candidates.append(path)
        if len(candidates) != 1:
            raise ValueError(f"Expected one release AAB, found {len(candidates)}")
        built = Path("build/app/outputs/bundle/release/app-release.aab")
        with installed_launcher_icons(version, candidates[0]) as preserved_launcher:
            if preserved_launcher:
                subprocess.run(command + ["--dry-run", "--allow-asset-diffs"], env=env, check=True)
            result = audit(candidates[0], built)
            result.update(release_version=version, track=track, legacy_icons=legacy_icons,
                          browser_links="copy and paste" if legacy_icons else "native launcher",
                          preserved_installed_launcher=preserved_launcher,
                          native_checks="Shorebird enabled; no override")
            evidence = Path(f"build/shorebird/wallet-ota-audit-{version}.json")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print("Wallet OTA compatibility audit: " + json.dumps(result), flush=True)
            if not audit_only:
                subprocess.run(command + ["--allow-asset-diffs"], env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-version", required=True,
                        help="One version or a comma separated list of installed versions")
    parser.add_argument("--track", default="stable", choices=("stable", "staging"))
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    versions = args.release_version.split(",")
    if len(versions) != len(set(versions)) or any(
        not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\+[0-9]+", v) for v in versions
    ):
        parser.error("Provide unique exact installed versions, for example 1.1.0+3")
    for version in versions:
        patch_release(version, args.track, args.audit_only)


if __name__ == "__main__":
    main()
