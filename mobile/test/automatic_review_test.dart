import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/models/drop_model.dart';
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
      final pending = Completer<http.Response>();
      final armedRequests = <Map<String, dynamic>>[];
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
                },
              ]),
              200,
            );
          }
          if (path.endsWith('/tasks/draft')) {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            expect(body['stage_id'], 's');
            expect(body['wallet_id'], 'w');
            return http.Response(
              jsonEncode({
                'eligibility': 'verified',
                'review_hash':
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'snapshot': {
                  'chain': 'Sepolia',
                  'chain_id': 11155111,
                  'contract': address,
                  'account': address,
                  'stage_name': stage.stageName,
                  'mint_kind': 'public',
                  'quantity': 1,
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
          child: MaterialApp(home: AutomaticReviewScreen(drop: drop)),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).first);
      await tester.pumpAndSettle();
      await tester.tap(find.text(address).last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Review limits'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Executing address / recipient:'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Selected public stage · public'),
        findsOneWidget,
      );
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Arm automatic mint'));
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
      await tester.tap(find.text('Arm automatic mint'));
      await tester.pumpAndSettle();
      expect(armedRequests.length, 2);
      expect(armedRequests[1], armedRequests[0]);
      expect(find.text('Signer unavailable'), findsOneWidget);
      expect(find.textContaining('Automatic mint armed.'), findsNothing);
    },
  );
}
