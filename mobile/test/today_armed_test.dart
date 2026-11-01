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
  for (final (status, label) in [
    ('armed', 'Armed'),
    ('preparing', 'Preparing mint'),
    ('prepared', 'Mint prepared'),
    ('submitting', 'Submitting mint'),
    ('submitted', 'Mint submitted'),
    ('uncertain', 'Checking transaction'),
    ('confirmed', 'Minted'),
  ]) {
    testWidgets(
      'Today opens existing $status mint without checking eligibility or rearming',
      (tester) async {
        tester.view.physicalSize = const Size(900, 2000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final calls = <String>[];
        var active = true;
        final scheduled = DateTime.now()
            .toUtc()
            .add(const Duration(hours: 1))
            .toIso8601String();
        final api = ApiService(
          client: MockClient((request) async {
            final path = request.url.path;
            calls.add('${request.method} $path');
            dynamic data = [];
            if (path.endsWith('/auth/login')) {
              data = {
                'token': 'test',
                'user': {'username': 'member', 'role': 'member'},
              };
            } else if (path.endsWith('/drops')) {
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
                    'id': 'public-feed-row',
                    'name': 'Villagers',
                    'chain': 'Base',
                    'chain_id': 8453,
                    'mint_page_url': 'https://opensea.io/collection/villagers',
                    // Stale eligibility must never replace the actual task state.
                    'wallet_check': {
                      'status': 'unverified',
                      'setup_enabled': false,
                      'refreshing': true,
                      'note': 'Checking wallet eligibility.',
                    },
                    if (active)
                      'automatic_mint': {
                        'id': 'existing-task',
                        'wallet_id': 'wallet',
                        'status': status,
                        'quantity': 2,
                        'stage_name': 'GTD',
                        'scheduled_for_utc': scheduled,
                        if (status == 'confirmed')
                          'confirmed_at': '2026-11-01T11:16:00Z',
                      },
                  },
                ],
              };
            } else if (path.endsWith('/tasks/queue')) {
              data = {
                'tasks': [
                  {
                    'id': 'existing-task',
                    'wallet_id': 'wallet',
                    'drop_id': 'private-plan-row',
                    'drop_name': 'Villagers',
                    'stage_name': 'GTD',
                    'status': status,
                    'quantity': 2,
                    'scheduled_for_utc': scheduled,
                    'unit_price_eth': '0',
                  },
                  {
                    'id': 'another-task',
                    'drop_name': 'Unrelated mint',
                    'status': 'armed',
                  },
                ],
              };
            } else if (path.endsWith('/artwork')) {
              data = {'image_url': null};
            } else if (path.endsWith('/history')) {
              data = {'records': [], 'next_offset': null};
            } else if (path.endsWith('/automation')) {
              data = {'paused': false};
            } else if (path.endsWith('/wallet-checks')) {
              expect(active, isFalse);
              data = {'queued': 1};
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
        expect(find.text(label), findsOneWidget);
        expect(find.text('Set up automatic mint'), findsNothing);
        expect(
          find.textContaining('Checking wallet eligibility'),
          findsNothing,
        );
        expect(calls.where((c) => c.endsWith('/wallet-checks')), isEmpty);
        expect(find.text('GTD · 2 NFT(s)'), findsOneWidget);
        final minted = status == 'confirmed';
        if (minted) {
          expect(find.text('Confirmed 1 Nov, 12:16 WAT'), findsOneWidget);
          expect(find.textContaining('Scheduled '), findsNothing);
        }
        await tester.tap(
          find.text(minted ? 'View mint history' : 'View automatic mint'),
        );
        await tester.pumpAndSettle();
        if (minted) {
          expect(calls.where((c) => c.endsWith('/history')), isNotEmpty);
        } else {
          expect(find.text('Villagers'), findsOneWidget);
        }
        expect(find.text('Unrelated mint'), findsNothing);
        expect(find.text('Review mint'), findsNothing);
        expect(
          calls.where(
            (c) =>
                c.endsWith('/prepare-plan') ||
                c.endsWith('/tasks/arm') ||
                c.endsWith('/automatic-context'),
          ),
          isEmpty,
        );
        // Returning after a server-side disarm restores the normal checked setup path.
        if (!minted) active = false;
        await tester.pageBack();
        await tester.pumpAndSettle();
        expect(find.text('View automatic mint'), findsNothing);
        if (minted) {
          expect(find.text('Minted'), findsOneWidget);
          expect(find.text('Set up automatic mint'), findsNothing);
          expect(calls.where((c) => c.endsWith('/wallet-checks')), isEmpty);
        } else {
          expect(find.text('Set up automatic mint'), findsOneWidget);
          expect(calls.where((c) => c.endsWith('/wallet-checks')), isNotEmpty);
        }
        await tester.pumpWidget(const SizedBox.shrink());
        container.dispose();
        expect(tester.takeException(), isNull);
      },
    );
  }
}
