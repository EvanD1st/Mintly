# Mintly Android updates and notifications

Mintly has its own Shorebird app ID in `mobile/shorebird.yaml`. It uses the
existing Firebase project `marketmind-f16d2`, with a distinct Android app
registration for package `com.mintly.mintly`. The MarketMind Android package
cannot substitute for this registration.

The Android build reads `mobile/android/app/google-services.json`. This file is
ignored by Git. GitHub Actions receives it through the
`MINTLY_GOOGLE_SERVICES_JSON_B64` repository secret. The backend and worker
read a Firebase service account from
`~/Mintly/shared/firebase-service-account.json` on Ubuntu. The deploy script
mounts that file read-only if present. No Firebase private key belongs in Git.

The app asks for notification permission after account sign-in,
registers its FCM token, and refreshes that registration if FCM rotates it.
The notification switches save per-device preferences to the backend.
Disconnecting deactivates that device token. The worker and manual-import API
send FCM messages to active, opted-in devices; invalid tokens are deactivated.
Foreground messages appear as a snack bar; Android displays background
notification payloads. The server only reports delivery when FCM accepts a
message, which is distinct from proof that a phone displayed it.

The signed Android installer must be created by Shorebird and installed once.
`flutter build apk` does not include Shorebird's update runtime. After that,
Shorebird checks for patches when the app starts and applies a downloaded patch
on a subsequent launch. Patches can change Dart code. Firebase plugin, Android
configuration, native code, and asset changes require a new signed installer.

`.github/workflows/shorebird-android.yml` has a manual **release** operation
and an automatic Dart patch path. The release job requires these repository
secrets: `SHOREBIRD_TOKEN`, `MINTLY_GOOGLE_SERVICES_JSON_B64`,
`MINTLY_ANDROID_KEYSTORE_B64`, `MINTLY_KEYSTORE_PASSWORD`,
`MINTLY_KEY_PASSWORD`, and `MINTLY_KEY_ALIAS`. After an installer has been
distributed, set repository variables `MINTLY_SHOREBIRD_RELEASE_VERSION` to
its exact version (for example `1.0.1+2`) and
`MINTLY_SHOREBIRD_RELEASE_READY` to `true`. Only then will a push to
`mobile/lib/` attempt a patch. The job checks for Android, iOS, asset, and
dependency changes in the same push and skips the patch when they are present.
Shorebird itself also rejects native differences.

The launcher icon is generated from `mobile/assets/icon/mintly.png` using
`dart run flutter_launcher_icons` in `mobile/`. Changing the icon requires a
new signed release and an updated installer; an over-the-air Dart patch cannot
change icons already installed on a phone.

To verify push end to end, install the signed Shorebird APK on an Android
device, sign in with an admin-created account, grant notification permission,
and import a real mint link as admin or wait for a new OpenSea listing. The
device should receive a new-drop notification; foreground and background
delivery should each be checked. The release key and its signing
metadata are stored outside this repository under `C:\Users\USER\.ssh` and
must be backed up for future installers.

Live Robinhood automatic minting was explicitly activated on 4 October 2026.
Users arm each exact stage through Mint plans after reviewing its finite limits.
Imported social posts and OpenSea URLs require independent stage and eligibility
verification before execution. The automatic notification service has a separate
protected Firebase credential copy and has no wallet-key mount.

The automatic-plans and History update was published to all four installed
Android versions on 4 October 2026: `1.1.1+4` patch 3, `1.1.0+3` patch 13,
`1.0.1+2` patch 3 and `1.0.0+1` patch 3. All three architectures passed the
existing native and asset checks. See [verified OTA records](automatic-plans-history-ota-2026-10-04.json).
Open Mintly online, allow the patch download to finish, then fully close and
reopen the app. Activation on a particular phone must be observed on that device.

## Wallet import OTA compatibility

Pure Dart recovery libraries can be included in a patch. Their new license
notices are embedded in `mobile/lib/services/wallet_licenses.dart`, registered
at startup, and available through Wallets → Settings → Open source licenses.
This delivers the notices even when the installed `NOTICES.Z` asset is older.

For the wallet update, manually dispatch **patch** with `audited_wallet_ota`
enabled and the exact installed release version. This mode also accepts a comma
separated list of installed versions. `deploy/shorebird-wallet-ota.py` first
performs a dry run, audits the release AAB downloaded by Shorebird against the
built AAB, and only then publishes. Asset file additions/removals, other asset
changes, missing font glyphs, altered glyph outlines/metrics, and native library
changes stop publication. Shorebird's native checks remain enabled. The asset
exception covers only the embedded licenses and a font subset already fully
provided by the installed font. Compatibility audit JSON is saved as a workflow
artifact for each release.

Versions `1.0.0+1` and `1.0.1+2` contain fewer Material icons. Their builds use
`MINTLY_LEGACY_ICONS=true` for equivalent installed icons, with the same wallet
features and limits. They also lack the native browser launcher introduced in
`1.1.0+3`. The audited build temporarily removes `url_launcher` from the CI
checkout's dependency graph and uses `external_url_legacy.dart`: browser actions
show a link with a Copy link button. The original source and dependency files
are restored after each build, including failures. That variant is analyzed and
tested before Shorebird checks the native code. No native-difference override is
used. The workflow tests both icon modes. Native plugin changes,
new images, and missing installed glyphs still require an installer update.
For `1.0.0+1`, the builder also copies that release's five exact installed
launcher PNGs from the downloaded AAB before rebuilding and auditing. The wallet
patch preserves its original launcher icon. The CI source PNGs are restored
afterwards, including on failures.

Devices check for a patch at launch. Open Mintly with internet access, let the
download finish, then fully close and reopen it to apply the update. Publishing
an OTA proves availability, not activation on every installed phone. This update
does not enable the production automatic spending worker.

### Published wallet update — 4 October 2026

The Shorebird API confirms these stable Android patches for every active
release, each with arm32, arm64, and x86_64 artifacts:

| Installed release | Stable patch |
| --- | --- |
| 1.0.0+1 | 1 |
| 1.0.1+2 | 1 |
| 1.1.0+3 | 11 |
| 1.1.1+4 | 1 |

[Rollout evidence](wallet-ota-2026-10-04.json) records source commits, build runs,
artifact hashes, asset audits, and production status. Some multi-target runs
published their compatible targets before rejecting another target; later runs
resolved those mismatches and published the remaining versions. No native diff
override was used. The final oldest-release run completed successfully.

The wallet update includes the simpler setup, local recovery phrase derivation,
and automatic collection selection for reviewed mints. Production mainnet
execution and the automatic spending worker remain disabled. Activation on
individual phones has not been observed; users must launch online and restart
after the download finishes.
