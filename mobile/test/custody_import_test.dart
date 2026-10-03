import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/custody_import_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/wallet_secret.dart';
import 'package:mintly/state/app_state.dart';
import 'wallet_secret_test.dart' show phrase, firstAddress, firstKey;

void main() {
  test(
    'unverified success never confirms import and secret payload is cleared',
    () async {
      final api = ApiService(
        client: MockClient(
          (request) async => request.url.path.endsWith('/auth/login')
              ? http.Response(
                  '{"token":"token","user":{"username":"member"}}',
                  200,
                )
              : http.Response('<html>proxy response</html>', 200),
        ),
      );
      await api.login('member', 'test');
      final payload = <String, dynamic>{
        'request_id': 'request',
        'wallet_id': 'wallet',
        'private_key': 'test-secret',
        'password': 'password',
      };
      await expectLater(
        api.importCustodyWallet(payload),
        throwsA(isA<ApiException>()),
      );
      expect(payload.containsKey('private_key'), isFalse);
      expect(payload.containsKey('password'), isFalse);
    },
  );
  testWidgets(
    'phrase stays on device, exact account key imports with automatic collections and consent',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final requests = <Map<String, dynamic>>[];
      final pending = Completer<http.Response>();
      final api = ApiService(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"token","user":{"username":"member"}}',
              200,
            );
          }
          if (request.url.path.endsWith('/config')) {
            return http.Response(
              '{"chain_id":4663,"automatic_collection_selection":true}',
              200,
            );
          }
          expect(request.body.contains(phrase), isFalse);
          requests.add(jsonDecode(request.body) as Map<String, dynamic>);
          return pending.future;
        }),
      );
      await api.login('member', 'test');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiServiceProvider.overrideWith((ref) => api),
            walletSecretResolverProvider.overrideWith(
              (ref) =>
                  (input) async => resolveWalletSecret(input),
            ),
          ],
          child: const MaterialApp(
            home: CustodyImportScreen(
              walletId: 'wallet',
              address: firstAddress,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('Allowed NFT collection'), findsNothing);
      final phraseField = find.byKey(const Key('custody-recovery-phrase'));
      await tester.enterText(phraseField, phrase);
      final input = tester.widget<EditableText>(
        find.descendant(of: phraseField, matching: find.byType(EditableText)),
      );
      expect(input.obscureText, isTrue);
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(input.controller.text, isEmpty);
      expect(find.text('Minting limits'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );
      await tester.enterText(find.byKey(const Key('custody-budget')), '0.001');
      final password = find.byKey(const Key('custody-password'));
      await tester.enterText(password, 'mintly-password');
      final passwordInput = tester.widget<EditableText>(
        find.descendant(of: password, matching: find.byType(EditableText)),
      );
      expect(passwordInput.obscureText, isTrue);
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      await tester.tap(find.text('Import wallet'));
      await tester.pump();
      expect(requests.length, 1);
      expect(requests.single['private_key'], firstKey);
      expect(requests.single['collection_scope'], 'reviewed_mints');
      expect(requests.single.containsKey('contract'), isFalse);
      expect(requests.single['max_task_eth'], '0.001');
      expect(passwordInput.controller.text, isEmpty);
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );
      pending.complete(http.Response(jsonEncode({'detail': firstKey}), 409));
      await tester.pumpAndSettle();
      expect(find.textContaining(firstKey), findsNothing);
      expect(find.textContaining('Import not confirmed.'), findsOneWidget);
      expect(find.byKey(const Key('custody-recovery-phrase')), findsOneWidget);
    },
  );

  testWidgets(
    'backgrounding clears phrase and rejects a derivation finishing afterwards',
    (tester) async {
      final api = ApiService(
        client: MockClient(
          (r) async => r.url.path.endsWith('/auth/login')
              ? http.Response(
                  '{"token":"token","user":{"username":"member"}}',
                  200,
                )
              : http.Response(
                  '{"chain_id":4663,"automatic_collection_selection":true}',
                  200,
                ),
        ),
      );
      await api.login('member', 'test');
      final pending = Completer<Uint8List?>();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiServiceProvider.overrideWith((ref) => api),
            walletSecretResolverProvider.overrideWith(
              (ref) =>
                  (input) => pending.future,
            ),
          ],
          child: const MaterialApp(
            home: CustodyImportScreen(
              walletId: 'wallet',
              address: firstAddress,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('custody-recovery-phrase')),
        phrase,
      );
      await tester.ensureVisible(find.text('Continue'));
      await tester.tap(find.text('Continue'));
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      final key = Uint8List(32)..fillRange(0, 32, 1);
      pending.complete(key);
      await tester.pumpAndSettle();
      expect(key.every((v) => v == 0), isTrue);
      expect(find.text('Minting limits'), findsNothing);
      final input = tester.widget<EditableText>(
        find.descendant(
          of: find.byKey(const Key('custody-recovery-phrase')),
          matching: find.byType(EditableText),
        ),
      );
      expect(input.controller.text, isEmpty);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    },
  );
  testWidgets('unavailable or old ingress never presents a secret field', (
    tester,
  ) async {
    for (final response in [
      http.Response('{"detail":"Disabled"}', 409),
      http.Response('{"chain_id":4663}', 200),
    ]) {
      final api = ApiService(
        client: MockClient(
          (r) async => r.url.path.endsWith('/auth/login')
              ? http.Response(
                  '{"token":"token","user":{"username":"member"}}',
                  200,
                )
              : response,
        ),
      );
      await api.login('member', 'test');
      await tester.pumpWidget(
        ProviderScope(
          key: UniqueKey(),
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: const MaterialApp(
            home: CustodyImportScreen(walletId: 'wallet', address: 'address'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(TextFormField), findsNothing);
      expect(find.textContaining('not available'), findsOneWidget);
    }
  });
}
