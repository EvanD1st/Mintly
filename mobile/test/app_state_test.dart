import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/queue_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

const savedPlan = <String, dynamic>{
  'id': 'saved-plan',
  'collection_name': 'Saved collection',
  'opensea_url': 'https://opensea.io/collection/saved-collection',
  'chain': 'robinhood',
  'contract_address': '0x1111111111111111111111111111111111111111',
  'wallet_address': '0x2222222222222222222222222222222222222222',
  'status': 'ready_for_approval',
  'status_note': 'Ready for approval',
  'price_eth': '0.0001',
};

http.Response liveResponse(http.Request request) {
  final path = request.url.path;
  if (path.endsWith('/auth/login')) {
    return http.Response(jsonEncode({
      'token': 'test-session',
      'user': {'username': 'member', 'role': 'member', 'must_change_password': false},
    }), 200);
  }
  expect(request.headers['Authorization'], 'Bearer test-session');
  if (path.endsWith('/drops')) {
    return http.Response(jsonEncode({'drops': [{'id': 'live-drop', 'name': 'Live drop'}]}), 200);
  }
  if (path.endsWith('/tasks/queue')) return http.Response('{"tasks":[]}', 200);
  if (path.endsWith('/mint-plans')) return http.Response(jsonEncode([savedPlan]), 200);
  if (path.endsWith('/mint-permissions')) return http.Response('[]', 200);
  if (path.endsWith('/activity')) return http.Response('[{"id":"live-activity"}]', 200);
  throw StateError('Unexpected request: ${request.method} $path');
}

void main() {
  testWidgets('permission failure keeps saved plans visible and reports the failed section', (tester) async {
    var permissionsFail = true;
    final api = ApiService(client: MockClient((request) async {
      if (permissionsFail && request.url.path.endsWith('/mint-permissions')) {
        return http.Response('{}', 500);
      }
      return liveResponse(request);
    }));
    await api.login('member', 'password');
    final notifier = MintlyNotifier(api);
    await notifier.loadInitialData();
    expect(notifier.state.mintPlans.single.id, 'saved-plan');
    expect(notifier.state.drops.single.id, 'live-drop');
    expect(notifier.state.activities.single.id, 'live-activity');
    expect(notifier.state.mintPermissions, isEmpty);
    expect(notifier.state.error, contains('Mint permissions:'));
    expect(notifier.state.isLoading, isFalse);

    await tester.pumpWidget(ProviderScope(overrides: [
      apiServiceProvider.overrideWith((ref) => api),
      mintlyProvider.overrideWith((ref) => notifier),
    ], child: const MaterialApp(home: Scaffold(body: QueueScreen()))));
    expect(find.text('Saved collection'), findsOneWidget);
    expect(find.textContaining('Mint permissions:'), findsOneWidget);
    expect(find.text('No mint plans yet'), findsNothing);
    expect(find.text('Quote automatic mint'), findsNothing);

    permissionsFail = false;
    await notifier.loadInitialData();
    await tester.pump();
    expect(notifier.state.error, isNull);
    expect(find.text('Saved collection'), findsOneWidget);
    expect(find.textContaining('Mint permissions:'), findsNothing);
  });

  test('failed plan refresh preserves previously loaded plans', () async {
    var plansFail = false;
    final api = ApiService(client: MockClient((request) async {
      if (plansFail && request.url.path.endsWith('/mint-plans')) return http.Response('{}', 500);
      return liveResponse(request);
    }));
    await api.login('member', 'password');
    final notifier = MintlyNotifier(api);
    await notifier.loadInitialData();
    plansFail = true;
    await notifier.loadInitialData();
    expect(notifier.state.mintPlans.single.id, 'saved-plan');
    expect(notifier.state.error, contains('Mint plans:'));
    notifier.dispose();
    api.dispose();
  });

  test('successful import remains visible when the follow-up list fails', () async {
    final api = ApiService(client: MockClient((request) async {
      if (request.url.path.endsWith('/mint-plans')) {
        if (request.method == 'POST') return http.Response(jsonEncode(savedPlan), 200);
        return http.Response('{}', 500);
      }
      return liveResponse(request);
    }));
    await api.login('member', 'password');
    final notifier = MintlyNotifier(api);
    await notifier.importOpenSeaMint(savedPlan['opensea_url'] as String);
    expect(notifier.state.mintPlans.single.id, 'saved-plan');
    expect(notifier.state.error, contains('Mint plans:'));
    // Reimporting updates the same plan rather than making duplicate cards.
    await notifier.importOpenSeaMint(savedPlan['opensea_url'] as String);
    expect(notifier.state.mintPlans.length, 1);
    notifier.dispose();
    api.dispose();
  });

  test('failed import never creates a mint plan', () async {
    final api = ApiService(client: MockClient((request) async {
      if (request.method == 'POST' && request.url.path.endsWith('/mint-plans')) {
        return http.Response('{"detail":"This wallet is ineligible"}', 400);
      }
      return liveResponse(request);
    }));
    await api.login('member', 'password');
    final notifier = MintlyNotifier(api);
    await expectLater(notifier.importOpenSeaMint(savedPlan['opensea_url'] as String), throwsA(isA<ApiException>()));
    expect(notifier.state.mintPlans, isEmpty);
    notifier.dispose();
    api.dispose();
  });
}
