import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/discover_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  test(
    'an unavailable selected wallet falls back to the owned default',
    () async {
      final selections = <String?>[];
      final api = ApiService(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/login')) {
            return http.Response(
              jsonEncode({
                'token': 'test',
                'user': {'id': 'owner', 'username': 'member', 'role': 'member'},
              }),
              200,
            );
          }
          selections.add(request.url.queryParameters['wallet_id']);
          if (request.url.queryParameters['wallet_id'] == 'archived') {
            return http.Response(
              jsonEncode({'detail': 'Wallet not found.'}),
              404,
            );
          }
          return http.Response(
            jsonEncode({
              'selected_wallet_id': 'default',
              'wallets': [],
              'drops': [],
            }),
            200,
          );
        }),
      );
      await api.login('member', 'password');
      api.selectedFeedWallet = 'archived';
      expect(await api.fetchDrops('all'), isEmpty);
      expect(selections, ['archived', null]);
      expect(api.selectedFeedWallet, 'default');
    },
  );
  for (final status in [
    'eligible',
    'not_eligible',
    'unverified',
    'stale',
    'refreshing_history',
  ]) {
    testWidgets('Today selected wallet card has safe setup state: $status', (
      tester,
    ) async {
      final calls = <String>[];
      final now = DateTime.now().toUtc();
      final api = ApiService(
        client: MockClient((request) async {
          calls.add(request.url.path);
          dynamic data = [];
          if (request.url.path.endsWith('/auth/login')) {
            data = {
              'token': 'test',
              'user': {'id': 'owner', 'username': 'member', 'role': 'member'},
            };
          } else if (request.url.path.endsWith('/drops')) {
            expect(request.url.queryParameters['daily_only'], 'true');
            data = {
              'selected_wallet_id': 'wallet',
              'wallets': [
                {
                  'id': 'wallet',
                  'label': 'Mint wallet',
                  'address': '0x${'1' * 40}',
                },
              ],
              'drops': [
                {
                  'id': 'drop',
                  'name': 'Captured collection',
                  'chain': 'Base',
                  'chain_id': 8453,
                  'mint_page_url': 'https://opensea.io/collection/example',
                  'source_price_text': 'Free / 0.001 ETH',
                  'source_time_text': '2pm UTC',
                  'wallet_check': {
                    'status': status == 'stale'
                        ? 'eligible'
                        : status == 'refreshing_history'
                        ? 'unverified'
                        : status,
                    'checked_at': now
                        .subtract(Duration(seconds: status == 'stale' ? 90 : 0))
                        .toIso8601String(),
                    'setup_enabled': status == 'eligible' || status == 'stale',
                    if (status == 'refreshing_history') ...{
                      'last_status': 'eligible',
                      'refreshing': true,
                      'last_recommended_stage': {
                        'id': 'public',
                        'name': 'Public',
                        'price_wei': '0',
                        'starts_at': now.toIso8601String(),
                      },
                    },
                    'recommended_stage':
                        status == 'eligible' || status == 'stale'
                        ? {
                            'id': 'public',
                            'name': 'Public',
                            'starts_at': now
                                .add(const Duration(hours: 1))
                                .toIso8601String(),
                            'price_wei': '0',
                          }
                        : null,
                    'stages': [],
                  },
                },
              ],
            };
          } else if (request.url.path.endsWith('/wallet-checks')) {
            final body = jsonDecode(request.body) as Map;
            expect(body['wallet_id'], 'wallet');
            expect(body['drop_ids'], ['drop']);
            data = {'queued': 1};
          } else if (request.url.path.endsWith('/artwork')) {
            data = {'image_url': null};
          } else if (request.url.path.endsWith('/tasks/queue')) {
            data = {'tasks': []};
          }
          return http.Response(jsonEncode(data), 200);
        }),
      );
      await api.login('member', 'password');
      final container = ProviderContainer(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
      );
      await container.read(mintlyProvider.notifier).loadInitialData();
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: DiscoverScreen())),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Captured collection'), findsOneWidget);
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Set up automatic mint'),
      );
      expect(button.onPressed != null, status == 'eligible');
      if (status == 'stale' || status == 'unverified') {
        expect(find.text('Not verified'), findsOneWidget);
      }
      if (status == 'refreshing_history') {
        expect(find.text('Last checked: eligible'), findsOneWidget);
        expect(find.textContaining('Refreshing eligibility'), findsOneWidget);
        expect(find.text('Not verified'), findsNothing);
      }
      if (status != 'eligible' && status != 'refreshing_history') {
        expect(find.textContaining('Source price:'), findsOneWidget);
      }
      final polls = calls.where((p) => p.endsWith('/wallet-checks')).length;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump(const Duration(seconds: 30));
      expect(calls.where((p) => p.endsWith('/wallet-checks')).length, polls);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      expect(calls.where((p) => p.endsWith('/prepare-plan')), isEmpty);
      await tester.pumpWidget(const SizedBox.shrink());
      container.dispose();
      expect(tester.takeException(), isNull);
    });
  }
}
