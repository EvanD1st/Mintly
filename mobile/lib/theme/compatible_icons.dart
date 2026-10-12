import 'package:flutter/material.dart';

// The first Android installers contain a smaller tree-shaken font. Those
// release-specific patches use glyphs already present in that installed font.
class MintlyIcons {
  static const _legacy = bool.fromEnvironment('MINTLY_LEGACY_ICONS');
  static const _release5 = bool.fromEnvironment('MINTLY_RELEASE_5_ICONS');
  static const verifiedUser = _release5
      ? Icons.lock_outline
      : Icons.verified_user_outlined;
  static const download = _release5
      ? Icons.arrow_forward
      : Icons.download_outlined;
  static const notifications = _release5
      ? Icons.star
      : Icons.notifications_none;
  static const pauseCircle = _release5
      ? Icons.close
      : Icons.pause_circle_outline;
  static const addLink = _legacy ? Icons.add : Icons.add_link;
  static const adminPanelSettings = _legacy
      ? Icons.verified_user_outlined
      : Icons.admin_panel_settings_outlined;
  static const chevronRight = _legacy
      ? Icons.arrow_forward
      : Icons.chevron_right;
  static const link = _legacy
      ? Icons.arrow_forward
      : _release5
      ? Icons.add_link
      : Icons.link;
  static const linkOff = _legacy ? Icons.close : Icons.link_off;
  static const lockOutline = _legacy
      ? Icons.verified_user_outlined
      : Icons.lock_outline;
  static const logout = _legacy ? Icons.arrow_back : Icons.logout;
  static const openInNew = _legacy ? Icons.arrow_forward : Icons.open_in_new;
  static const personAdd = _legacy ? Icons.add : Icons.person_add_alt;
  static const public = _legacy ? Icons.cloud_outlined : Icons.public;
}
