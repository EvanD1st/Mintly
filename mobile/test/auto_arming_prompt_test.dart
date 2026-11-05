import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/main_shell.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'free_drops_test.dart' show FreeDropApi;

class PromptApi extends FreeDropApi {
  PromptApi()
    : super(client: MockClient((_) async => http.Response('{}', 404)));
  bool enabledOnce = false, failStatus = false;
  String account = 'member';
  bool copyNotice = false;
  int copyChecks = 0;
  Completer<Map<String, dynamic>>? pending;
  @override
  String get userId => account;
  void switchTo(String value, {required bool enabled}) {
    account = value;
    enabledOnce = enabled;
    notifyListeners();
  }

  void unlock() {
    screenLocked = false;
    notifyListeners();
  }

  @override
  Future<bool> showFreePhaseNotice() async {
    copyChecks++;
    return copyNotice;
  }

  @override
  Future<void> markFreePhaseNoticeSeen() async {
    copyNotice = false;
  }

  @override
  Future<Map<String, dynamic>> fetchFreeDropApprovals() async {
    if (failStatus) throw Exception('Offline');
    if (pending != null) return pending!.future;
    return {'approvals': approvals, 'enabled_once': enabledOnce};
  }

  @override
  Future<void> approveFreeDrops(Map<String, dynamic> request) async {
    await super.approveFreeDrops(request);
    enabledOnce = true;
  }

  @override
  Future<Map<String, dynamic>> fetchWalletReadiness() async => {
    'unavailable': true,
  };
  @override
  Future<List<Map<String, dynamic>>> fetchWallets() async => [
    {
      'id': 'w',
      'label': 'My wallet',
      'address': '0x1111111111111111111111111111111111111111',
    },
  ];
}

