import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/splash_screen.dart';

void main() {
  testWidgets('SplashScreen renders approved brand assets and no preview buttons', (tester) async {
    await tester.pumpWidget(
      const ProviderScope(
        child: MaterialApp(
          home: SplashScreen(),
        ),
      ),
    );

    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    // Verify wordmark and tagline
    expect(find.text('A LITTLE AHEAD'), findsOneWidget);
    expect(find.textContaining('Your next mint'), findsOneWidget);
    expect(find.text('DISCOVER · PREPARE · MINT'), findsOneWidget);

    // Verify preview-only controls from the HTML prototype do NOT appear in Flutter
    expect(find.text('Play launch →'), findsNothing);
    expect(find.text('Replay splash ↻'), findsNothing);

    // Advance past the 1800ms timer
    await tester.pump(const Duration(milliseconds: 2000));
  });
}
