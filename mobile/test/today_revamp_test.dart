import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/models/drop_model.dart';
import 'package:mintly/models/today_automation_status.dart';
import 'package:mintly/screens/discover_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'package:mintly/widgets/today_overview.dart';

Map<String, dynamic> approval(
  int chain, {
  String status = 'active',
  String wallet = 'wallet',
  bool waiting = false,
}) => {
  'status': status,
  'expires_at': DateTime.now()
      .toUtc()
      .add(const Duration(days: 20))
      .toIso8601String(),
  'snapshot': {
    'wallet_id': wallet,
    'chain_id': chain,
    'quantity_mode': 'wallet_max',
  },
  'note': waiting
      ? 'The remaining signing allowance is below your chosen gas cap.'
      : 'Watching Today for eligible free phases.',
};

void main() {
  testWidgets('global pause overrides active network approvals', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TodayAutomationCard(
            status: AsyncData(
              TodayAutomationStatus([approval(1)], paused: true),
            ),
            hasWallet: true,
            onManage: () {},
          ),
        ),
      ),
    );
    expect(find.text('Paused'), findsOneWidget);
    expect(find.text('Ethereum · Paused'), findsOneWidget);
    expect(find.textContaining('On ·'), findsNothing);
    expect(find.textContaining('Resume it from Wallet'), findsOneWidget);
  });
  testWidgets(
    'automation distinguishes enabled, waiting and switched-off networks',
    (tester) async {
      var managed = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TodayAutomationCard(
              status: AsyncData(
                TodayAutomationStatus([
                  approval(1),
                  approval(8453),
                  approval(4663, waiting: true),
                  approval(57073, status: 'revoked'),
                ]),
              ),
              hasWallet: true,
              onManage: () => managed = true,
            ),
          ),
        ),
      );
      expect(find.text('On · 3 networks'), findsOneWidget);
      expect(find.text('Robinhood · Waiting'), findsOneWidget);
      expect(find.text('Ink · Off'), findsOneWidget);
      await tester.tap(find.text('Manage'));
      expect(managed, isTrue);
    },
  );

  testWidgets('missing status is unavailable, never falsely off', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TodayAutomationCard(
            status: AsyncError(Exception('offline'), StackTrace.current),
            hasWallet: true,
            onManage: () {},
          ),
        ),
      ),
    );
    expect(find.text('Status unavailable'), findsOneWidget);
    expect(find.text('Off'), findsNothing);
  });

  testWidgets(
    'summary separates ready, active and completed collection cards',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TodayMintSummary(
              drops: [
                DropModel.fromJson({
                  'wallet_check': {'setup_enabled': true},
                }),
                DropModel.fromJson({
                  'automatic_mint': {'status': 'armed'},
                  'wallet_check': {'setup_enabled': true},
                }),
                DropModel.fromJson({
                  'automatic_mint': {'status': 'already_minted'},
                }),
              ],
            ),
          ),
        ),
      );
      expect(find.text('1 ready'), findsOneWidget);
      expect(find.text('1 armed'), findsOneWidget);
      expect(find.text('1 minted'), findsOneWidget);
    },
  );

  test(
    'late status for another wallet cannot replace the selected wallet snapshot',
    () async {
      final old = Completer<http.Response>();
      var calls = 0;
      final api = ApiService(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/login')) {
            return http.Response(
              jsonEncode({
                'token': 'test',
                'user': {'id': 'owner'},
              }),
              200,
            );
          }
          calls++;
          if (calls == 1) return old.future;
          return http.Response(
            jsonEncode({
              'approvals': [approval(8453, wallet: 'new')],
              'automation_paused': true,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      await api.login('member', 'test');
      final container = ProviderContainer(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
      );
      addTearDown(container.dispose);
      final a = todayAutomationProvider(('owner', 0, 'old'));
      final b = todayAutomationProvider(('owner', 0, 'new'));
      final keepA = container.listen(a, (_, _) {});
      final keepB = container.listen(b, (_, _) {});
      addTearDown(keepA.close);
      addTearDown(keepB.close);
      final pending = container.read(a.future);
      final current = await container.read(b.future);
      expect(current.approvals.single['snapshot']['wallet_id'], 'new');
      expect(current.paused, isTrue);
      old.complete(
        http.Response(
          jsonEncode({
            'approvals': [approval(1, wallet: 'old')],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
      );
      await pending;
      expect(
        container.read(b).requireValue.approvals.single['snapshot']['chain_id'],
        8453,
      );
    },
  );

  for (final dark in [false, true]) {
    testWidgets('Today revamp ${dark ? 'dark' : 'light'} layout and preview', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(430, 980);
      if (Platform.environment['MINTLY_TODAY_PREVIEW_DIR'] != null) {
        final root =
            '${Platform.environment['FLUTTER_ROOT'] ?? 'C:/Users/USER/develop/flutter'}/bin/cache/artifacts/material_fonts';
        for (final font in {
          'Roboto': 'Roboto-Regular.ttf',
          'MaterialIcons': 'MaterialIcons-Regular.otf',
        }.entries) {
          final file = Directory(root).listSync().whereType<File>().firstWhere(
            (file) =>
                file.uri.pathSegments.last.toLowerCase() ==
                font.value.toLowerCase(),
          );
          await (FontLoader(font.key)..addFont(
                Future.value(ByteData.sublistView(file.readAsBytesSync())),
              ))
              .load();
        }
      }
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final rows = [
        approval(1),
        approval(8453),
        approval(4663, waiting: true),
        approval(999),
        approval(33139),
        approval(57073, status: 'revoked'),
      ];
      final api = ApiService(
        client: MockClient((request) async {
          final path = request.url.path;
          dynamic result = [];
          if (path.endsWith('/auth/login')) {
            result = {
              'token': 'test',
              'user': {'id': 'owner', 'username': 'member', 'role': 'member'},
            };
          } else if (path.endsWith('/automatic/free-drops')) {
            result = {'approvals': rows, 'enabled_once': true};
          } else if (path.endsWith('/drops')) {
            result = {
              'selected_wallet_id': 'wallet',
              'wallets': [
                {
                  'id': 'wallet',
                  'label': 'Mint wallet',
                  'address': '0x${'1' * 40}',
                },
              ],
              'feed_status_text':
                  '@lakzonevn list available · @Cassio_Sch list available',
              'drops': [
                {
                  'id': 'one',
                  'name': 'Neon Bloom',
                  'chain': 'Base',
                  'chain_id': 8453,
                  'sources': [
                    {'author': 'Cassio_Sch'},
                  ],
                  'today_schedule': 'GTD 18:00 WAT',
                  'automatic_mint': {
                    'id': 'armed',
                    'status': 'armed',
                    'quantity': 3,
                    'stage_name': 'GTD',
                    'scheduled_for_utc': DateTime.now()
                        .toUtc()
                        .add(const Duration(hours: 1))
                        .toIso8601String(),
                  },
                },
                {
                  'id': 'two',
                  'name': 'Moon House',
                  'chain': 'Ethereum',
                  'chain_id': 1,
                  'automatic_mint': {
                    'id': 'minted',
                    'status': 'confirmed',
                    'quantity': 2,
                    'stage_name': 'FCFS',
                  },
                },
              ],
            };
          } else if (path.endsWith('/tasks/queue')) {
            result = {'tasks': []};
          } else if (path.endsWith('/artwork')) {
            result = {'image_url': null};
          }
          return http.Response(
            jsonEncode(result),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      await api.login('member', 'test');
      final container = ProviderContainer(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
      );
      addTearDown(container.dispose);
      await container.read(mintlyProvider.notifier).loadInitialData();
      final capture = GlobalKey();
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: RepaintBoundary(
            key: capture,
            child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: dark ? MintlyTheme.dark() : MintlyTheme.light(),
              home: const Scaffold(body: SafeArea(child: DiscoverScreen())),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('On · 5 networks'), findsOneWidget);
      expect(find.text('Ink · Off'), findsOneWidget);
      expect(find.text('1 armed'), findsOneWidget);
      expect(find.text('1 minted'), findsOneWidget);
      expect(tester.takeException(), isNull);
      final output = Platform.environment['MINTLY_TODAY_PREVIEW_DIR'];
      if (output != null) {
        await tester.runAsync(() async {
          final image =
              await (capture.currentContext!.findRenderObject()
                      as RenderRepaintBoundary)
                  .toImage(pixelRatio: 2);
          final data = await image.toByteData(format: ui.ImageByteFormat.png);
          await Directory(output).create(recursive: true);
          await File(
            '$output/today-${dark ? 'dark' : 'light'}.png',
          ).writeAsBytes(data!.buffer.asUint8List());
          image.dispose();
        });
      }
      tester.view.physicalSize = const Size(320, 640);
      tester.platformDispatcher.textScaleFactorTestValue = 1.3;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.scrollUntilVisible(find.text('View automatic mint'), 200);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.scrollUntilVisible(find.text('Minted'), 200);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
    });
  }
}
