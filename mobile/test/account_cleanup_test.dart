import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/account_settings_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/push_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';

ApiService accountApi({bool admin = false}) => ApiService(
  client: MockClient((r) async {
    if (r.url.path.endsWith('/auth/login')) {
      final name = jsonDecode(r.body)['username'];
      return http.Response(
        jsonEncode({
          'token': name,
          'user': {
            'id': name,
            'username': name,
            'role': admin ? 'admin' : 'member',
          },
        }),
        200,
      );
    }
    return http.Response('{}', 200);
  }),
);

void main() {
  test('late responses and cached state cannot cross account sessions', () async {
    final pending = Completer<http.Response>();
    var delayDrops = false;
    final api = ApiService(
      client: MockClient((r) async {
        if (r.url.path.endsWith('/auth/login')) {
          final name = jsonDecode(r.body)['username'];
          return http.Response(
            jsonEncode({
              'token': name,
              'user': {'id': name, 'username': name},
            }),
            200,
          );
        }
        if (r.url.path.endsWith('/drops')) {
          if (delayDrops) return pending.future;
          return http.Response(
            '{"drops":[{"id":"old-drop","name":"Old account drop"}],"checked_wallet_label":"Old wallet"}',
            200,
          );
        }
        if (r.url.path.endsWith('/tasks/queue')) {
          return http.Response('{"tasks":[]}', 200);
        }
        return http.Response('[]', 200);
      }),
    );
    await api.login('first', 'password');
    final notifier = MintlyNotifier(api);
    await notifier.loadInitialData();
    expect(notifier.state.drops.single.id, 'old-drop');
    delayDrops = true;
    final oldRequest = api.fetchDrops('all');
    final rejected = expectLater(oldRequest, throwsA(isA<ApiException>()));
    await api.login('second', 'password');
    expect(notifier.state.drops, isEmpty);
    expect(notifier.state.queue, isEmpty);
    expect(notifier.state.activities, isEmpty);
    expect(api.checkedWalletLabel, 'No wallet connected');
    pending.complete(
      http.Response(
        '{"drops":[{"id":"late-private-drop"}],"checked_wallet_label":"Previous wallet"}',
        200,
      ),
    );
    await rejected;
    expect(api.checkedWalletLabel, 'No wallet connected');
    expect(notifier.state.drops, isEmpty);
    api.disconnectBackend();
    expect(notifier.state.selectedDrop, isNull);
    notifier.dispose();
    api.dispose();
  });

  test(
    'push messages and preferences cannot carry into another account',
    () async {
      final api = accountApi();
      await api.login('first', 'password');
      final push = PushService.instance;
      await push.connect(api);
      expect(
        push.acceptsMessage({'category': 'mint_status', 'user_id': 'first'}),
        isTrue,
      );
      expect(
        push.acceptsMessage({'category': 'mint_status', 'user_id': 'second'}),
        isFalse,
      );
      expect(push.acceptsMessage({'category': 'mint_status'}), isFalse);
      expect(
        push.acceptsMessage({'category': 'source_health', 'user_id': 'first'}),
        isFalse,
      );
      push.preferences.value = const PushPreferences(
        dailyList: false,
        mintStatus: false,
      );
      await push.disconnect();
      expect(push.preferences.value.dailyList, isTrue);
      expect(
        push.acceptsMessage({'category': 'mint_status', 'user_id': 'first'}),
        isFalse,
      );
      await api.login('second', 'password');
      await push.connect(api);
      expect(
        push.acceptsMessage({'category': 'mint_status', 'user_id': 'first'}),
        isFalse,
      );
      await push.disconnect();
      api.dispose();
    },
  );

  for (final admin in [false, true]) {
    testWidgets(
      'settings groups account options and restricts admin tools: $admin',
      (tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = accountApi(admin: admin);
        await api.login('account', 'password');
        await tester.pumpWidget(
          ProviderScope(
            overrides: [apiServiceProvider.overrideWith((ref) => api)],
            child: MaterialApp(
              theme: MintlyTheme.light(),
              home: const AccountSettingsScreen(),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Your activity'), findsOneWidget);
        expect(find.text('Notifications'), findsOneWidget);
        expect(find.text('History'), findsOneWidget);
        expect(find.text('Copy mints'), findsOneWidget);
        await tester.scrollUntilVisible(find.text('About the app'), 250);
        expect(find.text('Live source'), admin ? findsOneWidget : findsNothing);
        expect(
          find.text('Manage accounts'),
          admin ? findsOneWidget : findsNothing,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
}
