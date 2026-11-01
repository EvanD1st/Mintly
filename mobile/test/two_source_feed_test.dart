import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/discover_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/push_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  testWidgets(
    'merged sources keep Minted and acknowledge exact displayed editions',
    (tester) async {
      tester.view.physicalSize = const Size(900, 2200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var seen = false;
      Map? ack;
      final api = ApiService(
        client: MockClient((request) async {
          final path = request.url.path;
          dynamic result = [];
          if (path.endsWith('/auth/login')) {
            result = {
              'token': 'test',
              'user': {'id': 'member', 'username': 'member', 'role': 'member'},
            };
          } else if (path.endsWith('/drops/seen')) {
            ack = jsonDecode(request.body) as Map;
            seen = true;
            result = {'seen': true};
          } else if (path.endsWith('/drops')) {
            result = {
              'selected_wallet_id': 'wallet',
              'source_status_text':
                  '@lakzonevn connected · @Cassio_Sch refresh delayed',
              'feed_status_text':
                  '@lakzonevn list available · @Cassio_Sch refresh delayed',
              'wallets': [
                {
                  'id': 'wallet',
                  'label': 'Mint wallet',
                  'address': '0x1111111111111111111111111111111111111111',
                },
              ],
              'editions': [
                {'id': 'first', 'content_hash': 'hash-one'},
                {'id': 'second', 'content_hash': 'hash-two'},
              ],
              'drops': [
                {
                  'id': 'shared-card',
                  'name': 'Shared collection',
                  'chain': 'Base',
                  'chain_id': 8453,
                  'mint_page_url': 'https://opensea.io/collection/shared',
                  'additions': seen ? null : 'new',
                  'sources': [
                    {
                      'author': 'lakzonevn',
                      'price': 'Free',
                      'time_wat': '01 Nov 14:00 WAT',
                    },
                    {
                      'author': 'Cassio_Sch',
                      'price': 'Free / 0.001 ETH',
                      'time_wat': '01 Nov 15:00 WAT',
                    },
                  ],
                  'automatic_mint': {
                    'id': 'confirmed-task',
                    'status': 'confirmed',
                    'quantity': 2,
                    'stage_name': 'GTD',
                    'confirmed_at': '2026-11-01T11:16:00Z',
                  },
                },
              ],
            };
          } else if (path.endsWith('/tasks/queue')) {
            result = {'tasks': []};
          } else if (path.endsWith('/artwork')) {
            result = {'image_url': null};
          } else if (path.endsWith('/wallet-checks') ||
              path.endsWith('/prepare-plan') ||
              path.endsWith('/tasks/arm')) {
            fail(
              'A merged confirmed card must not check, prepare or arm again.',
            );
          }
          return http.Response(jsonEncode(result), 200);
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
      expect(find.text('Shared collection'), findsOneWidget);
      expect(find.text('Minted'), findsOneWidget);
      expect(find.text('New addition'), findsOneWidget);
      expect(find.text('@lakzonevn · @Cassio_Sch'), findsOneWidget);
      expect(find.text('Set up automatic mint'), findsNothing);
      await tester.tap(find.text('Source details'));
      await tester.pumpAndSettle();
      expect(find.textContaining('01 Nov 15:00 WAT'), findsOneWidget);
      await tester.tap(find.text('Mark additions as seen'));
      await tester.pumpAndSettle();
      expect(ack, {
        'editions': [
          {'id': 'first', 'content_hash': 'hash-one'},
          {'id': 'second', 'content_hash': 'hash-two'},
        ],
      });
      expect(find.text('New addition'), findsNothing);
      expect(find.text('Minted'), findsOneWidget);
      final push = PushService.instance;
      await push.connect(api);
      final before = push.todayRequests.value;
      push.openToday({'category': 'daily_list', 'user_id': 'foreign'});
      expect(push.todayRequests.value, before);
      push.openToday({'category': 'daily_list', 'user_id': 'member'});
      expect(push.todayRequests.value, before + 1);
      await push.disconnect();
      await tester.pumpWidget(const SizedBox.shrink());
      container.dispose();
      expect(tester.takeException(), isNull);
    },
  );
}
