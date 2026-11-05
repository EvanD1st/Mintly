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

  final quickRequests = <String>[];
  Completer<void>? enabling;
  @override
  Future<void> enableFreeDrops(String requestId, String? walletId) async {
    quickRequests.add(requestId);
    if (enabling != null) await enabling!.future;
    if (this.fail) throw Exception('Set up a signing wallet first.');
    enabledOnce = true;
    approvals.add({'id': 'quick', 'status': 'active'});
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

  testWidgets('X repeats on the next opening but not on every Today visit', (
    tester,
  ) async {
    final api = PromptApi();
    final container = await open(tester, api);
    expect(find.text('Turn on Auto-Arming'), findsOneWidget);
    expect(find.textContaining('You still pay gas.'), findsOneWidget);
    await tester.tap(find.byTooltip('Close Auto-Arming'));
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
  });
  testWidgets('Turn on enables directly and never opens another screen', (
    tester,
  ) async {
    final api = PromptApi();
    await open(tester, api);
    expect(find.text('Not now'), findsNothing);
    await tester.tap(find.text('Turn on'));
    await tester.pumpAndSettle();
    expect(api.enabledOnce, isTrue);
    expect(api.quickRequests, hasLength(1));
    expect(find.text('Free drops automation'), findsNothing);
    expect(find.text('Auto-Arming is on.'), findsOneWidget);
    await close(tester);
  });
  testWidgets('failed enable stays in popup and retries the same request', (
    tester,
  ) async {
    final api = PromptApi()..fail = true;
    await open(tester, api);
    await tester.tap(find.text('Turn on'));
    await tester.pumpAndSettle();
    expect(find.text('Set up a signing wallet first.'), findsOneWidget);
    expect(api.enabledOnce, isFalse);
    api.fail = false;
    await tester.tap(find.text('Turn on'));
    await tester.pumpAndSettle();
    expect(api.quickRequests, hasLength(2));
    expect(api.quickRequests[0], api.quickRequests[1]);
    expect(api.enabledOnce, isTrue);
    await close(tester);
  });
  testWidgets('pending enable prevents duplicate taps and dismissal', (
    tester,
  ) async {
    final done = Completer<void>();
    final api = PromptApi()..enabling = done;
    await open(tester, api);
    await tester.tap(find.text('Turn on'));
    await tester.pump();
    expect(find.text('Turning on...'), findsOneWidget);
    expect(
      tester
          .widget<IconButton>(find.widgetWithIcon(IconButton, Icons.close))
          .onPressed,
      isNull,
    );
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, 'Turning on...'),
          )
          .onPressed,
      isNull,
    );
    expect(api.quickRequests, hasLength(1));
    done.complete();
    await tester.pumpAndSettle();
    await close(tester);
  });
  testWidgets(
    'successful enabling stops prompt forever even after turning it off',
    (tester) async {
      final api = PromptApi();
      final container = await open(tester, api);
      await tester.tap(find.text('Turn on'));
      await tester.pumpAndSettle();
      expect(api.enabledOnce, isTrue);
      await api.revokeFreeDrops('quick');
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
    await tester.tap(find.byTooltip('Close Auto-Arming'));
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
  testWidgets('an old account popup cannot enable the newly selected account', (
    tester,
  ) async {
    final api = PromptApi();
    await open(tester, api);
    api.switchTo('other', enabled: false);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Turn on'));
    await tester.pumpAndSettle();
    expect(api.quickRequests, isEmpty);
    expect(
      find.text('Unlock this account before turning on Auto-Arming.'),
      findsOneWidget,
    );
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
    await tester.tap(find.byTooltip('Close Auto-Arming'));
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
      await tester.tap(find.byTooltip('Close Auto-Arming'));
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
