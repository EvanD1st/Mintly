import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/copy_mints_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'copy_mints_test.dart' show watch, networks;

void main() {
  testWidgets('funding skip has a short network reason and Retry sends one scoped request', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var retries = 0;
    final api = ApiService(client: MockClient((r) async {
      if (r.url.path.endsWith('/auth/login')) {
        return http.Response('{"token":"test","user":{"username":"member"}}', 200);
      }
      dynamic response = {};
      if (r.url.path.endsWith('/copy-mints')) {
        response = {'enabled': true, 'networks': networks, 'watches': [watch]};
      } else if (r.url.path.endsWith('/copy-mints/activity')) {
        response = {'copied_mints': 0, 'spent_wei': '0', 'events': [{
          'id': 'funding-event', 'watch_id': watch['id'], 'wallet_label': watch['label'],
          'observed_at': '2026-10-08T09:00:00Z', 'status': 'skipped', 'task_id': null,
          'retryable': true, 'note': 'Not enough ETH on Base for gas.',
          'observation': {'name': 'Free collection', 'chain': 'Base', 'chain_id': 8453,
            'contract': watch['address'], 'source_quantity': 1, 'price_wei': '0', 'source_hash': '0xsource'},
        }]};
      } else if (r.url.path.endsWith('/events/funding-event/retry')) {
        expect(r.method, 'POST');
        expect(jsonDecode(r.body), isEmpty);
        retries++;
        response = {'status': 'queued', 'task_id': 'same-approved-mint'};
      }
      return http.Response(jsonEncode(response), 200);
    }));
    await api.login('member', 'test');
    await tester.pumpWidget(ProviderScope(overrides: [apiServiceProvider.overrideWith((ref) => api)],
        child: const MaterialApp(home: CopyMintsScreen())));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Activity').last);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Retry'), 150,
        scrollable: find.byWidgetPredicate((w) => w is Scrollable && w.axisDirection == AxisDirection.down).first);
    expect(find.text('Not enough ETH on Base for gas.'), findsOneWidget);
    expect(find.text('Review & copy this mint'), findsNothing);
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(retries, 1);
    expect(tester.takeException(), isNull);
  });

  test('unverified wallet copy approval does not confirm a partial network response', () async {
    final api = ApiService(client: MockClient((r) async => r.url.path.endsWith('/auth/login')
        ? http.Response('{"token":"test","user":{"username":"member"}}', 200)
        : http.Response('{"id":"request","status":"active","rules":[{"snapshot":{"grant_id":"ethereum"}}]}', 200)));
    await api.login('member', 'test');
    await expectLater(api.approveWalletCopyRules('watch', {
      'request_id': 'request', 'grant_ids': ['ethereum', 'base', 'robinhood'],
    }), throwsA(isA<ApiException>()));
  });
}
