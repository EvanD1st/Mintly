import 'package:flutter/material.dart';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/free_drops_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';

class FreeDropApi extends ApiService {
  FreeDropApi({super.client});
  final approvals = <Map<String, dynamic>>[];
  final submitted = <Map<String, dynamic>>[];
  bool fail = false;
  bool paused = false;
  final expiry = DateTime.now()
      .toUtc()
      .add(const Duration(days: 30))
      .toIso8601String();
  @override
  Future<List<Map<String, dynamic>>> fetchAutomaticPolicies() async => [
    {
      'id': 'g',
      'wallet_id': 'w',
      'chain_id': 1,
      'status': 'enabled',
      'expires_at': expiry,
      'native_symbol': 'ETH',
    },
  ];
  @override
  Future<Map<String, dynamic>> fetchFreeDropApprovals() async => {
    'approvals': approvals,
    'automation_paused': paused,
  };
  @override
  Future<List<Map<String, dynamic>>> fetchWallets() async => [
    {'id': 'w', 'label': 'My wallet'},
  ];
  @override
  Future<void> approveFreeDrops(Map<String, dynamic> request) async {
    submitted.add(Map.of(request));
    if (fail) throw Exception('Signer confirmation pending');
    approvals.add({
      'id': request['request_id'],
      'status': 'active',
      'expires_at': request['expires_at'],
      'snapshot': {
        'wallet_id': 'w',
        'chain_id': 1,
        'grant_id': 'g',
        'quantity': request['quantity'],
        if (request['quantity_mode'] != null)
          'quantity_mode': request['quantity_mode'],
        'fee_cap_wei': '500000000000000',
      },
    });
  }

  @override
  Future<void> revokeFreeDrops(String id) async {
    approvals.first['status'] = 'revoked';
  }
}

class SelectedWalletApi extends FreeDropApi {
  SelectedWalletApi() {
    selectedFeedWallet = 'today-wallet';
    approvals.add({
      'id': 'today-approval',
      'status': 'active',
      'expires_at': expiry,
      'snapshot': {
        'wallet_id': 'today-wallet',
        'chain_id': 8453,
        'grant_id': 'today-grant',
        'quantity': 65535,
        'quantity_mode': 'wallet_max',
        'fee_cap_wei': '700000000000000',
      },
    });
  }
  @override
  Future<List<Map<String, dynamic>>> fetchAutomaticPolicies() async => [
    ...await super.fetchAutomaticPolicies(),
    {
      'id': 'today-grant',
      'wallet_id': 'today-wallet',
      'chain_id': 8453,
      'status': 'enabled',
      'expires_at': expiry,
      'native_symbol': 'ETH',
    },
  ];
  @override
  Future<List<Map<String, dynamic>>> fetchWallets() async => [
    ...await super.fetchWallets(),
    {'id': 'today-wallet', 'label': 'Today wallet'},
  ];
}

