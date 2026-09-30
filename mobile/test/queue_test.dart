import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/queue_screen.dart';

void main() {
  testWidgets('empty history explains MetaMask approval', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: MaterialApp(
      home: Scaffold(body: QueueScreen()),
    )));
    expect(find.text('Mint history'), findsOneWidget);
    expect(find.text('No task history'), findsOneWidget);
    expect(find.textContaining('MetaMask asks you to approve'), findsOneWidget);
  });
}
