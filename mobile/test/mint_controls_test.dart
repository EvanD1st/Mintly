import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/push_service.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'package:mintly/widgets/mint_progress.dart';
import 'package:mintly/widgets/daily_budget_control.dart';
import 'package:mintly/screens/copy_mints_screen.dart';

Map<String, dynamic> progressData(String state) => {
  'label': state == 'included' ? 'Included — waiting for confirmations' : 'Checking transaction status',
  'steps': [for (final entry in [('checking','Checking wallet'),('preparing','Preparing'),('sent','Sent'),('included','Included'),('confirmed','Confirmed')])
    {'key':entry.$1,'label':entry.$2,'state':entry.$1 == 'confirmed' ? 'pending' : entry.$1 == state ? 'current' : 'complete'}],
};

void main() {
  for (final dark in [false,true]) {
    testWidgets('Progress fits a small phone and distinguishes inclusion: $dark', (tester) async {
      tester.view.physicalSize = const Size(360,800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(theme:dark ? MintlyTheme.dark() : MintlyTheme.light(),
        home:Scaffold(body:Padding(padding:const EdgeInsets.all(16),child:MintProgress(progress:progressData('included'))))));
      expect(find.text('Included — waiting for confirmations'),findsOneWidget);
      expect(tester.takeException(),isNull);
    });
  }

  testWidgets('Daily limit requires explicit confirmation and does not reset pending spending', (tester) async {
    Map<String,dynamic>? saved;
    final api = ApiService(client:MockClient((request) async {
      if (request.url.path.endsWith('/auth/login')) return http.Response('{"token":"test","user":{"id":"member","username":"member"}}',200);
      if (request.method == 'POST') saved = jsonDecode(request.body) as Map<String,dynamic>;
      return http.Response(jsonEncode({'limit_wei':'1000000000000000','spent_wei':'100000000000000',
        'reserved_wei':'200000000000000','remaining_wei':'700000000000000','status':'active'}),200);
    }));
    await api.login('member','password');
    await tester.pumpWidget(ProviderScope(overrides:[apiServiceProvider.overrideWith((ref)=>api)],
      child:MaterialApp(theme:MintlyTheme.light(),home:const Scaffold(body:DailyBudgetControl()))));
    await tester.pumpAndSettle();
    expect(find.text('Pending maximum: 0.0002 ETH'),findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('daily-limit-input')),'0.002');
    await tester.tap(find.byKey(const ValueKey('save-daily-limit')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Pending transactions keep counting'),findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(saved,isNull);
    await tester.tap(find.byKey(const ValueKey('save-daily-limit')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved,{'limit_eth':'0.002','consent':true});
    expect(find.text('Pending maximum: 0.0002 ETH'),findsOneWidget);
  });

  testWidgets('Check-only setup uses an owned wallet without a signing policy and never approves a grant', (tester) async {
    tester.view.physicalSize = const Size(390,844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    Map<String,dynamic>? checked;
    var approvals = 0;
    final api = ApiService(client:MockClient((request) async {
      if (request.url.path.endsWith('/auth/login')) return http.Response('{"token":"test","user":{"id":"member","username":"member"}}',200);
      if (request.url.path.endsWith('/automatic/policies')) return http.Response('[]',200);
      if (request.url.path.endsWith('/wallets')) return http.Response('[{"id":"receiver","label":"My wallet","address":"0x${'2'*40}"}]',200);
      if (request.url.path.endsWith('/checks') && request.method == 'POST') {
        checked = jsonDecode(request.body) as Map<String,dynamic>;
        return http.Response('{"check_only":true}',200);
      }
      if (request.url.path.endsWith('/wallet-rules')) approvals++;
      return http.Response('{}',200);
    }));
    await api.login('member','password');
    await tester.pumpWidget(ProviderScope(overrides:[apiServiceProvider.overrideWith((ref)=>api)],
      child:MaterialApp(theme:MintlyTheme.light(),home:CopySettingsScreen(watch:{'id':'watch','label':'Followed wallet','address':'0x${'1'*40}','chains':[1,8453,4663],'preferences':{}}))));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(SwitchListTile,'Check-only mode'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Receiving wallet'),150);
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('My wallet').last);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Max mint price per NFT'),180);
    await tester.enterText(find.widgetWithText(TextFormField,'Max mint price per NFT'),'0');
    await tester.enterText(find.widgetWithText(TextFormField,'Gas spending limit'),'0.0005');
    await tester.scrollUntilVisible(find.text('Total copy budget'),180);
    await tester.enterText(find.widgetWithText(TextFormField,'Total copy budget'),'0.001');
    await tester.scrollUntilVisible(find.textContaining('Start check-only monitoring'),180);
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Start check-only'),100);
    await tester.tap(find.text('Start check-only'));
    await tester.pumpAndSettle();
    expect(approvals,0);
    expect(checked?['wallet_id'],'receiver');
    expect(checked?.containsKey('grant_ids'),false);
    expect(checked?.containsKey('consent'),false);
  });

  test('Wallet alerts must belong to the signed-in account', () async {
    final api=ApiService(client:MockClient((request) async=>http.Response('{"token":"test","user":{"id":"member","username":"member"}}',200)));
    await api.login('member','password');
    await PushService.instance.connect(api);
    expect(PushService.instance.acceptsMessage({'category':'wallet_alerts'}),false);
    expect(PushService.instance.acceptsMessage({'category':'wallet_alerts','user_id':'foreign'}),false);
    expect(PushService.instance.acceptsMessage({'category':'wallet_alerts','user_id':'member'}),true);
    await PushService.instance.disconnect();
    api.dispose();
  });
}
