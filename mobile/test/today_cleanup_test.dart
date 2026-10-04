import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/discover_screen.dart';
import 'package:mintly/screens/queue_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

Future<ProviderContainer> dataFor(String role, {bool canRevoke = false}) async {
  bool removed = false;
  final api = ApiService(
    client: MockClient((request) async {
      dynamic result;
      if (request.url.path.endsWith('/auth/login')) {
        result = {
          'token': 'test',
          'user': {'username': role, 'role': role},
        };
      } else if (request.method == 'DELETE') {
        expect(request.url.path.endsWith('/drops/drop'), isTrue);
        removed = true;
        result = {'removed': true};
      } else if (request.url.path.endsWith('/drops')) {
        result = {
          'source_status_text': '@lakzonevn feed awaiting an X session',
          'drops': removed
              ? []
              : [
                  {
                    'id': 'drop',
                    'name': 'Existing drop',
                    'chain': 'Base',
                    'stages': [],
                  },
                ],
        };
      } else if (request.url.path.endsWith('/tasks/queue')) {
        result = {'tasks': []};
      } else if (request.url.path.endsWith('/mint-permissions')) {
        result = [
          {
            'id': 'permission',
            'status': 'cancelled',
            'note': 'Cancelled in Mintly',
            'can_revoke': canRevoke,
          },
        ];
      } else {
        result = [];
      }
      return http.Response(
        jsonEncode(result),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
  await api.login(role, 'test');
  final container = ProviderContainer(
    overrides: [apiServiceProvider.overrideWith((ref) => api)],
  );
  await container.read(mintlyProvider.notifier).loadInitialData();
  return container;
}

void main() {
  testWidgets(
    'Today removal stays removed after refresh and hides session notices from members',
    (tester) async {
      final container = await dataFor('member');
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: DiscoverScreen())),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('awaiting an X session'), findsNothing);
      expect(find.text('@lakzonevn drops'), findsNothing);
      expect(find.text('Existing drop'), findsOneWidget);
      await tester.tap(find.byTooltip('Remove drop'));
      await tester.pumpAndSettle();
      expect(find.text('Existing drop'), findsNothing);
    expect(container.read(mintlyProvider).selectedDrop, isNull);
      await container.read(mintlyProvider.notifier).loadInitialData();
      await tester.pumpAndSettle();
      expect(find.text('Existing drop'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('admin retains the X source notice', (tester) async {
    final container = await dataFor('admin');
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: Scaffold(body: DiscoverScreen())),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('@lakzonevn drops'), findsOneWidget);
    expect(find.textContaining('awaiting an X session'), findsOneWidget);
  });
  for (final canRevoke in [false, true]) {
    testWidgets(
      'cancelled notice stays out of Mint plans; revocation=$canRevoke',
      (tester) async {
        final container = await dataFor('member', canRevoke: canRevoke);
        addTearDown(container.dispose);
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: const MaterialApp(home: Scaffold(body: QueueScreen())),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Automatic mint: cancelled'), findsNothing);
        expect(find.text('Cancelled in Mintly'), findsNothing);
        expect(find.text('Mint plans'), findsOneWidget);
        expect(
          find.text('Revoke on-chain'),
          canRevoke ? findsOneWidget : findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
}
