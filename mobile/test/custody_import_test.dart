import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/custody_import_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  test('unverified success never confirms import and secret payload is cleared', () async {
    final api = ApiService(client: MockClient((request) async => request.url.path.endsWith('/auth/login')
      ? http.Response('{"token":"token","user":{"username":"member"}}', 200)
      : http.Response('<html>proxy response</html>', 200)));
    await api.login('member', 'test');
    final payload = <String,dynamic>{'request_id':'request','wallet_id':'wallet','private_key':'test-secret','password':'password'};
    await expectLater(api.importCustodyWallet(payload), throwsA(isA<ApiException>()));
    expect(payload.containsKey('private_key'), isFalse);
    expect(payload.containsKey('password'), isFalse);
  });
  testWidgets('import requires consent, clears secrets and never echoes a failed response', (tester) async {
    tester.view.physicalSize = const Size(1000, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final requests = <Map<String, dynamic>>[];
    final pending = Completer<http.Response>();
    final api = ApiService(client: MockClient((request) async {
      if (request.url.path.endsWith('/auth/login')) return http.Response('{"token":"token","user":{"username":"member"}}', 200);
      if (request.url.path.endsWith('/config')) return http.Response('{"chain_id":4663}', 200);
      requests.add(jsonDecode(request.body) as Map<String, dynamic>);
      return pending.future;
    }));
    await api.login('member', 'test');
    await tester.pumpWidget(ProviderScope(overrides: [apiServiceProvider.overrideWith((ref) => api)],
      child: const MaterialApp(home: CustodyImportScreen(walletId: 'wallet', address: '0x1111111111111111111111111111111111111111'))));
    await tester.pumpAndSettle();
    expect(find.text('Network: Robinhood mainnet'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.byType(FilledButton)).onPressed, isNull);
    final fields = find.byType(TextFormField);
    await tester.enterText(fields.at(0), '0x2222222222222222222222222222222222222222');
    await tester.enterText(fields.at(1), '0.001');
    await tester.enterText(fields.at(2), '0.0001');
    final secret = 'ab' * 32;
    final keyField = find.byKey(const Key('custody-private-key'));
    final passwordField = find.byKey(const Key('custody-password'));
    await tester.enterText(keyField, secret);
    await tester.enterText(passwordField, 'mintly-password');
    final keyInput = tester.widget<EditableText>(find.descendant(of: keyField, matching: find.byType(EditableText)));
    final passwordInput = tester.widget<EditableText>(find.descendant(of: passwordField, matching: find.byType(EditableText)));
    expect(keyInput.obscureText, isTrue);
    expect(passwordInput.obscureText, isTrue);
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pump();
    await tester.tap(find.text('Import wallet'));
    await tester.pump();
    expect(requests.length, 1);
    expect(requests.single['private_key'], secret);
    expect(keyInput.controller.text, isEmpty);
    expect(passwordInput.controller.text, isEmpty);
    expect(tester.widget<FilledButton>(find.byType(FilledButton)).onPressed, isNull);
    pending.complete(http.Response(jsonEncode({'detail': secret}), 409));
    await tester.pumpAndSettle();
    expect(find.textContaining(secret), findsNothing);
    expect(find.textContaining('Import not confirmed.'), findsOneWidget);
  });

  testWidgets('unavailable ingress never presents a private key field', (tester) async {
    final api = ApiService(client: MockClient((request) async => request.url.path.endsWith('/auth/login')
      ? http.Response('{"token":"token","user":{"username":"member"}}', 200)
      : http.Response('{"detail":"Disabled"}', 409)));
    await api.login('member', 'test');
    await tester.pumpWidget(ProviderScope(overrides: [apiServiceProvider.overrideWith((ref) => api)],
      child: const MaterialApp(home: CustodyImportScreen(walletId: 'wallet', address: 'address'))));
    await tester.pumpAndSettle();
    expect(find.byType(TextFormField), findsNothing);
    expect(find.textContaining('not available'), findsOneWidget);
  });
}
