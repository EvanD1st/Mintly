import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/models/drop_model.dart';
import 'package:mintly/models/mint_plan_model.dart';
import 'package:mintly/screens/automatic_review_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main() {
  testWidgets(
    'review pins exact limits, blocks duplicate taps and preserves key after failed arm',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 2200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final start = DateTime.now().toUtc().add(const Duration(hours: 1));
      const address = '0x1111111111111111111111111111111111111111';
      final stage = MintStageModel(
        id: 's',
        dropId: 'd',
        stageName: 'Selected public stage',
        startTimeUtc: start,
        endTimeUtc: start.add(const Duration(hours: 1)),
        priceWei: 10,
        priceEthStr: '0.00000000000000001',
        limitPerWallet: 2,
        eligibilityStatus: 'unknown',
      );
      final drop = DropModel(
        id: 'd',
        name: 'Test collection',
        chain: 'Sepolia',
        chainId: 11155111,
        contractAddress: address,
        mintPageUrl: 'https://opensea.io/collection/test',
        siteLabel: 'OpenSea',
        iconName: 'gem',
        statusLabel: 'Public',
        statusKind: 'unknown',
        isSupportedIntegration: true,
        isDemo: false,
        stages: [stage],
      );
      final plan = MintPlanModel.fromJson({
        'id': 'plan-id',
        'collection_name': 'Test collection',
        'opensea_url': 'https://opensea.io/collection/test',
        'chain': 'Sepolia',
        'contract_address': address,
        'wallet_address': address,
        'wallet_id': 'w',
        'quantity': 2,
        'status': 'scheduled',
        'status_note': 'Upcoming',
        'estimated_network_fee_eth': '0.0004',
      });
      final pending = Completer<http.Response>();
      final armedRequests = <Map<String, dynamic>>[];
      final scheduled = start.add(const Duration(minutes:10));
      final api = ApiService(
        client: MockClient((request) async {
          final path = request.url.path;
          if (path.endsWith('/auth/login')) {
            return http.Response(
              jsonEncode({
                'token': 'test-token',
                'user': {'username': 'member'},
              }),
              200,
            );
          }
          if (path.endsWith('/automatic/policies')) {
            return http.Response(
              jsonEncode([
                {
                  'id': 'g',
                  'wallet_id': 'w',
                  'account': address,
                  'chain_id': 11155111,
                  'status': 'enabled',
                  'expires_at': start
                      .add(const Duration(minutes: 30))
                      .toIso8601String(),
                },
              ]),
              200,
            );
          }
          if (path.endsWith('/tasks/guided-preview')) {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['stage_id'], 's');
            expect(body['wallet_id'], 'w');
            expect(body['plan_id'], 'plan-id');
            expect(body['quantity'], 2);
            final received=DateTime.parse(body['scheduled_for_utc']).toUtc();
            expect(received.year,scheduled.year);
            expect(received.month,scheduled.month);
            expect(received.day,scheduled.day);
            expect(received.hour,scheduled.hour);
            expect(received.minute,scheduled.minute);
            expect(body['maximum_total_eth'], '0.001');
            expect(body.containsKey('mint_kind'), isFalse);
            expect(body.containsKey('gas_limit_eth'), isFalse);
            return http.Response(
              jsonEncode({
                'request': {...body, 'guided': true, 'mint_kind': 'public', 'price_cap_eth': '0.00000000000000001', 'fee_cap_eth': '0.00099999999999998', 'total_cap_eth': '0.001'},
                'eligibility': 'verified',
                'review_hash':
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'snapshot': {
                  'execute_at': (DateTime.parse(body['scheduled_for_utc']).microsecondsSinceEpoch+999999) ~/ 1000000,
                  'chain': 'Sepolia',
                  'chain_id': 11155111,
                  'contract': address,
                  'account': address,
                  'stage_name': stage.stageName,
                  'mint_kind': 'public',
                  'quantity': 2,
                  'price_wei': 10,
                  'price_cap_wei': 10,
                  'fee_cap_wei': 1000000000000000,
                  'total_cap_wei': 1000000000000010,
                  'expiry':
                      start
                          .add(const Duration(hours: 1))
                          .millisecondsSinceEpoch ~/
                      1000,
                },
              }),
              200,
            );
          }
          if (path.endsWith('/tasks/arm')) {
            armedRequests.add(jsonDecode(request.body) as Map<String, dynamic>);
            if (armedRequests.length == 1) return pending.future;
            return http.Response('{"detail":"Signer unavailable"}', 503);
          }
          throw StateError('Unexpected request: $path');
        }),
      );
      await api.login('member', 'test password');
      await tester.pumpWidget(
        ProviderScope(
          overrides: [apiServiceProvider.overrideWith((ref) => api)],
          child: MaterialApp(
            home: AutomaticReviewScreen(drop: drop, plan: plan),
          ),
        ),
      );
      await tester.pumpAndSettle();
      // A plan selects its exact wallet automatically; no dropdown interaction required.
      expect(find.text(address), findsOneWidget);
      await tester.tap(find.text('Change time'));
      await tester.pumpAndSettle();
      final wat=scheduled.add(const Duration(hours:1));
      String pad(int value)=>value.toString().padLeft(2,'0');
      await tester.enterText(find.byKey(const Key('mint-date-input')),'${pad(wat.day)}/${pad(wat.month)}/${wat.year}');
      await tester.enterText(find.byKey(const Key('mint-time-input')),'${pad(wat.hour)}:${pad(wat.minute)}');
      await tester.tap(find.text('Save time'));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(milliseconds:300));
      await tester.enterText(find.byWidgetPredicate((w) => w is TextField && w.decoration?.labelText == 'Maximum total spend (ETH)'), '0.001');
      expect(find.text('Merkle allowlist'), findsNothing);
      expect(find.text('Signed presale'), findsNothing);
      await tester.tap(find.text('Review limits'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Executing address / recipient:'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Selected public stage · Public mint'),
        findsOneWidget,
      );
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Set automatic'));
      await tester.pump();
      await tester.tap(find.text('Saving…'));
      await tester.pump();
      expect(armedRequests.length, 1);
      expect(
        armedRequests.single['review_hash'],
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      );
      expect(find.textContaining('Automatic mint armed.'), findsNothing);
      pending.complete(http.Response('{"detail":"Response lost"}', 503));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Set automatic'));
      await tester.pumpAndSettle();
      expect(armedRequests.length, 2);
      expect(armedRequests[1], armedRequests[0]);
      expect(find.text('Signer unavailable'), findsOneWidget);
      expect(find.textContaining('Automatic mint armed.'), findsNothing);
    },
  );
}