void main() {
  Widget shell(ProviderContainer container) => UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: MintlyTheme.light(), home: const MainShell()),
  );
  Future<ProviderContainer> open(WidgetTester tester, PromptApi api) async {
    tester.view.physicalSize = const Size(1000, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWith((ref) => api)],
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(shell(container));
    await tester.pumpAndSettle();
    return container;
  }

  Future<void> resume(WidgetTester tester) async {
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
  }

  Future<void> close(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  }

  testWidgets(
    'Not now repeats on the next opening but not on every Today visit',
    (tester) async {
      final api = PromptApi();
      final container = await open(tester, api);
      expect(find.text('Turn on Auto-Arming'), findsOneWidget);
      expect(find.textContaining('You still pay gas.'), findsOneWidget);
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Copy').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Today').last);
      await tester.pumpAndSettle();
      expect(find.text('Turn on Auto-Arming'), findsNothing);
      await resume(tester);
      expect(find.text('Turn on Auto-Arming'), findsOneWidget);
      await close(tester);
      await tester.pumpWidget(shell(container));
      await tester.pumpAndSettle();
      expect(find.text('Turn on Auto-Arming'), findsOneWidget);
      expect(api.submitted, isEmpty);
      await close(tester);
    },
  );
  testWidgets('Turn on opens settings and does not count as enabling', (
    tester,
  ) async {
    final api = PromptApi();
    await open(tester, api);
    await tester.tap(find.text('Turn on'));
    await tester.pumpAndSettle();
    expect(find.text('Free drops automation'), findsOneWidget);
    expect(api.enabledOnce, isFalse);
    expect(api.submitted, isEmpty);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await resume(tester);
    expect(find.text('Turn on Auto-Arming'), findsOneWidget);
    await close(tester);
  });
  testWidgets(
    'successful enabling stops prompt forever even after turning it off',
    (tester) async {
      final api = PromptApi();
      final container = await open(tester, api);
      await tester.tap(find.text('Turn on'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).at(1), '0.0005');
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      await tester.tap(find.text('Enable automatic free mints'));
      await tester.pumpAndSettle();
      expect(api.enabledOnce, isTrue);
      await tester.tap(find.text('Turn off free-drop automation'));
      await tester.pumpAndSettle();
      expect(api.approvals.first['status'], 'revoked');
      await tester.pageBack();
      await tester.pumpAndSettle();
      await resume(tester);
      expect(find.text('Turn on Auto-Arming'), findsNothing);
      await close(tester);
      await tester.pumpWidget(shell(container));
      await tester.pumpAndSettle();
      expect(find.text('Turn on Auto-Arming'), findsNothing);
      await close(tester);
    },
  );
  testWidgets('backgrounding with prompt open never stacks a second dialog', (
    tester,
  ) async {
    await open(tester, PromptApi());
    await resume(tester);
    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsNothing);
    await close(tester);
  });
  testWidgets('a delayed check waits until Today is visible', (tester) async {
    final api = PromptApi()..pending = Completer<Map<String, dynamic>>();
    await open(tester, api);
    await tester.tap(find.text('Copy').last);
    await tester.pumpAndSettle();
    api.pending!.complete({'approvals': [], 'enabled_once': false});
    await tester.pumpAndSettle();
    api.pending = null;
    expect(find.text('Turn on Auto-Arming'), findsNothing);
    await tester.tap(find.text('Today').last);
    await tester.pumpAndSettle();
    expect(find.text('Turn on Auto-Arming'), findsOneWidget);
    await close(tester);
  });
  testWidgets(
    'failed status check leaves Today usable and retries next opening',
    (tester) async {
      final api = PromptApi()..failStatus = true;
      await open(tester, api);
      expect(find.text('Turn on Auto-Arming'), findsNothing);
      api.failStatus = false;
      await resume(tester);
      expect(find.text('Turn on Auto-Arming'), findsOneWidget);
      await close(tester);
    },
  );
  testWidgets('prompt waits for account unlock', (tester) async {
    final api = PromptApi()..screenLocked = true;
    await open(tester, api);
    expect(find.text('Turn on Auto-Arming'), findsNothing);
    api.unlock();
    await tester.pumpAndSettle();
    expect(find.text('Turn on Auto-Arming'), findsOneWidget);
    await close(tester);
  });
  testWidgets('switching accounts checks the new account independently', (
    tester,
  ) async {
    final api = PromptApi()..enabledOnce = true;
    await open(tester, api);
    expect(find.text('Turn on Auto-Arming'), findsNothing);
    api.switchTo('other', enabled: false);
    await tester.pumpAndSettle();
    expect(find.text('Turn on Auto-Arming'), findsOneWidget);
    await tester.tap(find.text('Not now'));
    await tester.pumpAndSettle();
    api.switchTo('member', enabled: true);
    await tester.pumpAndSettle();
    expect(find.text('Turn on Auto-Arming'), findsNothing);
    await close(tester);
  });
  testWidgets(
    'late response from old account cannot suppress the new account prompt',
    (tester) async {
      final old = Completer<Map<String, dynamic>>();
      final api = PromptApi()..pending = old;
      await open(tester, api);
      api.switchTo('other', enabled: false);
      api.pending = null;
      old.complete({'approvals': [], 'enabled_once': true});
      await tester.pumpAndSettle();
      expect(find.text('Turn on Auto-Arming'), findsOneWidget);
      await close(tester);
    },
  );
  testWidgets(
    'Auto-Arming prompt takes priority without stacking copy announcement',
    (tester) async {
      final api = PromptApi()..copyNotice = true;
      final container = await open(tester, api);
      expect(find.text('Turn on Auto-Arming'), findsOneWidget);
      expect(api.copyChecks, 0);
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();
      expect(find.text('New: copy any eligible free phase'), findsNothing);
      await close(tester);
      api.enabledOnce = true;
      await tester.pumpWidget(shell(container));
      await tester.pumpAndSettle();
      expect(find.text('New: copy any eligible free phase'), findsOneWidget);
      await tester.tap(find.text('Got it'));
      await tester.pumpAndSettle();
      await close(tester);
    },
  );
}
