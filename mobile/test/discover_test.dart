import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/discover_screen.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  testWidgets('DiscoverScreen renders shortlisted drops, source card, and filter chips', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final container = ProviderContainer();
    addTearDown(container.dispose);

    // Pre-populate data
    await container.read(mintlyProvider.notifier).loadInitialData();

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(
          home: Scaffold(body: DiscoverScreen()),
        ),
      ),
    );

    await tester.pumpAndSettle();

    // Verify greetings and source
    expect(find.text('Find your next mint.'), findsOneWidget);
    expect(find.text("Hey Jenny. Your shortlist is ready."), findsOneWidget);
    expect(find.text("LAKZONE’s daily list"), findsOneWidget);

    // Verify filter chips
    expect(find.text('All drops'), findsOneWidget);
    expect(find.text('Eligible · 2'), findsOneWidget);
    expect(find.text('Needs review · 1'), findsOneWidget);

    // Verify reference drops appear
    expect(find.text('Orbit Bloom'), findsOneWidget);
    expect(find.text('Paper Planets'), findsOneWidget);
    expect(find.text('Midnight Club'), findsOneWidget);

    // Verify wallet check footer
    expect(find.text('Wallet: Jenny · Demo address'), findsOneWidget);
    expect(find.text('Recheck'), findsOneWidget);
  });
}
