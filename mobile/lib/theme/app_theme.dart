import 'package:flutter/material.dart';
import 'colors.dart';

class MintlyTheme {
  static ThemeData light() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: MintlyColors.bgLight,
      colorScheme: const ColorScheme.light(
        primary: MintlyColors.greenLight,
        onPrimary: MintlyColors.onGreenLight,
        surface: MintlyColors.panelLight,
        onSurface: MintlyColors.inkLight,
        outline: MintlyColors.lineLight,
      ),
      fontFamily: 'Roboto',
      appBarTheme: const AppBarTheme(
        backgroundColor: MintlyColors.bgLight,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: MintlyColors.inkLight,
          fontSize: 24,
          fontWeight: FontWeight.w700,
          letterSpacing: -0.8,
        ),
      ),
      cardTheme: CardThemeData(
        color: MintlyColors.panelLight,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: MintlyColors.lineLight, width: 1),
        ),
        margin: const EdgeInsets.symmetric(vertical: 6),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: MintlyColors.greenLight,
          foregroundColor: MintlyColors.onGreenLight,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
          minimumSize: const Size.fromHeight(48),
          textStyle: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: MintlyColors.inkLight,
          backgroundColor: MintlyColors.panelLight,
          side: const BorderSide(color: MintlyColors.lineLight, width: 1),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
          minimumSize: const Size.fromHeight(44),
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: MintlyColors.panelLight,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: MintlyColors.lineLight),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: MintlyColors.lineLight),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: MintlyColors.greenLight, width: 2),
        ),
        hintStyle: const TextStyle(color: MintlyColors.mutedLight, fontSize: 14),
      ),
    );
  }

  static ThemeData dark() {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: MintlyColors.bgDark,
      colorScheme: const ColorScheme.dark(
        primary: MintlyColors.greenDark,
        onPrimary: MintlyColors.onGreenDark,
        surface: MintlyColors.panelDark,
        onSurface: MintlyColors.inkDark,
        outline: MintlyColors.lineDark,
      ),
      fontFamily: 'Roboto',
      appBarTheme: const AppBarTheme(
        backgroundColor: MintlyColors.bgDark,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: MintlyColors.inkDark,
          fontSize: 24,
          fontWeight: FontWeight.w700,
          letterSpacing: -0.8,
        ),
      ),
      cardTheme: CardThemeData(
        color: MintlyColors.panelDark,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: MintlyColors.lineDark, width: 1),
        ),
        margin: const EdgeInsets.symmetric(vertical: 6),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: MintlyColors.greenDark,
          foregroundColor: MintlyColors.onGreenDark,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
          minimumSize: const Size.fromHeight(48),
          textStyle: const TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: MintlyColors.inkDark,
          backgroundColor: MintlyColors.panelDark,
          side: const BorderSide(color: MintlyColors.lineDark, width: 1),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
          minimumSize: const Size.fromHeight(44),
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: MintlyColors.panelDark,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: MintlyColors.lineDark),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: MintlyColors.lineDark),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: MintlyColors.greenDark, width: 2),
        ),
        hintStyle: const TextStyle(color: MintlyColors.mutedDark, fontSize: 14),
      ),
    );
  }
}
