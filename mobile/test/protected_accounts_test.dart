import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/protected_accounts.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/models/drop_model.dart';
import 'package:mintly/main.dart';
import 'package:mintly/screens/auth_gate.dart';
import 'package:mintly/widgets/account_picker_card.dart';
import 'package:mintly/widgets/mintly_notice.dart';
import 'session_restore_test.dart' show MemoryVault;

class Accounts implements ProtectedAccounts {
  bool secure = true, allow = true;
  int unlocks = 0, reads = 0;
  String? active;
  bool chooser = false;
  final records = <String, Map<String, dynamic>>{};
  @override
  Future<Map<String, dynamic>> capabilities({String? origin}) async => {
    'version': 2,
    'device_secure': secure,
    'has_accounts': records.isNotEmpty,
    'chooser_on_reopen': chooser,
  };
  @override
  Future<void> showChooserOnReopen(String origin, bool show) async {
    chooser = show;
  }

  @override
  Future<bool> unlock() async {
    unlocks++;
    return allow;
  }

  @override
  Future<List<Map<String, dynamic>>> accounts(String origin) async => [
    for (final row in records.values)
      if (row['origin'] == origin)
        {
          'user_id': row['user_id'],
          'username': row['username'],
          'origin': origin,
          'active': row['user_id'] == active,
        },
  ];
  @override
  Future<Map<String, dynamic>?> read(String origin, String account) async {
    reads++;
    final row = records[account];
    return row?['origin'] == origin ? Map.of(row!) : null;
  }

  @override
  Future<void> save(Map<String, dynamic> record) async {
    expect(record.containsKey('password'), false);
    expect(record.containsKey('token'), false);
    expect(record.containsKey('private_key'), false);
    records[record['user_id'] as String] = Map.of(record);
    active = record['user_id'] as String;
  }

  @override
  Future<void> remove(String origin, String account) async {
    if (records[account]?['origin'] == origin) records.remove(account);
  }
}

Map<String, dynamic> result(String account, {String refresh = 'refresh-old'}) =>
    {
      'token': 'bearer-$account',
      'expires_at': '2099-10-13T00:00:00Z',
      'user': {
        'id': account,
        'username': account,
        'role': 'member',
        'must_change_password': false,
      },
      'refresh_token': refresh,
      'device_session_id': '11111111-1111-4111-8111-111111111111',
      'remembered_expires_at': '2099-10-13T00:00:00Z',
      'origin': ApiService.baseUrl,
    };
Map<String, dynamic> stored(String account) => {
  'user_id': account,
  'username': account,
  'refresh_token': 'refresh-old',
  'device_session_id': '11111111-1111-4111-8111-111111111111',
  'remembered_expires_at': '2099-10-13T00:00:00Z',
  'origin': ApiService.baseUrl,
};
http.Response ok(dynamic data) => http.Response(jsonEncode(data), 200);

