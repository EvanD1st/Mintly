import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/copy_mints_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'package:mintly/widgets/network_budget_card.dart';

void main() {
  testWidgets(
    'six network budget dropdown preserves native units and exact amounts',
    (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = ApiService(
        client: MockClient((r) async {
          if (r.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          expect(r.url.queryParameters['native_currencies'], 'true');
          return http.Response(
            jsonEncode([
              for (final chain in [1, 8453, 4663, 999, 33139, 57073])
                {
                  'id': 'grant$chain',
                  'chain_id': chain,
                  'status': 'enabled',
                  'expires_at': DateTime.now()
                      .toUtc()
                      .add(const Duration(days: 1))
                      .toIso8601String(),
                  'remaining_wei': chain == 33139
                      ? '12500000000000000001'
                      : chain == 999
                      ? '4200000000000000000'
                      : '4000000000000000',
                  'spent_wei': '0',
                  'reserved_wei': '0',
                },
            ]),
            200,
          );
        }),
      );
      await api.login('member', 'test');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: MaterialApp(
            theme: MintlyTheme.dark(),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: TextScaler.linear(1.4)),
              child: child!,
            ),
            home: const Scaffold(body: NetworkBudgetCard()),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Available budget by network'));
      await tester.pumpAndSettle();
      for (final label in [
        'Ethereum',
        'Base',
        'Robinhood',
        'HyperEVM',
        'ApeChain',
        'Ink',
      ]) {
        expect(find.text(label), findsWidgets);
      }
      await tester.tap(find.text('ApeChain').last);
      await tester.pumpAndSettle();
      expect(find.text('APE 12.5…'), findsOneWidget);
      expect(find.byTooltip('12.500000000000000001 APE'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('copy consent approves only selected native currency grants', (
    tester,
  ) async {
    Map<String, dynamic>? sent;
    final api = ApiService(
      client: MockClient((r) async {
        if (r.url.path.endsWith('/auth/login')) {
          return http.Response(
            '{"token":"test","user":{"username":"member"}}',
            200,
          );
        }
        dynamic data;
        if (r.url.path.endsWith('/automatic/policies')) {
          data = [
            for (final chain in [1, 8453, 4663, 999, 33139, 57073])
              {
                'id': 'grant$chain',
                'wallet_id': 'receiver',
                'account': '0x${'2' * 40}',
                'chain_id': chain,
                'status': 'enabled',
                'expires_at': DateTime.now()
                    .toUtc()
                    .add(const Duration(days: 8))
                    .toIso8601String(),
                'remaining_wei': '12500000000000000000',
                'scope': {
                  'mint_kinds': ['public', 'allowlist', 'signed'],
                  'max_task_wei': '1000000000000000000',
                },
              },
          ];
        } else if (r.url.path.endsWith('/wallets')) {
          data = [
            {
              'id': 'receiver',
              'label': 'Receiving wallet',
              'address': '0x${'2' * 40}',
            },
          ];
        } else {
          sent = jsonDecode(r.body) as Map<String, dynamic>;
          data = {
            'id': sent!['request_id'],
            'status': 'active',
            'rules': [
              for (final id in sent!['grant_ids'] as List)
                {
                  'snapshot': {'grant_id': id},
                },
            ],
          };
        }
        return http.Response(jsonEncode(data), 200);
      }),
    );
    await api.login('member', 'test');
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
        child: MaterialApp(
          theme: MintlyTheme.dark(),
          home: CopySettingsScreen(
            watch: {
              'id': 'watch',
              'address': '0x${'1' * 40}',
              'chains': [1, 8453, 4663, 999, 33139, 57073],
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final receiving = find.byType(DropdownButtonFormField<String>).first;
    await tester.tap(receiving);
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('Receiving wallet ·').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('copy-currency-ETH')));
    await tester.tap(find.byKey(const ValueKey('copy-currency-ETH')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('HYPE').last);
    await tester.pumpAndSettle();
    expect(find.text('HyperEVM'), findsOneWidget);
    for (final entry in [
      ('Max mint price per NFT', '0.01'),
      ('Gas spending limit', '0.001'),
      ('Total copy budget', '12.5'),
    ]) {
      final field = find.byWidgetPredicate(
        (w) => w is TextField && w.decoration?.labelText == entry.$1,
      );
      await tester.ensureVisible(field);
      await tester.pumpAndSettle();
      await tester.enterText(field, entry.$2);
      await tester.pump();
    }
    final consent = find.byType(CheckboxListTile);
    await tester.ensureVisible(consent);
    await tester.pumpAndSettle();
    await tester.tap(consent);
    await tester.pumpAndSettle();
    final submit = find.text('Enable copy minting');
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(sent?['native_symbol'], 'HYPE');
    expect(sent?['grant_ids'], ['grant999']);
    expect(sent?['budget_eth'], '12.5');
    expect(sent?['consent'], true);
    expect(tester.takeException(), isNull);
  });
}
