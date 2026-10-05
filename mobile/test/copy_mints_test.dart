import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/copy_mints_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';

const address = '0x1111111111111111111111111111111111111111';
final watch = <String, dynamic>{
  'id': 'watch',
  'address': address,
  'label': 'Moon scout',
  'chains': [1, 8453, 4663],
  'recent_mints': 12,
  'cursors': {
    '8453': {'status': 'monitoring', 'checked_at': '2026-10-04T11:20:00Z'},
  },
  'rules': <dynamic>[],
};
final networks = [
  for (final (id, name) in [
    (1, 'Ethereum'),
    (8453, 'Base'),
    (4663, 'Robinhood'),
  ])
    {'chain_id': id, 'name': name},
];

Future<ApiService> apiFor({
  void Function(Map<String, dynamic>)? approved,
  bool populated = true,
}) async {
  final api = ApiService(
    client: MockClient((r) async {
      if (r.url.path.endsWith('/auth/login')) {
        return http.Response(
          '{"token":"test","user":{"username":"member"}}',
          200,
        );
      }
      expect(r.headers['Authorization'], 'Bearer test');
      dynamic data;
      if (r.url.path.endsWith('/copy-mints')) {
        data = {
          'enabled': true,
          'networks': networks,
          'watches': populated ? [watch] : [],
        };
      } else if (r.url.path.endsWith('/copy-mints/activity')) {
        data = {
          'copied_mints': 2,
          'spent_wei': '14000000000000000',
          'next_offset': null,
          'events': populated
              ? [
                  {
                    'id': 'event',
                    'watch_id': 'watch',
                    'wallet_label': 'Moon scout',
                    'observed_at': '2026-10-04T11:10:00Z',
                    'status': 'confirmed',
                    'task_id': 'task',
                    'quantity': 1,
                    'actual_cost_wei': '8000000000000000',
                    'observation': {
                      'name': 'Orbit collection',
                      'chain': 'Base',
                      'chain_id': 8453,
                      'contract': address,
                      'source_quantity': 1,
                      'price_wei': '6000000000000000',
                      'source_hash': '0xsource',
                    },
                    'transaction_hash': '0xcopy',
                  },
                ]
              : [],
        };
      } else if (r.url.path.endsWith('/automatic/policies')) {
        data = [
          for (final chain in [1, 8453, 4663])
            {
              'id': 'policy$chain',
              'wallet_id': 'receiving',
              'chain_id': chain,
              'account': '0x2222222222222222222222222222222222222222',
              'status': 'enabled',
              'expires_at': DateTime.now()
                  .toUtc()
                  .add(const Duration(days: 8))
                  .toIso8601String(),
              'remaining_wei': '10000000000000000',
              'scope': {
                'mint_kinds': ['public'],
                'max_task_wei': '1000000000000000',
              },
            },
        ];
      } else if (r.url.path.endsWith('/rules')) {
        approved?.call(jsonDecode(r.body) as Map<String, dynamic>);
        data = {'status': 'active'};
      } else {
        data = <String, dynamic>{};
      }
      return http.Response(
        jsonEncode(data),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
  await api.login('member', 'test');
  return api;
}

void main() {
  testWidgets(
    'follow does not spend, copy approval binds selected network and explicit limits',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, dynamic>? approved;
      final api = await apiFor(approved: (r) => approved = r);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: MintlyTheme.light(),
            home: const CopyMintsScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Copy minting'), findsOneWidget);
      expect(approved, isNull);
      await tester.tap(find.text('Set up copy'));
      await tester.pumpAndSettle();
      expect(find.text('Copy settings'), findsOneWidget);
      await tester.ensureVisible(find.byType(DropdownButtonFormField<String>));
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('Base ·').last);
      await tester.pumpAndSettle();
      for (final (label, value) in [
        ('Max mint price per NFT', '0.00001'),
        ('Max network fee per mint', '0.0001'),
        ('Total copy budget', '0.001'),
      ]) {
        final field = find.byWidgetPredicate(
          (w) => w is TextField && w.decoration?.labelText == label,
        );
        await tester.scrollUntilVisible(
          field,
          250,
          scrollable: find
              .byWidgetPredicate(
                (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
              )
              .last,
        );
        await tester.enterText(field, value);
        await tester.pump();
      }
      await tester.scrollUntilVisible(
        find.byType(CheckboxListTile),
        250,
        scrollable: find
            .byWidgetPredicate(
              (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
            )
            .last,
      );
      await tester.pumpAndSettle();
      expect(approved, isNull);
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Enable copy minting'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Enable copy minting'));
      await tester.pumpAndSettle();
      expect(approved?['grant_id'], 'policy8453');
      expect(approved?['quantity'], 1);
      expect(approved?['price_cap_eth'], '0.00001');
      expect(approved?['fee_cap_eth'], '0.0001');
      expect(approved?['budget_eth'], '0.001');
      expect(approved?['consent'], true);
      expect(approved?.containsKey('private_key'), false);
      expect(find.text('Copy minting'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final dark in [false, true]) {
    testWidgets(
      'copy section fits a phone in ${dark ? 'dark' : 'light'} theme and has real activity states',
      (tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final font = File('C:/Windows/Fonts/arial.ttf');
        final usePreviewFont =
            font.existsSync() &&
            Platform.environment['MINTLY_TEST_NO_PREVIEW_FONT'] != 'true';
        if (usePreviewFont) {
          final loader = FontLoader('Roboto')
            ..addFont(
              Future.value(ByteData.sublistView(font.readAsBytesSync())),
            );
          await loader.load();
          final iconFile = File(
            '${Platform.environment['FLUTTER_ROOT'] ?? 'C:/Users/USER/develop/flutter'}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
          );
          if (iconFile.existsSync()) {
            final icons = FontLoader('MaterialIcons')
              ..addFont(
                Future.value(ByteData.sublistView(iconFile.readAsBytesSync())),
              );
            await icons.load();
          }
        }
        final api = await apiFor();
        final captureKey = GlobalKey();
        final theme = dark ? MintlyTheme.dark() : MintlyTheme.light();
        await tester.pumpWidget(
          ProviderScope(
            overrides: [apiServiceProvider.overrideWith((ref) => api)],
            child: RepaintBoundary(
              key: captureKey,
              child: MaterialApp(
                debugShowCheckedModeBanner: false,
                theme: theme.copyWith(
                  textTheme: theme.textTheme.apply(fontFamily: 'Roboto'),
                  outlinedButtonTheme: OutlinedButtonThemeData(
                    style: theme.outlinedButtonTheme.style?.copyWith(
                      textStyle: const WidgetStatePropertyAll(
                        TextStyle(
                          fontFamily: 'Roboto',
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                  ),
                  appBarTheme: theme.appBarTheme.copyWith(
                    titleTextStyle: theme.appBarTheme.titleTextStyle?.copyWith(
                      fontFamily: 'Roboto',
                    ),
                  ),
                ),
                home: const CopyMintsScreen(),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        Future<void> capture(String screen) async {
          if (!usePreviewFont) return;
          await tester.runAsync(() async {
            final image =
                await (captureKey.currentContext!.findRenderObject()
                        as RenderRepaintBoundary)
                    .toImage(pixelRatio: 2);
            final bytes = await image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await Directory('build/copy-review').create(recursive: true);
            await File(
              'build/copy-review/${dark ? 'dark' : 'light'}-$screen.png',
            ).writeAsBytes(bytes!.buffer.asUint8List());
            image.dispose();
          });
        }

        await capture('following');
        await tester.tap(find.text('Activity').last);
        await tester.pumpAndSettle();
        expect(find.text('Mint confirmed'), findsOneWidget);
        expect(find.text('Orbit collection'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await capture('activity');
        await tester.tap(find.text('Following').last);
        await tester.pumpAndSettle();
        await tester.tap(find.text('Set up copy'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await capture('settings');
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  testWidgets(
    'empty copy screen does not fabricate followed wallets or mints',
    (tester) async {
      final api = await apiFor(populated: false);
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: MaterialApp(
            theme: MintlyTheme.light(),
            home: const CopyMintsScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('0 wallets followed'), findsOneWidget);
      expect(find.text('mintly.'), findsNothing);
      expect(find.text('Moon scout'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
