import 'package:flutter/material.dart';

// The first Android installers contain a smaller tree-shaken font. Those
// release-specific patches use glyphs already present in that installed font.
class MintlyIcons {
  static const _legacy = bool.fromEnvironment('MINTLY_LEGACY_ICONS');
  static const addLink = _legacy ? Icons.add : Icons.add_link;
  static const adminPanelSettings = _legacy
      ? Icons.verified_user_outlined
      : Icons.admin_panel_settings_outlined;
  static const chevronRight = _legacy
      ? Icons.arrow_forward
      : Icons.chevron_right;
  static const link = _legacy ? Icons.arrow_forward : Icons.link;
  static const linkOff = _legacy ? Icons.close : Icons.link_off;
  static const lockOutline = _legacy
      ? Icons.verified_user_outlined
      : Icons.lock_outline;
  static const logout = _legacy ? Icons.arrow_back : Icons.logout;
  static const openInNew = _legacy ? Icons.arrow_forward : Icons.open_in_new;
  static const personAdd = _legacy ? Icons.add : Icons.person_add_alt;
  static const public = _legacy ? Icons.cloud_outlined : Icons.public;
}
