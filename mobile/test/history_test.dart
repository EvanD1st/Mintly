import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/history_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  for (final chain in ['Ethereum', 'Base']) {
    testWidgets(
      '$chain actual spend does not misattribute additional network fees',
      (tester) async {
        final api = ApiService(
          client: MockClient((request) async {
            if (request.url.path.endsWith('/auth/login')) {
              return http.Response(
                '{"token":"test","user":{"username":"member"}}',
                200,
              );
            }
            expect(request.method, 'GET');
            if (request.url.path.endsWith('/artwork')) {
              return http.Response('{"image_url":null}', 200);
            }
            return http.Response(
              jsonEncode({
                'records': [
                  {
                    'id': 'task',
                    'drop_name': 'Receipt collection',
                    'status': 'confirmed',
                    'chain': chain,
                    'quantity': 1,
                    'created_at': '2026-10-11T10:00:00Z',
                    'actual_gas_used': '21000',
                    'actual_effective_gas_price': '1000000000',
                    'actual_total_cost_wei': chain == 'Base'
                        ? '26000000000000'
                        : '21000000000000',
                  },
                ],
                'next_offset': null,
              }),
              200,
            );
          }),
        );
        await api.login('member', 'password');
        await tester.pumpWidget(
          ProviderScope(
            overrides: [apiServiceProvider.overrideWith((ref) => api)],
            child: const MaterialApp(
              home: HistoryScreen(initialSection: 'mints'),
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('View details'));
        await tester.pumpAndSettle();
        if (chain == 'Base') {
          expect(find.text('Execution gas'), findsOneWidget);
          expect(find.text('0.000026 ETH'), findsOneWidget);
          expect(find.text('Mint value'), findsNothing);
          expect(find.text('Free'), findsNothing);
          expect(
            find.text('Additional network fees are included in the total.'),
            findsOneWidget,
          );
        } else {
          expect(find.text('Network fee'), findsOneWidget);
          expect(find.text('Mint value'), findsOneWidget);
          expect(find.text('Free'), findsOneWidget);
        }
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'all activity uses independent cursors and shows copied tasks once',
    (tester) async {
      tester.view.physicalSize = const Size(390, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final reads = <String>[];
      final api = ApiService(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          expect(
            request.method,
            'GET',
          ); // Viewing activity never authorizes a mint.
          final section = request.url.path.endsWith('/copy-mints/activity')
              ? 'copies'
              : request.url.queryParameters['section'];
          final offset = request.url.queryParameters['offset'];
          reads.add('$section:$offset');
          if (request.url.path.endsWith('/artwork')) {
            return http.Response('{"image_url":null}', 200);
          }
          final second = offset != '0';
          Map<String, dynamic> response;
          if (section == 'mints') {
            response = {
              'records': [
                {
                  'id': second ? 'task-two' : 'task-one',
                  'drop_name': second
                      ? 'Second collection'
                      : 'Copied collection',
                  'chain': 'Base',
                  'quantity': 1,
                  'status': second ? 'submitted' : 'confirmed',
                  'created_at': second
                      ? '2026-10-11T09:59:00Z'
                      : '2026-10-11T10:01:00Z',
                  'actual_total_cost_wei': second ? null : '30000000000000',
                },
              ],
              'next_offset': second ? null : 1,
            };
          } else if (section == 'copies') {
            response = {
              'events': [
                {
                  'id': second ? 'event-two' : 'event-one',
                  'task_id': second ? 'task-two' : 'task-one',
                  'wallet_label': 'Joe',
                  'status': second ? 'submitted' : 'confirmed',
                  'observed_at': '2026-10-11T10:00:00Z',
                  'observation': {
                    'name': 'Duplicate source record',
                    'chain': 'Base',
                  },
                },
                {
                  'id': second ? 'skipped-two' : 'skipped-one',
                  'wallet_label': 'Joe',
                  'status': 'skipped',
                  'note': 'Remaining budget below required amount.',
                  'observed_at': second
                      ? '2026-10-11T08:40:00Z'
                      : '2026-10-11T09:00:00Z',
                  'observation': {
                    'name': second
                        ? 'Older skipped collection'
                        : 'Skipped collection',
                    'chain': 'Base',
                  },
                },
              ],
              'next_offset': second ? null : 2,
            };
          } else {
            expect(section, 'activity');
            response = {
              'records': [
                {
                  'id': 'update',
                  'label': 'Copy settings updated',
                  'recorded_at': '2026-10-11T10:02:00Z',
                  'detail': 'Preferences saved.',
                },
              ],
              'next_offset': null,
            };
          }
          return http.Response(jsonEncode(response), 200);
        }),
      );
      await api.login('member', 'password');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: const MaterialApp(home: HistoryScreen()),
        ),
      );
      await tester.pumpAndSettle();
      expect(reads, containsAll(['mints:0', 'copies:0', 'activity:0']));
      expect(find.text('Copied collection'), findsOneWidget);
      expect(find.text('Duplicate source record'), findsNothing);
      expect(find.text('1 NFT · From Joe'), findsOneWidget);
      expect(find.text('Skipped collection'), findsOneWidget);
      expect(find.text('Copy settings updated'), findsOneWidget);
      await tester.ensureVisible(find.text('Load more'));
      await tester.tap(find.text('Load more'));
      await tester.pumpAndSettle();
      expect(reads, containsAll(['mints:1', 'copies:2']));
      expect(reads.where((r) => r == 'activity:0').length, 1);
      expect(find.text('Copied collection'), findsOneWidget);
      expect(find.text('Second collection'), findsOneWidget);
      expect(find.text('Duplicate source record'), findsNothing);
      expect(find.text('Older skipped collection'), findsOneWidget);
      expect(find.text('Load more'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'history paginates removed records and refreshes in-flight mint receipts',
    (tester) async {
      var mintReads = 0;
      final offsets = <String>[];
      final api = ApiService(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          expect(request.headers['Authorization'], 'Bearer test');
          expect(request.url.path.endsWith('/history'), isTrue);
          final section = request.url.queryParameters['section'];
          final offset = request.url.queryParameters['offset'];
          offsets.add('$section:$offset');
          if (section == 'mints') {
            mintReads++;
            return http.Response(
              jsonEncode({
                'records': [
                  {
                    'id': 'task',
                    'drop_name': 'Removed automatic mint',
                    'status': mintReads == 1 ? 'submitted' : 'confirmed',
                    'transaction_hash': '0xabc',
                    'recoveries': [
                      {
                        'status': 'submitted',
                        'nonce': 7,
                        'previous_hash': '0xoriginal',
                        'replacement_hash': '0xreplacement',
                        'authorized_at': '2026-10-04T09:00:00Z',
                        'expires_at': '2026-10-04T09:20:00Z',
                      },
                    ],
                    'quantity': 1,
                    'chain': 'Robinhood Chain',
                    'archived_at': '2026-10-04T10:00:00Z',
                    'actual_total_cost_wei': mintReads == 1 ? null : 1234,
                  },
                ],
                'next_offset': null,
              }),
              200,
            );
          }
          return http.Response(
            jsonEncode({
              'records': [
                {
                  'id': offset == '0' ? 'removed' : 'saved',
                  'event': offset == '0' ? 'removed' : 'saved',
                  'snapshot': {
                    'collection_name': offset == '0'
                        ? 'Removed plan'
                        : 'Original plan',
                    'quantity': 2,
                    'chain': 'Robinhood Chain',
                  },
                },
              ],
              'next_offset': offset == '0' ? 1 : null,
            }),
            200,
          );
        }),
      );
      await api.login('member', 'password');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: const MaterialApp(
            home: HistoryScreen(initialSection: 'mints'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Pending'), findsOneWidget);
      expect(find.textContaining('Transaction: 0xabc'), findsNothing);
      await tester.tap(find.text('View details'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Approval & recovery history'));
      await tester.pumpAndSettle();
      expect(find.text('Status: submitted'), findsOneWidget);
      expect(find.textContaining('Transaction: 0xabc'), findsOneWidget);
      expect(find.text('Same-nonce recovery: submitted'), findsOneWidget);
      expect(find.text('Original transaction: 0xoriginal'), findsOneWidget);
      expect(
        find.text('Replacement transaction: 0xreplacement'),
        findsOneWidget,
      );
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView), const Offset(0, 350));
      await tester.pumpAndSettle();
      expect(find.text('Confirmed'), findsOneWidget);
      expect(find.text('Total spent'), findsOneWidget);
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Plan history').last);
      await tester.pumpAndSettle();
      expect(find.text('Removed plan'), findsOneWidget);
      await tester.tap(find.text('Load more'));
      await tester.pumpAndSettle();
      expect(find.text('Original plan'), findsOneWidget);
      expect(find.text('Removed plan'), findsOneWidget);
      expect(offsets, contains('plans:1'));
      expect(tester.takeException(), isNull);
    },
  );
}
