import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/discover_screen.dart';

void main() {
  testWidgets('empty live feed contains no fabricated drops', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(() { tester.view.resetPhysicalSize(); tester.view.resetDevicePixelRatio(); });
    await tester.pumpWidget(const ProviderScope(child: MaterialApp(
      home: Scaffold(body: DiscoverScreen()),
    )));
    expect(find.text('OpenSea drops'), findsOneWidget);
    expect(find.textContaining('No current drops from the live source'), findsOneWidget);
    expect(find.text('Orbit Bloom'), findsNothing);
  });
}