void main() {
  for (final dark in [false, true]) {
    testWidgets(
      'free drops ${dark ? 'dark' : 'light'} phone layout keeps details collapsed',
      (tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final output = Platform.environment['MINTLY_FREE_DROP_PREVIEWS'];
        if (output != null) {
          final root =
              '${Platform.environment['FLUTTER_ROOT'] ?? 'C:/Users/USER/develop/flutter'}/bin/cache/artifacts/material_fonts';
          for (final font in {
            'Roboto': 'Roboto-Regular.ttf',
            'MaterialIcons': 'MaterialIcons-Regular.otf',
          }.entries) {
            final file = Directory(root)
                .listSync()
                .whereType<File>()
                .firstWhere(
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
        final api = SelectedWalletApi();
        final capture = GlobalKey();
        await tester.pumpWidget(
          ProviderScope(
            overrides: [apiServiceProvider.overrideWith((ref) => api)],
            child: RepaintBoundary(
              key: capture,
              child: MaterialApp(
                debugShowCheckedModeBanner: false,
                theme: dark ? MintlyTheme.dark() : MintlyTheme.light(),
                home: const FreeDropsScreen(),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Enabled'), findsOneWidget);
        expect(find.text('Maximum allowed for this wallet'), findsOneWidget);
        expect(find.textContaining('@lakzonevn'), findsNothing);
        expect(api.submitted, isEmpty);
        expect(tester.takeException(), isNull);
        if (output != null) {
          await tester.runAsync(() async {
            final shot =
                await (capture.currentContext!.findRenderObject()
                        as RenderRepaintBoundary)
                    .toImage(pixelRatio: 2);
            final data = await shot.toByteData(format: ui.ImageByteFormat.png);
            await Directory(output).create(recursive: true);
            await File(
              '$output/free-drops-${dark ? 'dark' : 'light'}.png',
            ).writeAsBytes(data!.buffer.asUint8List());
            shot.dispose();
          });
        }
        tester.view.physicalSize = const Size(320, 640);
        tester.platformDispatcher.textScaleFactorTestValue = 1.3;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        await tester.pumpAndSettle();
        await tester.scrollUntilVisible(
          find.text('How it works'),
          150,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('How it works'));
        await tester.pumpAndSettle();
        expect(find.textContaining('@lakzonevn'), findsOneWidget);
        expect(tester.takeException(), isNull);
        expect(api.submitted, isEmpty);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
  Future<void> open(WidgetTester tester, FreeDropApi api) async {
    tester.view.physicalSize = const Size(1000, 2000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
        child: const MaterialApp(home: FreeDropsScreen()),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('account pause is clear while saved limits stay visible', (
    tester,
  ) async {
    final api = SelectedWalletApi()..paused = true;
    await open(tester, api);
    expect(find.text('Paused'), findsOneWidget);
    expect(find.text('Resume automation from Wallet.'), findsOneWidget);
    expect(find.text('Enabled'), findsNothing);
    expect(find.text('Maximum allowed for this wallet'), findsOneWidget);
    expect(api.submitted, isEmpty);
  });
  testWidgets('saved gas display preserves one wei without rounding', (
    tester,
  ) async {
    final api = SelectedWalletApi();
    (api.approvals.single['snapshot'] as Map)['fee_cap_wei'] = '1';
    await open(tester, api);
    expect(
      tester.widget<TextField>(find.byType(TextField).first).controller!.text,
      '0.000000000000000001',
    );
    expect(api.submitted, isEmpty);
  });
  for (final reason in {
    'The remaining signing allowance is below your chosen gas cap.':
        'Your signing allowance is below this gas limit.',
    'Waiting for pending mint reservations to settle.':
        'Another mint is using part of your signing allowance.',
  }.entries) {
    testWidgets('short attention message: ${reason.key}', (tester) async {
      final api = SelectedWalletApi();
      api.approvals.single['note'] = reason.key;
      await open(tester, api);
      expect(find.text('Needs attention'), findsOneWidget);
      expect(find.text(reason.value), findsOneWidget);
      expect(api.submitted, isEmpty);
    });
  }
  testWidgets(
    'Manage opens Today wallet and its saved approval without submitting',
    (tester) async {
      final api = SelectedWalletApi();
      await open(tester, api);
      expect(
        tester
            .widget<DropdownButtonFormField<String>>(
              find.byType(DropdownButtonFormField<String>),
            )
            .initialValue,
        'today-grant',
      );
      expect(find.text('Enabled'), findsOneWidget);
      expect(
        tester.widget<TextField>(find.byType(TextField).first).controller!.text,
        '0.0007',
      );
      expect(api.submitted, isEmpty);
      expect(find.text('Free NFTs. Gas still costs money.'), findsOneWidget);
    },
  );
  testWidgets(
    'standing approval needs explicit consent and retries unchanged settings',
    (tester) async {
      final api = FreeDropApi()..fail = true;
      await open(tester, api);
      expect(api.submitted, isEmpty);
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNull,
      );
      expect(find.text('Maximum allowed for this wallet'), findsOneWidget);
      await tester.enterText(find.byType(TextField).first, '0.0005');
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      await tester.tap(find.text('Enable automatic free mints'));
      await tester.pumpAndSettle();
      expect(api.submitted, hasLength(1));
      expect(
        tester.widget<TextField>(find.byType(TextField).at(0)).enabled,
        isFalse,
      );
      api.fail = false;
      await tester.tap(find.text('Enable automatic free mints'));
      await tester.pumpAndSettle();
      expect(api.submitted.length, 2);
      expect(api.submitted[1], api.submitted[0]);
      expect(api.submitted.first['quantity'], 65535);
      expect(api.submitted.first['quantity_mode'], 'wallet_max');
      expect(api.submitted.first['consent'], isTrue);
      expect(find.text('Enabled'), findsOneWidget);
    },
  );
  testWidgets(
    'saved active settings display without asking users to configure again',
    (tester) async {
      final api = FreeDropApi();
      api.approvals.add({
        'id': 'saved',
        'status': 'active',
        'expires_at': api.expiry,
        'snapshot': {
          'wallet_id': 'w',
          'chain_id': 1,
          'grant_id': 'g',
          'quantity': 3,
          'fee_cap_wei': '500000000000000',
        },
      });
      await open(tester, api);
      expect(
        tester.widget<TextField>(find.byType(TextField).at(0)).controller!.text,
        '3',
      );
      expect(
        tester.widget<TextField>(find.byType(TextField).at(1)).controller!.text,
        '0.0005',
      );
      expect(find.text('Enabled'), findsOneWidget);
      expect(find.byType(CheckboxListTile), findsNothing);
      expect(api.submitted, isEmpty);
      await tester.tap(find.text('Turn off free-drop automation'));
      await tester.pumpAndSettle();
      expect(find.text('Maximum allowed for this wallet'), findsOneWidget);
      expect(
        tester.widget<TextField>(find.byType(TextField).at(0)).controller!.text,
        '0.0005',
      );
      expect(
        tester.widget<TextField>(find.byType(TextField).at(0)).enabled,
        isTrue,
      );
      expect(api.submitted, isEmpty);
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pump();
      await tester.tap(find.text('Enable automatic free mints'));
      await tester.pumpAndSettle();
      expect(api.submitted.single['quantity_mode'], 'wallet_max');
      expect(api.submitted.single['quantity'], 65535);
      expect(api.approvals.first['snapshot']['quantity'], 3);
    },
  );
}
