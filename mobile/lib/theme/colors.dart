import 'package:flutter/material.dart';

class MintlyColors {
  // Brand Green & Lime
  static const Color greenLight = Color(0xFF2A6940);
  static const Color greenDark = Color(0xFFB5E6A2);
  static const Color limeLight = Color(0xFFD5EDB7);
  static const Color limeDark = Color(0xFFB5E6A2);

  // Surfaces & Backgrounds
  static const Color bgLight = Color(0xFFF6F8F5);
  static const Color bgDark = Color(0xFF101713);
  static const Color panelLight = Color(0xFFFFFFFF);
  static const Color panelDark = Color(0xFF19221C);
  static const Color softLight = Color(0xFFEAF0E8);
  static const Color softDark = Color(0xFF233128);

  // Typography & Borders
  static const Color inkLight = Color(0xFF19271E);
  static const Color inkDark = Color(0xFFEDF4ED);
  static const Color mutedLight = Color(0xFF657469);
  static const Color mutedDark = Color(0xFFA3B2A6);
  static const Color lineLight = Color(0xFFDCE4DC);
  static const Color lineDark = Color(0xFF303D33);

  // On Green & Badges
  static const Color onGreenLight = Color(0xFFFFFFFF);
  static const Color onGreenDark = Color(0xFF152610);

  // Status & Warnings
  static const Color warnTextLight = Color(0xFF875922);
  static const Color warnTextDark = Color(0xFFE7BC76);
  static const Color warnBgLight = Color(0xFFFFF1DC);
  static const Color warnBgDark = Color(0xFF382E21);
  static const Color redLight = Color(0xFF9D3E40);
  static const Color redDark = Color(0xFFEDA3A4);

  // Artwork Backgrounds & Accents
  static const Color artOrbitBgLight = Color(0xFFE9DCF8);
  static const Color artOrbitBgDark = Color(0xFF392B4A);
  static const Color artOrbitFgLight = Color(0xFF7954A1);
  static const Color artOrbitFgDark = Color(0xFFD9BBF5);

  static const Color artPaperBgLight = Color(0xFFD8E8ED);
  static const Color artPaperBgDark = Color(0xFF253A44);
  static const Color artPaperFgLight = Color(0xFF3D6C83);
  static const Color artPaperFgDark = Color(0xFFA7D7E9);

  static const Color artMidnightBgLight = Color(0xFFF6E6C9);
  static const Color artMidnightBgDark = Color(0xFF473825);
  static const Color artMidnightFgLight = Color(0xFF926527);
  static const Color artMidnightFgDark = Color(0xFFECD0A1);

  static Color getBg(bool isDark) => isDark ? bgDark : bgLight;
  static Color getPanel(bool isDark) => isDark ? panelDark : panelLight;
  static Color getInk(bool isDark) => isDark ? inkDark : inkLight;
  static Color getMuted(bool isDark) => isDark ? mutedDark : mutedLight;
  static Color getLine(bool isDark) => isDark ? lineDark : lineLight;
  static Color getSoft(bool isDark) => isDark ? softDark : softLight;
  static Color getGreen(bool isDark) => isDark ? greenDark : greenLight;
  static Color getOnGreen(bool isDark) => isDark ? onGreenDark : onGreenLight;
}
