import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/screens/reliability_screen.dart';

void main() {
  testWidgets('members cannot fetch or see the admin report', (tester) async {
    var reads = 0;
    final api = ApiService(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({
              'token': 'test',
              'user': {'id': 'member', 'username': 'member', 'role': 'member'},
            }),
            200,
          );
        }
        reads++;
        return http.Response('{}', 403);
      }),
    );
    await api.login('member', 'password');
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
        child: const MaterialApp(home: ReliabilityScreen()),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Administrator access required.'), findsOneWidget);
    expect(reads, 0);
  });

  testWidgets('admin sees measured failures and timing with clear coverage', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1000, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = ApiService(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({
              'token': 'test',
              'user': {'id': 'admin', 'username': 'admin', 'role': 'admin'},
            }),
            200,
          );
        }
        return http.Response(
          jsonEncode({
            'eligible_auto_arm_collections': 4,
            'eligible_with_task': 3,
            'eligible_without_task': 1,
            'failures_needing_review': 2,
            'incidents': [
              {
                'reason_code': 'api_access_denied',
                'reason_text': 'OpenSea denied API access.',
                'chain_id': 8453,
                'affected_tasks': 3,
                'last_seen': '2026-11-09T00:00:00Z',
              },
            ],
            'outcomes': {'sold_out': 1},
            'modes': {
              'copy': {
                'tasks': 2,
                'submitted': 2,
                'confirmed': 1,
                'activity_to_submission': {
                  'samples': 2,
                  'p50_seconds': 1.2,
                  'p95_seconds': 2.0,
                },
              },
            },
            'notes': [],
          }),
          200,
        );
      }),
    );
    await api.login('admin', 'password');
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
        child: const MaterialApp(home: ReliabilityScreen()),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Last 24 hours'), findsOneWidget);
    expect(
      find.textContaining('Older opportunities are not included.'),
      findsOneWidget,
    );
    expect(find.textContaining('OpenSea denied API access.'), findsOneWidget);
    expect(
      find.textContaining('Activity detected to submission: 2 samples'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });

  test('report response from a previous account is discarded', () async {
    final response = Completer<http.Response>();
    final requested = Completer<void>();
    final api = ApiService(
      client: MockClient((request) async {
        if (request.url.path.endsWith('/auth/login')) {
          final name = jsonDecode(request.body)['username'];
          return http.Response(
            jsonEncode({
              'token': 'test-$name',
              'user': {
                'id': name,
                'username': name,
                'role': name == 'admin' ? 'admin' : 'member',
              },
            }),
            200,
          );
        }
        requested.complete();
        return response.future;
      }),
    );
    await api.login('admin', 'password');
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWith((ref) => api)],
    );
    addTearDown(container.dispose);
    final provider = reliabilityProvider((api.userId, api.sessionRevision));
    final subscription = container.listen(provider, (_, _) {});
    addTearDown(subscription.close);
    final pending = container.read(provider.future);
    final expectation = expectLater(pending, throwsA(anything));
    await requested.future;
    await api.login('member', 'password');
    response.complete(
      http.Response('{"incidents":[{"private_operator_data":true}]}', 200),
    );
    await expectation;
    expect(api.isAdmin, isFalse);
  });
}
