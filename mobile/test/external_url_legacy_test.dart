import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mintly/services/external_url_legacy.dart';

void main() {
  testWidgets(
    'old installers can copy browser links without a launcher plugin',
    (tester) async {
      String? copied;
      bool? presented;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copied = (call.arguments as Map)['text'] as String;
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      final uri = Uri.parse('https://opensea.io/collection/example');
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () async {
                  presented = await openExternalUrl(context, uri);
                },
                child: const Text('View mint'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('View mint'));
      await tester.pumpAndSettle();
      expect(find.text(uri.toString()), findsOneWidget);
      expect(copied, isNull);
      await tester.tap(find.text('Copy link'));
      await tester.pumpAndSettle();
      expect(copied, uri.toString());
      expect(presented, isTrue);
      expect(tester.takeException(), isNull);
    },
  );
}
