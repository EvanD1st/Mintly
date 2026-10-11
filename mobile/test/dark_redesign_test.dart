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
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/screens/main_shell.dart';
import 'package:mintly/theme/app_theme.dart';
import 'package:mintly/widgets/network_budget_card.dart';

Map<String, dynamic> grant(
  String id,
  int chain, {
  String status = 'enabled',
  String remaining = '4000000000000000',
}) => {
  'id': id,
  'chain_id': chain,
  'status': status,
  'expires_at': DateTime.now()
      .toUtc()
      .add(const Duration(days: 1))
      .toIso8601String(),
  'remaining_wei': remaining,
  'spent_wei': '1000000000000000',
  'reserved_wei': '1000000000000000',
};

void main() {
  test(
    'network allowance counts grants once, excludes disabled and expired grants, preserves wei',
    () {
      final now = DateTime.now().toUtc();
      final data = networkAllowances([
        grant('a', 1),
        grant('a', 1),
        grant('b', 8453, remaining: '1'),
        grant('disabled', 1, status: 'disabled'),
        {
          ...grant('expired', 1),
          'expires_at': now
              .subtract(const Duration(seconds: 1))
              .toIso8601String(),
        },
      ], now);
      expect(data.length, 2);
      expect(formatNative(data[0].available), '0.004');
      expect(formatNative(data[0].reserved), '0.001');
      expect(formatNative(data[1].available), '0.000000000000000001');
    },
  );

  test(
    'artwork requests are shared, tolerate failures and reset between sessions',
    () async {
      var requests = 0;
      final api = ApiService(
        client: MockClient((r) async {
          if (r.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"test","user":{"username":"member"}}',
              200,
            );
          }
          requests++;
          expect(r.headers['Authorization'], 'Bearer test');
          return http.Response(
            '{"image_url":"https://i.seadn.io/example.png"}',
            200,
          );
        }),
      );
      await api.login('one', 'test');
      expect(
        await Future.wait([
          api.collectionArtwork('plan:one'),
          api.collectionArtwork('plan:one'),
        ]),
        ['https://i.seadn.io/example.png', 'https://i.seadn.io/example.png'],
      );
      expect(requests, 1);
      await api.login('two', 'test');
      await api.collectionArtwork('plan:one');
      expect(requests, 2);
    },
  );

  for (final scale in [1.0, 1.4]) {
    testWidgets(
      'dark screens fit a narrow phone and preserve budget selection and activity details at scale $scale',
      (tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final font = File('C:/Windows/Fonts/arial.ttf');
        const defaultTestFont = bool.fromEnvironment(
          'MINTLY_TEST_DEFAULT_FONT',
        );
        if (!defaultTestFont && font.existsSync()) {
          await (FontLoader('Roboto')..addFont(
                Future.value(ByteData.sublistView(font.readAsBytesSync())),
              ))
              .load();
          final icons = File(
            '${Platform.environment['FLUTTER_ROOT'] ?? 'C:/Users/USER/develop/flutter'}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
          );
          if (icons.existsSync()) {
            await (FontLoader('MaterialIcons')..addFont(
                  Future.value(ByteData.sublistView(icons.readAsBytesSync())),
                ))
                .load();
          }
        }
        var budgetReads = 0;
        var armed = false;
        final api = ApiService(
          client: MockClient((r) async {
            final path = r.url.path;
            dynamic data;
            if (path.endsWith('/auth/login')) {
              data = {
                'token': 'test',
                'user': {'id': 'member', 'username': 'Jenny'},
              };
            } else if (path.endsWith('/automatic/policies')) {
              budgetReads++;
              data = [
                grant('eth', 1),
                grant('base', 8453, remaining: '6000000000000000'),
              ];
            } else if (path.endsWith('/artwork')) {
              data = {'image_url': null};
            } else if (path.endsWith('/wallets')) {
              data = [];
            } else if (path.endsWith('/copy-mints')) {
              data = {
                'enabled': true,
                'networks': [
                  {'chain_id': 1, 'name': 'Ethereum'},
                  {'chain_id': 8453, 'name': 'Base'},
                ],
                'watches': [],
              };
            } else if (path.endsWith('/copy-mints/activity')) {
              data = {
                'events': [
                  {
                    'id': 'copy',
                    'wallet_label': 'Joe',
                    'status': 'skipped',
                    'note': 'Remaining budget below required amount.',
                    'observed_at': '2026-10-11T11:00:00Z',
                    'observation': {
                      'name': 'Moon Shapes',
                      'chain': 'Base',
                      'contract': '0x123',
                    },
                  },
                ],
                'next_offset': null,
              };
            } else if (path.endsWith('/history')) {
              data = {
                'records': [
                  {
                    'id': 'mint',
                    'drop_name': 'Orbit Garden',
                    'chain': 'Ethereum',
                    'quantity': 1,
                    'status': 'confirmed',
                    'created_at': '2026-10-11T11:42:00Z',
                    'actual_total_cost_wei': '30000000000000',
                    'transaction_hash': '0xconfirmed',
                  },
                ],
                'next_offset': null,
              };
            } else if (path.endsWith('/mint-plans')) {
              data = [
                {
                  'id': 'plan',
                  'collection_name': 'Paper Worlds',
                  'chain': 'Base',
                  'opensea_url': 'https://opensea.io/collection/paper-worlds',
                  'wallet_address': '0x123',
                  'contract_address': '0x456',
                  'stage_name': 'Whitelist',
                  'price_eth': '0.001',
                  'quantity': 2,
                  'status': 'scheduled',
                  'status_note': 'The whitelist phase opens soon.',
                  'starts_at': '2026-10-11T15:00:00Z',
                },
              ];
            } else if (path.endsWith('/tasks/queue')) {
              data = {
                'tasks': armed
                    ? [
                        {
                          'id': 'task',
                          'plan_id': 'plan',
                          'drop_id': 'drop',
                          'drop_name': 'Paper Worlds',
                          'status': 'armed',
                          'chain': 'Base',
                          'stage_name': 'Whitelist',
                          'quantity': 2,
                          'time_wat_label': '11 Oct · 16:00 WAT',
                        },
                      ]
                    : [],
              };
            } else if (path.endsWith('/drops')) {
              data = {'drops': []};
            } else if (path.endsWith('/activity') ||
                path.endsWith('/mint-permissions')) {
              data = [];
            } else {
              data = {};
            }
            return http.Response(jsonEncode(data), 200);
          }),
        );
        await api.login('member', 'test');
        final container = ProviderContainer(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
        );
        addTearDown(container.dispose);
        await container.read(mintlyProvider.notifier).loadInitialData();
        final captureKey = GlobalKey();
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: RepaintBoundary(
              key: captureKey,
              child: MaterialApp(
                debugShowCheckedModeBanner: false,
                theme: MintlyTheme.dark(),
                builder: (context, child) => MediaQuery(
                  data: MediaQuery.of(
                    context,
                  ).copyWith(textScaler: TextScaler.linear(scale)),
                  child: child!,
                ),
                home: const MainShell(),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        Future<void> capture(String name) async {
          expect(tester.takeException(), isNull);
          expect(find.text('Mintly'), findsNothing);
          if (defaultTestFont || !font.existsSync() || scale != 1.0) return;
          await tester.runAsync(() async {
            final image =
                await (captureKey.currentContext!.findRenderObject()
                        as RenderRepaintBoundary)
                    .toImage(pixelRatio: 2);
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await Directory('build/dark-redesign').create(recursive: true);
            await File(
              'build/dark-redesign/$name.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }

        await tester.tap(find.text('Mint plans').last);
        await tester.pumpAndSettle();
        await capture('mint-plans');
        await tester.ensureVisible(find.text('Review mint'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Review mint'));
        await tester.pumpAndSettle();
        expect(
          find.text('0x123'),
          findsOneWidget,
        ); // Short addresses never crash the details page.
        await capture('plan-details');
        await tester.pageBack();
        await tester.pumpAndSettle();
        armed = true;
        await container.read(mintlyProvider.notifier).loadInitialData();
        await tester.pumpAndSettle();
        expect(find.text('Review mint'), findsNothing);
        expect(find.text('Paper Worlds'), findsOneWidget);
        expect(find.text('Armed'), findsOneWidget);
        armed = false;
        await tester.tap(find.text('Copy').last);
        await tester.pumpAndSettle();
        await capture('copy');
        await tester.tap(find.byTooltip('Available budget by network'));
        await tester.pumpAndSettle();
        await capture('network-budgets');
        await tester.tap(find.text('Base').last);
        await tester.pumpAndSettle();
        expect(find.text('ETH 0.006'), findsOneWidget);
        expect(find.text('HyperEVM'), findsNothing);
        final before = budgetReads;
        await tester.tap(find.byTooltip('Refresh budget'));
        await tester.pumpAndSettle();
        expect(budgetReads, greaterThan(before));
        await tester.tap(find.text('Activity').last);
        await tester.pumpAndSettle();
        await capture('activity');
        expect(find.text('Total spent'), findsOneWidget);
        expect(find.textContaining('0xconfirmed'), findsNothing);
        await tester.ensureVisible(find.text('View details'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('View details'));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Approval & recovery history'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Approval & recovery history'));
        await tester.pumpAndSettle();
        expect(find.text('Transaction: 0xconfirmed'), findsOneWidget);
        await capture('mint-details');
        await tester.pageBack();
        await tester.pumpAndSettle();
        await tester.scrollUntilVisible(
          find.text('Copies'), -300,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Copies'));
        await tester.pumpAndSettle();
        expect(find.text('Skipped'), findsOneWidget);
        expect(
          find.text('Remaining budget below required amount.'),
          findsOneWidget,
        );
        expect(find.text('Total spent'), findsNothing);
        await tester.tap(find.text('Wallet').last);
        await tester.pumpAndSettle();
        await capture('wallet');
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
