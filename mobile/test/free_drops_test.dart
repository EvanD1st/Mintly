import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mintly/screens/free_drops_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

class FreeDropApi extends ApiService {
  FreeDropApi({super.client});
  final approvals = <Map<String, dynamic>>[];
  final submitted = <Map<String, dynamic>>[];
  bool fail = false;
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
        '0.000700000000000000',
      );
      expect(api.submitted, isEmpty);
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
      expect(
        find.text('NFTs per collection: Maximum allowed for this wallet'),
        findsOneWidget,
      );
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
        '0.000500000000000000',
      );
      expect(find.text('Enabled'), findsOneWidget);
      expect(find.byType(CheckboxListTile), findsNothing);
      expect(api.submitted, isEmpty);
      await tester.tap(find.text('Turn off free-drop automation'));
      await tester.pumpAndSettle();
      expect(
        find.text('NFTs per collection: Maximum allowed for this wallet'),
        findsOneWidget,
      );
      expect(
        tester.widget<TextField>(find.byType(TextField).at(0)).controller!.text,
        '0.000500000000000000',
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
