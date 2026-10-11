# Dark UI OTA compatibility

The ordinary patch workflow targeted `1.1.1+4` with current Android sources. That installer predates the current native secure-session implementation, so Shorebird correctly refused the native differences. A Dart patch must retain the installed native implementation.

Pushes now use the existing audited builder. It preserves the native sources for the four older versions, retains the oldest launcher's assets and plugin graph, verifies unchanged native libraries and assets, and requires every requested icon glyph to exist with identical outlines and metrics in the installed font. Native differences are never overridden.

`MINTLY_SHOREBIRD_PATCH_RELEASE_VERSIONS` selects the supported installed versions for automatic patches. The current set is `1.1.2+5,1.1.1+4,1.1.0+3,1.0.1+2,1.0.0+1`. Manual patch inputs can select an exact version instead.

The budget refresh symbol is drawn in Dart, and the Copy tab uses its existing drawn symbol without referencing an unused new font glyph. The `1.1.2+5` build uses `MINTLY_RELEASE_5_ICONS=true` to choose equivalent installed symbols for account activity and links. All screen actions, authentication, mint approvals, copying and spending rules are retained.

The workflow tests normal, earliest-installer and release-5 icon modes. The audited builder dry-runs each exact installed release before publication and saves an asset audit for it. This update adds no native code, plugin, bundled image, dependency or database migration. It does not require a backend redeployment.

Published OTA availability must be checked against the Shorebird stable channel and all three Android architectures. Activation on an individual phone requires launching online, allowing the download to finish, then fully closing and reopening Mintly; publication alone does not prove device activation.
