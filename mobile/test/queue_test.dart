import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/queue_screen.dart';

void main() {
  testWidgets('empty plans explain MetaMask approval', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: MaterialApp(
      home: Scaffold(body: QueueScreen()),
    )));
    expect(find.text('Mint plans'), findsOneWidget);
    expect(find.text('No mint plans yet'), findsOneWidget);
    expect(find.textContaining('MetaMask asks you to approve'), findsOneWidget);
  });
}
