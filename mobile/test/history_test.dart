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
          child: const MaterialApp(home: HistoryScreen()),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Status: submitted'), findsOneWidget);
      expect(find.textContaining('Transaction: 0xabc'), findsOneWidget);
      expect(find.text('Same-nonce recovery: submitted'), findsOneWidget);
      expect(find.text('Original transaction: 0xoriginal'), findsOneWidget);
      expect(find.text('Replacement transaction: 0xreplacement'), findsOneWidget);
      await tester.drag(find.byType(ListView), const Offset(0, 350));
      await tester.pumpAndSettle();
      expect(find.text('Status: confirmed'), findsOneWidget);
      expect(find.textContaining('Actual spend:'), findsOneWidget);
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
