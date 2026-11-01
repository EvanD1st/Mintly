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
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

NOTICES = "base/assets/flutter_assets/NOTICES.Z"
FONT = "base/assets/flutter_assets/fonts/MaterialIcons-Regular.otf"

# Exact source revisions used by the installed release builds. Native checks
# remain enabled; the new Dart code must work with each installer's own APIs.
NATIVE_BASELINES = {
    '1.1.3+6': '75b4117648a1f77a23e6cf3a9a467fba8c292ef9',
    '1.1.2+5': 'f18096a13caf05a53bb85d2344734c5c8487c457',
    **{version: '6c9c5a83cff9fb35ca0bbef8c4ad2c2fb43ae235'
       for version in ('1.1.1+4', '1.1.0+3', '1.0.1+2', '1.0.0+1')},
}

LEGACY_ICON_VERSIONS = frozenset(('1.0.0+1', '1.0.1+2'))
# Releases 6 and 7 also predate the account chooser's shield glyph. Use the
# already tested release-5 fallback, whose required icons are installed in all
# three versions. The per-release font audit still verifies every glyph.
RELEASE_5_ICON_VERSIONS = frozenset(('1.1.2+5', '1.1.3+6', '1.1.4+7'))


def patch_command(version, track):
    command = ["shorebird", "--json", "patch", "android", "--release-version",
               version, "--track", track]
    if version in LEGACY_ICON_VERSIONS:
        command.append("--dart-define=MINTLY_LEGACY_ICONS=true")
    if version in RELEASE_5_ICON_VERSIONS:
        command.append("--dart-define=MINTLY_RELEASE_5_ICONS=true")
    return command


@contextmanager
def installed_native_sources(version):
    """Old installers get Dart fallback only; never replace their native secure store."""
    baseline = NATIVE_BASELINES.get(version)
    if baseline is None:
        yield
        return
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


def dry_run(command, env, version):
    completed = subprocess.run(command + ["--dry-run", "--allow-asset-diffs"],
                               env=env, check=True, stdout=subprocess.PIPE, text=True)
    payload = json.loads(completed.stdout)
    result = payload.get('data', {})
    if (payload.get('status') != 'success' or result.get('dry_run') is not True
            or result.get('release_version') != version
            or type(result.get('release_id')) is not int or result['release_id'] <= 0
            or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', result.get('app_id', ''))):
        raise ValueError('Dry-run did not confirm the requested release identity')
    return result


def release_bundle(release, scratch):
    """Download the exact dry-run release through authenticated artifact metadata.

    Shorebird 1.6.134 caches downloads outside TMPDIR. Do not scan that shared
    cache or guess an installed archive; bind the audit to the reported release
    ID, Android AAB artifact and server-recorded SHA256 and byte length instead.
    Signed download URLs stay in memory and are never printed in the audit log.
    """
    endpoint = (f"/apps/{release['app_id']}/releases/{release['release_id']}/artifacts"
                "?arch=aab&platform=android")
    completed = subprocess.run(['shorebird', 'api', 'GET', endpoint], check=True,
                               stdout=subprocess.PIPE, text=True)
    artifacts = json.loads(completed.stdout).get('artifacts', [])
    if len(artifacts) != 1:
        raise ValueError('Expected exactly one original Android AAB artifact')
    artifact = artifacts[0]
    digest = artifact.get('hash', '')
    if (artifact.get('release_id') != release['release_id']
            or artifact.get('platform') != 'android' or artifact.get('arch') != 'aab'
            or type(artifact.get('id')) is not int or artifact['id'] <= 0
            or type(artifact.get('size')) is not int or artifact['size'] <= 0
            or not re.fullmatch(r'[0-9a-f]{64}', digest)):
        raise ValueError('Original release artifact metadata is invalid')
    url = artifact.get('url', '')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Original release bundle requires an HTTPS download')
    destination = Path(scratch) / 'installed.aab'
    checksum, size = hashlib.sha256(), 0
    try:
        with urlopen(url, timeout=60) as response, destination.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > artifact['size']:
                    raise ValueError('Original release bundle exceeds its recorded size')
                checksum.update(chunk)
                output.write(chunk)
    except OSError:
        raise ValueError('Original release bundle could not be downloaded') from None
    if size != artifact['size'] or checksum.hexdigest() != digest:
        raise ValueError('Original release bundle failed its recorded SHA256 or size check')
    with zipfile.ZipFile(destination) as archive:
        if NOTICES not in archive.namelist():
            raise ValueError('Original release artifact is not an Android app bundle')
    return destination, {'release_id': release['release_id'], 'artifact_id': artifact['id'],
                         'artifact_sha256': digest, 'artifact_size': size}


def patch_release(version, track, audit_only):
    command = patch_command(version, track)
    legacy_icons = version in LEGACY_ICON_VERSIONS
    # Keep build scratch isolated and bind the audit to the CLI's selected release.
    with installed_native_sources(version), installed_plugin_graph(legacy_icons), tempfile.TemporaryDirectory(prefix="mintly-ota-") as scratch:
        env = {**os.environ, "TMPDIR": scratch, "TMP": scratch, "TEMP": scratch}
        release = dry_run(command, env, version)
        installed, artifact = release_bundle(release, scratch)
        built = Path("build/app/outputs/bundle/release/app-release.aab")
        with installed_launcher_icons(version, installed) as preserved_launcher:
            if preserved_launcher:
                repeated = dry_run(command, env, version)
                if any(repeated[key] != release[key] for key in ('app_id', 'release_id', 'release_version')):
                    raise ValueError('Release identity changed during launcher compatibility build')
            result = audit(installed, built)
            if result['installed_sha256'] != artifact['artifact_sha256']:
                raise ValueError('Original release bundle changed before the asset audit')
            result.update(release_version=version, track=track, legacy_icons=legacy_icons,
                          release_5_icons=version in RELEASE_5_ICON_VERSIONS,
                          browser_links="copy and paste" if legacy_icons else "native launcher",
                          preserved_installed_launcher=preserved_launcher,
                          native_checks="Shorebird enabled; no override", original_artifact=artifact)
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
