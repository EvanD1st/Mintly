import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/configure_screen.dart';
import 'package:mintly/screens/queue_screen.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  testWidgets('ConfigureScreen displays quantity buttons and spending cap', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final container = ProviderContainer();
    addTearDown(container.dispose);

    // Load initial data
    await container.read(mintlyProvider.notifier).loadInitialData();

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(
          home: ConfigureScreen(),
        ),
      ),
    );

    await tester.pumpAndSettle();

    // Verify Title & Fields
    expect(find.text('PLAN YOUR MINT'), findsOneWidget);
    expect(find.text('Ready before the drop.'), findsOneWidget);
    expect(find.text('Minting wallet'), findsOneWidget);
    expect(find.text('Maximum transaction fee (ETH)'), findsOneWidget);
    expect(find.text('Total spending cap'), findsOneWidget);

    // Verify Review Button
    expect(find.text('Review mint'), findsOneWidget);
  });

  testWidgets('QueueScreen displays empty state when no tasks are armed', (tester) async {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(
          home: Scaffold(body: QueueScreen()),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('Mint queue'), findsOneWidget);
    expect(find.text('No mints armed yet'), findsOneWidget);
    expect(find.textContaining('Your next mint starts with a plan'), findsOneWidget);
  });
}
