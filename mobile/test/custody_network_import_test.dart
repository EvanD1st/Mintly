import 'dart:convert';
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

const networks = [
  {'chain_id': 1, 'name': 'Ethereum'},
  {'chain_id': 8453, 'name': 'Base'},
  {'chain_id': 4663, 'name': 'Robinhood'},
];

Map<String, dynamic> importResponse(Map<String, dynamic> sent) => {
  'id': sent['request_id'],
  'wallet_id': 'new-wallet',
  'account': sent['account_address'],
  'grants': [
    for (final network in (sent['networks'] as List))
      {
        'id': 'grant-${network['chain_id']}',
        'wallet_id': 'new-wallet',
        'account': sent['account_address'],
        'chain_id': network['chain_id'],
      },
  ],
};

void main() {
  test(
    'known relink hold explains the block without echoing arbitrary responses',
    () async {
      const message =
          'A previously signed mint for this wallet is unresolved. Wait for settlement before relinking.';
      final api = ApiService(
        client: MockClient(
          (request) async => request.url.path.endsWith('/auth/login')
              ? http.Response(
                  '{"token":"token","user":{"username":"member"}}',
                  200,
                )
              : http.Response(jsonEncode({'detail': message}), 409),
        ),
      );
      await api.login('member', 'password');
      final payload = <String, dynamic>{
        'private_key': 'test-secret',
        'password': 'password',
      };
      await expectLater(
        api.importCustodyWallet(payload),
        throwsA(
          isA<ApiException>().having((e) => e.message, 'message', message),
        ),
      );
      expect(payload.containsKey('private_key'), isFalse);
      expect(payload.containsKey('password'), isFalse);
    },
  );
  for (final onlyRobinhood in [false, true]) {
  testWidgets(
    'selected networks approve only their budgets: Robinhood only $onlyRobinhood',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, dynamic>? sent;
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
              jsonEncode({
                'chain_id': 4663,
                'automatic_collection_selection': true,
                'phrase_wallet_setup': true,
                'multi_network_import': true,
                'networks': networks,
              }),
              200,
            );
          }
          if (request.url.path.endsWith('/wallets')) {
            return http.Response('[]', 200);
          }
          expect(request.body.contains(phrase), isFalse);
          sent = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response(jsonEncode(importResponse(sent!)), 200);
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
      expect(find.byType(DropdownButtonFormField<int>), findsNothing);
      expect(
        find.text('One wallet · Ethereum · Base · Robinhood'),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(const Key('custody-recovery-phrase')),
        phrase,
      );
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      if (onlyRobinhood) {
        await tester.tap(find.byKey(const Key('custody-select-1')));
        await tester.tap(find.byKey(const Key('custody-select-8453')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('custody-budget-1')), findsNothing);
      } else {
      await tester.enterText(
        find.byKey(const Key('custody-budget-1')),
        '0.001',
      );
      await tester.enterText(
        find.byKey(const Key('custody-budget-8453')),
        '0.002',
      );
      }
      await tester.enterText(
        find.byKey(const Key('custody-budget-4663')),
        '0.003',
      );
      await tester.pump();
      expect(
        find.text('Combined authorized budget: ${onlyRobinhood ? '0.003' : '0.006'} ETH'),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(const Key('custody-password')),
        'password',
      );
      await tester.tap(find.widgetWithText(CheckboxListTile, 'I authorize Mintly to store this account’s encrypted key and mint within my limits.'));
      await tester.pump();
      await tester.tap(find.text('Import wallet'));
      await tester.pumpAndSettle();
      expect(sent?['private_key'], firstKey);
      expect(
        sent?['account_address']?.toLowerCase(),
        firstAddress.toLowerCase(),
      );
      expect(sent?.containsKey('chain_id'), isFalse);
      expect(sent?.containsKey('budget_eth'), isFalse);
      expect(sent?['networks'], [
        if (!onlyRobinhood) {'chain_id': 1, 'budget_eth': '0.001', 'max_task_eth': '0.001'},
        if (!onlyRobinhood) {'chain_id': 8453, 'budget_eth': '0.002', 'max_task_eth': '0.002'},
        {'chain_id': 4663, 'budget_eth': '0.003', 'max_task_eth': '0.003'},
      ]);
      expect(tester.takeException(), isNull);
    },
  );

  }
  for (final failure in [
    'missing',
    'duplicate_chain',
    'duplicate_grant',
    'foreign_wallet',
    'foreign_account',
  ]) {
    test(
      'partial or mismatched $failure network response never confirms and clears secrets',
      () async {
        final payload = <String, dynamic>{
          'request_id': 'request',
          'account_address': firstAddress,
          'private_key': 'test-secret',
          'password': 'password',
          'networks': [
            for (final n in networks) {'chain_id': n['chain_id']},
          ],
        };
        final response = importResponse(payload);
        final grants = response['grants'] as List;
        if (failure == 'missing') grants.removeLast();
        if (failure == 'duplicate_chain') {
          grants[1]['chain_id'] = grants[0]['chain_id'];
        }
        if (failure == 'duplicate_grant') grants[1]['id'] = grants[0]['id'];
        if (failure == 'foreign_wallet') {
          grants[1]['wallet_id'] = 'other-wallet';
        }
        if (failure == 'foreign_account') {
          grants[1]['account'] = 'other-account';
        }
        final api = ApiService(
          client: MockClient(
            (request) async => request.url.path.endsWith('/auth/login')
                ? http.Response(
                    '{"token":"token","user":{"username":"member"}}',
                    200,
                  )
                : http.Response(jsonEncode(response), 200),
          ),
        );
        await api.login('member', 'password');
        await expectLater(
          api.importCustodyWallet(payload),
          throwsA(isA<ApiException>()),
        );
        expect(payload.containsKey('private_key'), isFalse);
        expect(payload.containsKey('password'), isFalse);
      },
    );
  }
}
