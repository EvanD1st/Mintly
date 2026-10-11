import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/queue_screen.dart';

void main() {
  testWidgets(
    'queue distinguishes server automation from manual wallet plans',
    (tester) async {
      await tester.pumpWidget(
        const ProviderScope(
          child: MaterialApp(home: Scaffold(body: QueueScreen())),
        ),
      );
      expect(find.text('Mint plans'), findsOneWidget);
      expect(find.text('No mint plans yet'), findsOneWidget);
      expect(
        find.textContaining('Only armed tasks authorize automatic execution'),
        findsOneWidget,
      );
      expect(find.text('View mint history'), findsOneWidget);
    },
  );
}
