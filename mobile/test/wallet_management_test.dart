import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/wallet_screen.dart';
import 'package:mintly/screens/copy_mints_screen.dart';
import 'package:mintly/screens/custody_import_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/wallet_secret.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'wallet_secret_test.dart' show phrase;

void main() {
  testWidgets(
    'wallet rows unlink only after Okay and address and explicit signing choices replace web',
    (tester) async {
      var removed = 0;
      final wallets = [
        {'id': 'a', 'label': 'First wallet', 'address': '0x${'1' * 40}'},
        {'id': 'b', 'label': 'Second wallet', 'address': '0x${'2' * 40}'},
      ];
      final api = ApiService(
        client: MockClient((r) async {
          if (r.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          if (r.url.path.endsWith('/wallets/a') && r.method == 'DELETE') {
            removed++;
            wallets.removeAt(0);
            return http.Response('{"status":"unlinked"}', 200);
          }
          if (r.url.path.endsWith('/wallets')) {
            return http.Response(jsonEncode(wallets), 200);
          }
          if (r.url.path.endsWith('/config')) {
            return http.Response(
              '{"chain_id":4663,"automatic_collection_selection":true,"phrase_wallet_setup":true}',
              200,
            );
          }
          if (r.url.path.endsWith('/automatic/policies')) {
            return http.Response('[]', 200);
          }
          if (r.url.path.endsWith('/drops')) {
            return http.Response('{"drops":[]}', 200);
          }
          if (r.url.path.endsWith('/tasks/queue')) {
            return http.Response('{"tasks":[]}', 200);
          }
          return http.Response('[]', 200);
        }),
      );
      await api.login('member', 'password');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: MaterialApp(
            theme: MintlyTheme.light(),
            home: const Scaffold(body: WalletScreen()),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Unlink'), findsNWidgets(2));
      expect(find.text('Connect MetaMask'), findsNothing);
      await tester.tap(find.byKey(const ValueKey('unlink-a')));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('disables copying and automatic minting'),
        findsOneWidget,
      );
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(removed, 0);
      await tester.tap(find.byKey(const ValueKey('unlink-a')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Okay'));
      await tester.pumpAndSettle();
      expect(removed, 1);
      expect(find.text('First wallet'), findsNothing);
      expect(find.text('Second wallet'), findsOneWidget);
      await tester.tap(find.text('Add wallet'));
      await tester.pumpAndSettle();
      expect(find.text('Add address only'), findsOneWidget);
      expect(find.text('Secret recovery phrase'), findsNothing);
      await tester.tap(find.text('Continue to automatic signing'));
      await tester.pumpAndSettle();
      expect(find.text('Secret recovery phrase'), findsOneWidget);
      expect(find.text('Private key'), findsNothing);
      expect(find.text('Account number'), findsOneWidget);
    },
  );

  testWidgets(
    'adding a second followed wallet shows both even when activity reload fails',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final watches = <Map<String, dynamic>>[
        {
          'id': 'one',
          'label': 'First source',
          'address': '0x${'1' * 40}',
          'chains': [4663],
          'cursors': <String, dynamic>{},
          'rules': [],
          'recent_mints': 0,
        },
      ];
      final api = ApiService(
        client: MockClient((r) async {
          if (r.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          if (r.url.path.endsWith('/watches')) {
            final body = jsonDecode(r.body) as Map<String, dynamic>;
            watches.add({
              'id': 'two',
              ...body,
              'cursors': <String, dynamic>{},
              'rules': [],
              'recent_mints': 0,
            });
            return http.Response('{"id":"two"}', 200);
          }
          if (r.url.path.endsWith('/copy-mints')) {
            return http.Response(
              jsonEncode({
                'enabled': true,
                'networks': [
                  {'chain_id': 4663, 'name': 'Robinhood'},
                ],
                'watches': watches,
              }),
              200,
            );
          }
          if (watches.length == 2) {
            return http.Response('{"detail":"Activity delayed"}', 503);
          }
          return http.Response(
            '{"events":[],"total":0,"copied_mints":0,"spent_wei":"0"}',
            200,
          );
        }),
      );
      await api.login('member', 'password');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: MaterialApp(
            theme: MintlyTheme.light(),
            home: const CopyMintsScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'First');
      await tester.pump();
      await tester.tap(find.byTooltip('Follow another wallet'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byWidgetPredicate(
          (w) => w is TextField && w.decoration?.labelText == 'Wallet address',
        ),
        '0x${'2' * 40}',
      );
      await tester.enterText(
        find.byWidgetPredicate(
          (w) =>
              w is TextField && w.decoration?.labelText == 'Name this wallet',
        ),
        'Second source',
      );
      await tester.ensureVisible(find.text('Follow wallet'));
      await tester.tap(find.text('Follow wallet'));
      await tester.pumpAndSettle();
      expect(watches.length, 2);
      await tester.scrollUntilVisible(
        find.text('2 wallets followed'),
        -250,
        scrollable: find
            .byWidgetPredicate(
              (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
            )
            .last,
      );
      expect(find.text('2 wallets followed'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.text('Second source'),
        250,
        scrollable: find
            .byWidgetPredicate(
              (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
            )
            .last,
      );
      expect(find.text('Second source'), findsOneWidget);
      expect(watches.first['address'], '0x${'1' * 40}');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'phrase selects account 2 and submits only its key with a new wallet identity',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, dynamic>? sent;
      final api = ApiService(
        client: MockClient((r) async {
          if (r.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          if (r.url.path.endsWith('/wallets')) return http.Response('[]', 200);
          if (r.url.path.endsWith('/config')) {
            return http.Response(
              '{"chain_id":4663,"automatic_collection_selection":true,"phrase_wallet_setup":true}',
              200,
            );
          }
          sent = jsonDecode(r.body) as Map<String, dynamic>;
          expect(r.body.contains(phrase), isFalse);
          return http.Response(
            jsonEncode({
              'id': sent!['request_id'],
              'wallet_id': 'new-wallet',
              'account': sent!['account_address'],
            }),
            200,
          );
        }),
      );
      await api.login('member', 'password');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiServiceProvider.overrideWith((ref) => api),
            walletSecretResolverProvider.overrideWith(
              (ref) =>
                  (input) async => resolveWalletSecret(input),
            ),
          ],
          child: const MaterialApp(home: CustodyImportScreen()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byWidgetPredicate(
          (w) => w is TextField && w.decoration?.labelText == 'Account number',
        ),
        '2',
      );
      await tester.enterText(
        find.byKey(const Key('custody-recovery-phrase')),
        phrase,
      );
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(
        find.text('0x70997970c51812dc3a010c7d01b50e0d17dc79c8'),
        findsOneWidget,
      );
      await tester.enterText(find.byKey(const Key('custody-budget')), '0.001');
      await tester.enterText(
        find.byKey(const Key('custody-password')),
        'password',
      );
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      await tester.tap(find.text('Import wallet'));
      await tester.pumpAndSettle();
      expect(sent?.containsKey('wallet_id'), isFalse);
      expect(
        sent?['account_address'],
        '0x70997970c51812dc3a010c7d01b50e0d17dc79c8',
      );
      expect(
        sent?['private_key'],
        '59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d',
      );
      expect(tester.takeException(), isNull);
    },
  );
}
