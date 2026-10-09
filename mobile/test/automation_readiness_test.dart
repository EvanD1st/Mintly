import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'package:mintly/widgets/automation_control.dart';
import 'package:mintly/widgets/wallet_readiness_panel.dart';

void main() {
  testWidgets('Pause all needs confirmation and resuming does not enable old actions', (tester) async {
    var changes = 0;
    var paused = false;
    final api = ApiService(client: MockClient((request) async {
      if (request.url.path.endsWith('/auth/login')) return http.Response('{"token":"test","user":{"id":"a","username":"member"}}', 200);
      if (request.url.path.endsWith('/automatic/pause')) {
        changes++;
        paused = jsonDecode(request.body)['paused'] == true;
        return http.Response(jsonEncode({'paused':paused}), 200);
      }
      if (request.url.path.endsWith('/automatic/status')) return http.Response(jsonEncode({'paused':paused}), 200);
      if (request.url.path.endsWith('/drops')) return http.Response('{"drops":[]}', 200);
      if (request.url.path.endsWith('/tasks/queue')) return http.Response('{"tasks":[]}', 200);
      return http.Response('{}', 200);
    }));
    await api.login('member','password');
    await tester.pumpWidget(ProviderScope(overrides:[apiServiceProvider.overrideWith((ref) => api)],
      child: MaterialApp(theme:MintlyTheme.light(), home:const Scaffold(body:AutomationControl()))));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('pause-all-automation')));
    await tester.pumpAndSettle();
    expect(find.textContaining('already signed may still finish'),findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(changes,0);
    await tester.tap(find.byKey(const ValueKey('pause-all-automation')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton,'Pause all').last);
    await tester.pumpAndSettle();
    expect(paused,true);
    expect(find.text('All automation paused'),findsOneWidget);
    await tester.tap(find.text('Resume'));
    await tester.pumpAndSettle();
    expect(find.textContaining('mint plans stay paused'),findsOneWidget);
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(paused,false);
    expect(changes,2);
  });

  testWidgets('Wallet balance is distinct from approval; unavailable is not zero; expiry uses WAT', (tester) async {
    tester.view.physicalSize = const Size(390,844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final readiness = Future.value(<String,dynamic>{'wallets':[
      {'wallet_id':'a','networks':[
        {'network':'Ethereum','balance_wei':'0','gas_status':'Add ETH for gas','approval_status':'active',
          'approved_remaining_wei':'1000000000000000000','approval_expires_at':'2026-10-10T11:00:00Z'},
        {'network':'Base','balance_wei':null,'gas_status':'Network check unavailable','approval_status':'needed','approved_remaining_wei':'0'},
      ]},
      {'wallet_id':'foreign','networks':[{'network':'Foreign secret'}]},
    ]});
    await tester.pumpWidget(MaterialApp(theme:MintlyTheme.light(),home:Scaffold(body:ListView(children:[WalletReadinessPanel(walletId:'a',readiness:readiness)]))));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Network readiness'));
    await tester.pumpAndSettle();
    expect(find.text('ETH balance: 0 ETH'),findsOneWidget);
    expect(find.text('ETH balance: Unavailable'),findsOneWidget);
    expect(find.text('Available spending budget: 1 ETH'),findsOneWidget);
    expect(find.text('Ends 10/10/2026 12:00 WAT'),findsOneWidget);
    expect(find.text('Foreign secret'),findsNothing);
    expect(tester.takeException(),isNull);
  });
}
