import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/main.dart';

void main() {
  testWidgets('MintlyApp root smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: MintlyApp()));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 2000));
    expect(find.byType(MintlyApp), findsOneWidget);
  });
}
