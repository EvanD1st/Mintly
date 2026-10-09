import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/opensea_access_screen.dart';
import 'package:mintly/screens/mint_stages_screen.dart';
import 'package:mintly/models/mint_plan_model.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';

void main(){
  testWidgets('eligibility sign-in needs explicit consent and never sends secrets or mint requests',(tester) async {
    tester.view.physicalSize=const Size(800,1800);tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    var enabled=false;var writes=0;
    final api=ApiService(client:MockClient((r) async {
      if(r.url.path.endsWith('/auth/login')) {return http.Response('{"token":"test","user":{"username":"member"}}',200);}
      expect(r.url.path.endsWith('/wallets/w/opensea-access'),true);
      if(r.method=='POST'){
        writes++;final body=jsonDecode(r.body);
        expect(body,{'enabled':true,'consent':true,'terms_accepted':true});
        expect(r.body.contains('private_key'),false);enabled=true;
      }
      return http.Response(jsonEncode({'wallet_id':'w','available':true,'enabled':enabled,'status':enabled?'active':'disabled'}),200);
    }));
    await api.login('member','password');
    await tester.pumpWidget(ProviderScope(overrides:[apiServiceProvider.overrideWith((ref)=>api)],child:const MaterialApp(home:OpenSeaAccessScreen(walletId:'w'))));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton,'Enable eligibility checks')).onPressed,isNull);
    expect(writes,0);
    await tester.tap(find.byType(CheckboxListTile));await tester.pumpAndSettle();
    await tester.tap(find.text('Enable eligibility checks'));await tester.pumpAndSettle();
    expect(writes,1);expect(find.text('Access: active'),findsOneWidget);
    expect(find.text('Disconnect eligibility access'),findsOneWidget);
    expect(tester.takeException(),isNull);await tester.pumpWidget(const SizedBox());
  });
  testWidgets('stage choice shows eligibility and allowance, blocks ineligible phases, saves only selected phase',(tester) async {
    tester.view.physicalSize=const Size(390,844);tester.view.devicePixelRatio=1;
    addTearDown(tester.view.resetPhysicalSize);addTearDown(tester.view.resetDevicePixelRatio);
    final now=DateTime.now().toUtc();Map<String,dynamic>? chosen;
    final plan={'id':'p','wallet_id':'w','wallet_address':'0x${'11'*20}','collection_name':'Test phases','chain':'Base',
      'contract_address':'0x${'22'*20}','opensea_url':'https://opensea.io/collection/test','quantity':1,'status':'scheduled','status_note':'Upcoming'};
    final api=ApiService(client:MockClient((r) async {
      if(r.url.path.endsWith('/auth/login')) {return http.Response('{"token":"test","user":{"username":"member"}}',200);}
      if(r.url.path.endsWith('/stage')) {chosen=Map<String,dynamic>.from(jsonDecode(r.body));return http.Response(jsonEncode({...plan,'quantity':chosen!['quantity']}),200);}
      return http.Response(jsonEncode({'wallet_id':'w','access_enabled':true,'stages':[
        for(final entry in [('GTD','gtd','eligible',2),('FCFS','fcfs','not_eligible',0),('Public','public','eligible',5)])
          {'id':entry.$2,'name':entry.$1,'eligibility':entry.$3,'remaining':entry.$4,'default_limit':entry.$4,
           'price_wei':'0','starts_at':now.add(const Duration(hours:1)).toIso8601String(),'ends_at':now.add(const Duration(hours:2)).toIso8601String(),'timing':'upcoming','selected':false},
      ]}),200);
    }));await api.login('member','password');
    await tester.pumpWidget(ProviderScope(overrides:[apiServiceProvider.overrideWith((ref)=>api)],child:MaterialApp(home:MintStagesScreen(plan:MintPlanModel.fromJson(plan)))));
    await tester.pumpAndSettle();
    expect(find.text('Available for your wallet: 2 NFTs'),findsOneWidget);
    final options=find.widgetWithText(OutlinedButton,'Choose this phase');
    expect(tester.widget<OutlinedButton>(options.at(1)).onPressed,isNull);
    await tester.ensureVisible(options.first);await tester.pumpAndSettle();await tester.tap(options.first);await tester.pumpAndSettle();
    final quantity=find.byType(TextField);await tester.ensureVisible(quantity);await tester.pumpAndSettle();await tester.enterText(quantity,'2');
    await tester.ensureVisible(find.text('Continue with this phase'));await tester.pumpAndSettle();await tester.tap(find.text('Continue with this phase'));await tester.pumpAndSettle();
    expect(chosen,{'stage_uuid':'gtd','quantity':2});expect(tester.takeException(),isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
