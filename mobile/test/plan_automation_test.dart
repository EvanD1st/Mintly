import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/queue_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  testWidgets('plan opens exact automatic review and removal refreshes visible queue', (tester) async {
    tester.view.physicalSize = const Size(900, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var removed = false;
    var contexts = 0;
    const account = '0x1111111111111111111111111111111111111111';
    final start = DateTime.now().toUtc().add(const Duration(hours: 1));
    final plan = {'id': 'plan', 'wallet_id': 'wallet', 'wallet_address': account,
      'collection_name': 'Plan collection', 'contract_address': account, 'chain': 'Robinhood Chain',
      'opensea_url': 'https://opensea.io/collection/example', 'quantity': 2, 'status': 'scheduled',
      'status_note': 'Public mint upcoming', 'stage_name': 'Exact public stage',
      'starts_at': start.toIso8601String(), 'ends_at': start.add(const Duration(hours: 1)).toIso8601String()};
    final api = ApiService(client: MockClient((request) async {
      final path = request.url.path;
      dynamic result;
      if (path.endsWith('/auth/login')) {
        result = {'token': 'test', 'user': {'username': 'member'}};
      } else if (path.endsWith('/automatic-context')) {
        expect(path, endsWith('/mint-plans/plan/automatic-context'));
        contexts++;
        result = {'plan': plan, 'mint_kind': 'public', 'drop': {
          'id': 'exact-drop', 'name': 'Plan collection', 'chain': 'Robinhood Chain', 'chain_id': 4663,
          'contract_address': account, 'mint_page_url': plan['opensea_url'], 'is_supported_integration': true,
          'stages': [{'id': 'exact-stage', 'drop_id': 'exact-drop', 'stage_name': 'Exact public stage',
            'start_time_utc': start.toIso8601String(), 'end_time_utc': plan['ends_at'],
            'price_wei': 0, 'price_eth_str': '0', 'limit_per_wallet': 2}],
        }};
      } else if (path.endsWith('/automatic/policies')) {
        result = [{'id': 'policy', 'wallet_id': 'wallet', 'account': account, 'chain_id': 4663, 'status': 'enabled'}];
      } else if (path.endsWith('/mint-plans/plan') && request.method == 'DELETE') {
        removed = true;
        result = {'status': 'removed', 'in_flight': false, 'history_retained': true};
      } else if (path.endsWith('/mint-plans')) {
        result = removed ? [] : [plan];
      } else if (path.endsWith('/tasks/queue')) {
        result = {'tasks': []};
      } else if (path.endsWith('/drops')) {
        result = {'drops': []};
      } else if (path.endsWith('/activity') || path.endsWith('/mint-permissions')) {
        result = [];
      } else {
        result = {};
      }
      return http.Response(jsonEncode(result), 200);
    }));
    await api.login('member', 'password');
    final container = ProviderContainer(overrides: [apiServiceProvider.overrideWith((ref) => api)]);
    addTearDown(container.dispose);
    await container.read(mintlyProvider.notifier).loadInitialData();
    await tester.pumpWidget(UncontrolledProviderScope(container: container,
      child: const MaterialApp(home: Scaffold(body: QueueScreen()))));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Set up automatic mint'));
    await tester.pumpAndSettle();
    expect(contexts, 1);
    expect(find.text('Review automatic mint'), findsOneWidget);
    expect(find.text('Exact public stage'), findsOneWidget);
    expect(find.text(account), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField).first).controller!.text, '2');
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();
    expect(removed, isTrue);
    expect(container.read(mintlyProvider).mintPlans, isEmpty);
    expect(find.textContaining('record saved in Settings → History.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
