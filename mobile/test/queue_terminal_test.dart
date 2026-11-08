import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/queue_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  for (final status in [
    'failed',
    'expired',
    'confirmed',
    'already_minted',
    'armed',
  ]) {
    testWidgets('$status task replaces its linked saved plan only', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(900, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = ApiService(
        client: MockClient((request) async {
          final path = request.url.path;
          dynamic result = [];
          if (path.endsWith('/auth/login')) {
            result = {
              'token': 'test',
              'user': {'username': 'member'},
            };
          } else if (path.endsWith('/mint-plans')) {
            result = [
              {
                'id': 'linked',
                'opensea_url': 'https://opensea.io/collection/art-as-monkey',
                'chain': 'Robinhood Chain',
                'contract_address': '0x1111111111111111111111111111111111111111',
                'wallet_address': '0x2222222222222222222222222222222222222222',
                'status_note': 'The phase ended.',
                'collection_name': 'Art as Monkey',
                'status': 'ended',
              },
              {
                'id': 'other-wallet-plan',
                'opensea_url': 'https://opensea.io/collection/another',
                'chain': 'Robinhood Chain',
                'contract_address': '0x3333333333333333333333333333333333333333',
                'wallet_address': '0x4444444444444444444444444444444444444444',
                'status_note': 'Upcoming mint.',
                'collection_name': 'Other wallet collection',
                'status': 'scheduled',
              },
            ];
          } else if (path.endsWith('/tasks/queue')) {
            result = {
              'tasks': [
                {
                  'id': 'task',
                  'plan_id': 'linked',
                  'status': status,
                  'drop_name': 'Art as Monkey',
                  'scheduled_for_utc': '2026-11-08T20:00:00Z',
                },
              ],
            };
          } else if (path.endsWith('/drops')) {
            result = {'drops': []};
          }
          return http.Response(jsonEncode(result), 200);
        }),
      );
      await api.login('member', 'password');
      final container = ProviderContainer(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
      );
      addTearDown(container.dispose);
      await container.read(mintlyProvider.notifier).loadInitialData();
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: QueueScreen())),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Art as Monkey'), findsOneWidget);
      expect(find.text('Other wallet collection'), findsOneWidget);
      expect(find.text('Review mint'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilterChip, 'Needs approval'));
      await tester.pumpAndSettle();
      expect(find.text('Art as Monkey'), findsNothing);
      expect(find.text('Other wallet collection'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
