import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/splash_screen.dart';

void main() {
  testWidgets('SplashScreen renders approved brand assets and no preview buttons', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final localFont = File('C:/Windows/Fonts/arial.ttf');
    if (localFont.existsSync()) {
      final fonts = FontLoader('Roboto')
        ..addFont(
          Future.value(ByteData.sublistView(localFont.readAsBytesSync())),
        );
      await fonts.load();
      final icons = File(
        'C:/Users/USER/develop/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
      );
      if (icons.existsSync()) {
        await (FontLoader('MaterialIcons')..addFont(
              Future.value(ByteData.sublistView(icons.readAsBytesSync())),
            ))
            .load();
      }
    }
    final captureKey = GlobalKey();
    await tester.pumpWidget(
      ProviderScope(
        child: RepaintBoundary(
          key: captureKey,
          child: const MaterialApp(
            debugShowCheckedModeBanner: false,
            home: SplashScreen(),
          ),
        ),
      ),
    );

    await tester.pump();
    await tester.pump(const Duration(milliseconds: 120));
    final before = tester
        .widget<Transform>(find.byKey(const Key('splash-mark-scale')))
        .transform
        .entry(0, 0);
    await tester.pump(const Duration(milliseconds: 400));
    final after = tester
        .widget<Transform>(find.byKey(const Key('splash-mark-scale')))
        .transform
        .entry(0, 0);
    expect(after, greaterThan(before));
    expect(find.text('mintly'), findsNothing);
    expect(find.text('mintly.'), findsNothing);
    expect(find.text('Getting ready…'), findsOneWidget);

    // Verify the logo animation and supporting copy without a wordmark.
    expect(find.text('A LITTLE AHEAD'), findsOneWidget);
    expect(find.textContaining('Your next mint'), findsOneWidget);
    expect(find.text('DISCOVER · PREPARE · MINT'), findsOneWidget);

    // Verify preview-only controls from the HTML prototype do NOT appear in Flutter
    expect(find.text('Play launch →'), findsNothing);
    expect(find.text('Replay splash ↻'), findsNothing);

    if (localFont.existsSync()) {
      await tester.runAsync(() async {
        final image =
            await (captureKey.currentContext!.findRenderObject()
                    as RenderRepaintBoundary)
                .toImage(pixelRatio: 2);
        final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
        await Directory('build/account-review').create(recursive: true);
        await File(
          'build/account-review/splash.png',
        ).writeAsBytes(bytes!.buffer.asUint8List());
        image.dispose();
      });
    }

    // Advance past the 1800ms timer
    await tester.pump(const Duration(milliseconds: 2000));
  });
  testWidgets(
    'Splash respects reduced motion and cancels navigation when disposed',
    (tester) async {
      await tester.pumpWidget(
        const ProviderScope(
          child: MaterialApp(
            home: MediaQuery(
              data: MediaQueryData(disableAnimations: true),
              child: SplashScreen(),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));
      final scale = tester
          .widget<Transform>(find.byKey(const Key('splash-mark-scale')))
          .transform
          .entry(0, 0);
      expect(scale, 1);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(seconds: 3));
      expect(tester.takeException(), isNull);
    },
  );
}