void main() {
  test(
    'sign out retains saved identities without a phone prompt and cold reopening shows chooser',
    () async {
      final vault = Accounts();
      final paths = <String>[];
      final client = MockClient((r) async {
        paths.add(r.url.path);
        if (r.url.path.endsWith('/device-login')) return ok(result('alice'));
        if (r.url.path.endsWith('/device-refresh')) {
          return ok(result('alice', refresh: 'rotated'));
        }
        return ok({});
      });
      final api = ApiService(accounts: vault, client: client);
      await api.login('alice', 'password');
      final prompts = vault.unlocks;
      await api.signOut();
      expect(vault.unlocks, prompts);
      expect(vault.records.keys, ['alice']);
      expect(api.isLiveBackendConnected, false);
      expect(paths.where((p) => p.endsWith('/logout')), isEmpty);
      expect(vault.chooser, true);
      final reopened = ApiService(accounts: vault, client: client);
      expect(await reopened.restoreSession(), false);
      expect(vault.unlocks, prompts + 1);
      expect(reopened.savedAccounts.single['username'], 'alice');
      expect(paths.where((p) => p.endsWith('/device-refresh')), isEmpty);
      await reopened.loadSavedAccounts();
      expect(vault.unlocks, prompts + 1);
      expect(await reopened.switchSavedAccount('alice'), true);
      expect(vault.unlocks, prompts + 2);
      expect(reopened.userId, 'alice');
      expect(vault.chooser, false);
    },
  );

  testWidgets(
    'account card expands without unlocking; sign out shows chooser and Add account shows clean login',
    (tester) async {
      final vault = Accounts()..records['bob'] = stored('bob');
      final api = ApiService(
        vault: MemoryVault(),
        accounts: vault,
        client: MockClient((r) async {
          if (r.url.path.endsWith('/device-login')) return ok(result('alice'));
          return ok({});
        }),
      );
      await api.login('alice', 'password');
      final container = ProviderContainer(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
      );
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: AccountPickerCard())),
        ),
      );
      expect(find.text('Personal account'), findsOneWidget);
      expect(find.text('bob'), findsNothing);
      final prompts = vault.unlocks;
      await tester.tap(find.text('alice'));
      await tester.pumpAndSettle();
      expect(find.text('bob'), findsOneWidget);
      expect(find.text('Add account'), findsOneWidget);
      expect(vault.unlocks, prompts);
      await tester.tap(find.text('Personal account'));
      await tester.pumpAndSettle();
      expect(find.text('bob'), findsNothing);
      await tester.runAsync(() => api.signOut());
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: AuthGate()),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Choose an account'), findsOneWidget);
      expect(find.text('bob'), findsOneWidget);
      expect(find.text('Unlock saved accounts'), findsNothing);
      expect(vault.unlocks, prompts);
      await tester.tap(find.text('Add account'));
      await tester.pumpAndSettle();
      expect(find.text('Remember this account'), findsOneWidget);
      expect(find.textContaining('Expires after'), findsNothing);
      expect(find.text('Back to saved accounts'), findsOneWidget);
      await tester.tap(find.text('Back to saved accounts'));
      await tester.pumpAndSettle();
      expect(find.text('Choose an account'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      container.dispose();
    },
  );

  testWidgets('ordinary background resume leaves active account unlocked', (
    tester,
  ) async {
    final vault = Accounts();
    final api = ApiService(
      vault: MemoryVault(),
      accounts: vault,
      client: MockClient((r) async {
        if (r.url.path.endsWith('/device-login')) return ok(result('alice'));
        if ([
          '/api/automatic/policies',
          '/api/mint-plans',
          '/api/wallets',
          '/api/mint-permissions',
          '/api/activity',
        ].contains(r.url.path))
          return ok([]);
        return ok({});
      }),
    );
    await api.login('alice', 'password');
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWith((ref) => api)],
    );
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: AuthGate()),
      ),
    );
    await tester.pump();
    final prompts = vault.unlocks;
    for (final state in [
      AppLifecycleState.inactive,
      AppLifecycleState.hidden,
      AppLifecycleState.paused,
      AppLifecycleState.hidden,
      AppLifecycleState.inactive,
      AppLifecycleState.resumed,
    ]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
    await tester.pump();
    expect(api.screenLocked, false);
    expect(vault.unlocks, prompts);
    await tester.pumpWidget(const SizedBox.shrink());
    container.dispose();
  });
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'locked routes hide account data from accessibility and keyboard',
    (tester) async {
      final api = ApiService(
        vault: MemoryVault(),
        accounts: Accounts(),
        client: MockClient((r) async => ok(result('alice'))),
      );
      await api.login('alice', 'password');
      final focus = FocusNode();
      final semantics = tester.ensureSemantics();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: const MintlyApp(),
        ),
      );
      MintlyNotice.navigatorKey.currentState!.pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => Scaffold(
            body: TextField(
              focusNode: focus,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Private approval draft',
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(focus.hasFocus, true);
      api.lockForReopen();
      await tester.pump();
      expect(focus.hasFocus, false);
      expect(
        tester
            .binding
            .renderViews
            .first
            .owner!
            .semanticsOwner!
            .rootSemanticsNode!
            .toStringDeep(),
        isNot(contains('Private approval draft')),
      );
      expect(find.text('Unlock account'), findsOneWidget);
      await api.unlockForReopen();
      await tester.pump();
      expect(find.text('Unlock account'), findsNothing);
      expect(find.byType(TextField), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      semantics.dispose();
      focus.dispose();
      expect(tester.takeException(), isNull);
    },
  );
  test(
    'reopening protects the screen without cancelling same-account wallet drafts',
    () async {
      final vault = Accounts();
      final api = ApiService(
        accounts: vault,
        client: MockClient((r) async => ok(result('alice'))),
      );
      await api.login('alice', 'password');
      final notifier = MintlyNotifier(api);
      notifier.selectDrop(
        DropModel.fromJson({
          'id': 'draft',
          'name': 'Wallet handoff',
          'stages': [],
        }),
      );
      notifier.setFeeCap('0.0003');
      notifier.setConsent(true);
      final revision = api.sessionRevision;
      api.lockForReopen();
      expect(api.screenLocked, true);
      expect(notifier.state.selectedDrop?.id, 'draft');
      expect(notifier.state.isConsentChecked, true);
      vault.allow = false;
      expect(await api.unlockForReopen(), false);
      expect(api.screenLocked, true);
      vault.allow = true;
      expect(await api.unlockForReopen(), true);
      expect(api.sessionRevision, revision);
      expect(notifier.state.feeCap, '0.0003');
      expect(notifier.state.selectedDrop?.id, 'draft');
      api.lockSession();
      expect(notifier.state.selectedDrop, isNull);
      expect(notifier.state.isConsentChecked, false);
      notifier.dispose();
      api.dispose();
    },
  );
  test(
    'two accounts are remembered without passwords; reopening rotates refresh and clears wallet caches',
    () async {
      final vault = Accounts();
      final api = ApiService(
        accounts: vault,
        client: MockClient((r) async {
          final body = jsonDecode(r.body) as Map;
          if (r.url.path.endsWith('/device-login')) {
            return ok(result(body['username'] as String));
          }
          if (r.url.path.endsWith('/device-refresh')) {
            return ok(result(vault.active!, refresh: 'rotated'));
          }
          throw StateError('Unexpected request');
        }),
      );
      await api.login('alice', 'password');
      await api.login('bob', 'password');
      expect(vault.records.keys, containsAll(['alice', 'bob']));
      expect(api.userId, 'bob');
      expect(api.sessionRemembered, true);
      api.selectedFeedWallet = 'old-wallet';
      api.feedWallets = [
        {'id': 'old-wallet'},
      ];
      api.lockSession();
      expect(api.selectedFeedWallet, isNull);
      expect(api.feedWallets, isEmpty);
      expect(await api.restoreSession(), true);
      expect(api.userId, 'bob');
      expect(vault.records['bob']!['refresh_token'], 'rotated');
      expect(vault.unlocks, 3);
      api.dispose();
    },
  );
  test('lost refresh response repeats the same durable request id', () async {
    final vault = Accounts()
      ..records['alice'] = stored('alice')
      ..active = 'alice';
    var calls = 0;
    String? key;
    final api = ApiService(
      accounts: vault,
      client: MockClient((r) async {
        final body = jsonDecode(r.body) as Map;
        calls++;
        key ??= body['request_id'] as String;
        expect(body['request_id'], key);
        expect(vault.records['alice']!['pending_refresh_id'], key);
        if (calls == 1) throw http.ClientException('Lost response');
        return ok(result('alice', refresh: 'rotated'));
      }),
    );
    expect(await api.restoreSession(), true);
    expect(calls, 2);
    expect(vault.records['alice']!.containsKey('pending_refresh_id'), false);
    api.dispose();
  });
  test(
    'offline retry retains credentials and recovery id across process recreation',
    () async {
      final vault = Accounts()
        ..records['alice'] = stored('alice')
        ..active = 'alice';
      final api = ApiService(
        accounts: vault,
        client: MockClient((r) async => throw http.ClientException('Offline')),
      );
      expect(await api.restoreSession(), false);
      final pending = vault.records['alice']!['pending_refresh_id'];
      expect(pending, isNotNull);
      api.dispose();
      final restored = ApiService(
        accounts: vault,
        client: MockClient((r) async {
          expect(jsonDecode(r.body)['request_id'], pending);
          return ok(result('alice', refresh: 'rotated'));
        }),
      );
      expect(await restored.restoreSession(), true);
      restored.dispose();
    },
  );
  test(
    'cancelled unlock does not read credentials or send refresh requests',
    () async {
      final vault = Accounts()
        ..allow = false
        ..records['alice'] = stored('alice')
        ..active = 'alice';
      var calls = 0;
      final api = ApiService(
        accounts: vault,
        client: MockClient((r) async {
          calls++;
          return ok({});
        }),
      );
      expect(await api.restoreSession(), false);
      expect(vault.reads, 0);
      expect(calls, 0);
      expect(vault.records.length, 1);
      api.dispose();
    },
  );
  test(
    'no device lock disables remembering and retains normal password login',
    () async {
      final accounts = Accounts()..secure = false;
      final legacy = MemoryVault();
      final api = ApiService(
        accounts: accounts,
        vault: legacy,
        client: MockClient((r) async {
          expect(r.url.path.endsWith('/auth/login'), true);
          return ok(result('alice')..remove('refresh_token'));
        }),
      );
      await api.login('alice', 'password');
      expect(api.isLiveBackendConnected, true);
      expect(api.sessionRemembered, false);
      expect(legacy.session, isNull);
      expect(accounts.records, isEmpty);
      api.dispose();
    },
  );
  test(
    'expired and revoked records require password without deleting other accounts',
    () async {
      final vault = Accounts()
        ..records['alice'] = stored('alice')
        ..records['bob'] = stored('bob')
        ..active = 'alice';
      final api = ApiService(
        accounts: vault,
        client: MockClient(
          (r) async => http.Response('{"detail":"Expired"}', 401),
        ),
      );
      expect(await api.restoreSession(), false);
      expect(vault.records.containsKey('alice'), false);
      expect(vault.records.containsKey('bob'), true);
      api.dispose();
    },
  );
  test(
    'account switch rejects late previous account responses and clears drafts',
    () async {
      final vault = Accounts();
      final pending = Completer<http.Response>();
      final api = ApiService(
        accounts: vault,
        client: MockClient((r) async {
          if (r.url.path.endsWith('/device-login')) return ok(result('alice'));
          if (r.url.path.endsWith('/drops')) return pending.future;
          if (r.url.path.endsWith('/device-refresh')) {
            return ok(result('bob', refresh: 'rotated'));
          }
          return ok([]);
        }),
      );
      await api.login('alice', 'password');
      vault.records['bob'] = stored('bob');
      final notifier = MintlyNotifier(api);
      final old = api.fetchDrops('all');
      final failed = expectLater(old, throwsA(isA<ApiException>()));
      expect(await api.switchSavedAccount('bob'), true);
      pending.complete(ok({'drops': []}));
      await failed;
      expect(api.userId, 'bob');
      expect(notifier.state.drops, isEmpty);
      expect(notifier.state.selectedDrop, isNull);
      expect(notifier.state.isConsentChecked, false);
      notifier.dispose();
      api.dispose();
    },
  );
  test('remove revokes one family and keeps another saved account', () async {
    final vault = Accounts()
      ..records['alice'] = stored('alice')
      ..records['bob'] = stored('bob');
    var revoked = false;
    final api = ApiService(
      accounts: vault,
      client: MockClient((r) async {
        expect(r.url.path.endsWith('/device-revoke'), true);
        revoked = true;
        return ok({'status': 'ok'});
      }),
    );
    await api.removeSavedAccount('alice');
    expect(revoked, true);
    expect(vault.records.keys, ['bob']);
    api.dispose();
  });
}
