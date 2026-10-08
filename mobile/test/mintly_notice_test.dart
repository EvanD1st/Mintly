import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mintly/widgets/mintly_notice.dart';
import 'package:mintly/theme/app_theme.dart';
import 'package:mintly/services/api_service.dart';

Future<void> harness(WidgetTester tester, {bool dark = false, bool reduceMotion = false, double keyboard = 0}) async {
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  tester.view.physicalSize = const Size(390,844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(MintlyNotice.dismissAll);
  await tester.pumpWidget(MaterialApp(
    navigatorKey: MintlyNotice.navigatorKey,
    theme: dark ? MintlyTheme.dark() : MintlyTheme.light(),
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(disableAnimations:reduceMotion, viewInsets:EdgeInsets.only(bottom:keyboard)),
      child:child!,
    ),
    home: Scaffold(body:Builder(builder:(context) => Center(child:TextButton(
      onPressed:() => MintlyNotice.show(context,const SnackBar(content:Text('Settings saved'), duration:Duration(seconds:1))),
      child:const Text('Show notice'),
    )))),
  ));
}

void main() {
  for (final dark in [false,true]) {
    testWidgets('notice matches ${dark ? 'dark' : 'light'} theme and fades without vertical motion', (tester) async {
      await harness(tester,dark:dark);
      await tester.tap(find.text('Show notice'));
      await tester.pump();
      final card = find.byKey(const Key('mintly-notice-card'));
      final rect = tester.getRect(card);
      await tester.pump();
      await tester.pump(const Duration(milliseconds:90));
      expect(tester.getRect(card),rect);
      final fade = find.ancestor(of:card,matching:find.byType(AnimatedOpacity));
      expect(fade,findsOneWidget);
      expect(find.byType(SnackBar),findsNothing);
      final opacity = tester.widget<FadeTransition>(find.descendant(of:fade,matching:find.byType(FadeTransition)).first).opacity.value;
      expect(opacity,greaterThan(0));
      expect(opacity,lessThan(1));
      final material = tester.widget<Material>(card);
      expect(material.color,dark ? MintlyTheme.dark().colorScheme.surface : MintlyTheme.light().colorScheme.surface);
      await tester.pump(const Duration(milliseconds:150));
      expect(tester.getRect(card),rect);
      await tester.pump(const Duration(seconds:1));
      await tester.pump(const Duration(milliseconds:200));
      expect(find.text('Settings saved'),findsNothing);
      expect(tester.takeException(),isNull);
    });
  }
  testWidgets('latest notice replaces earlier one, close works, and account reset clears it', (tester) async {
    await harness(tester);
    await tester.tap(find.text('Show notice'));
    await tester.pumpAndSettle();
    MintlyNotice.showGlobal(const SnackBar(content:Text('Another message')));
    await tester.pumpAndSettle();
    expect(find.text('Settings saved'),findsNothing);
    expect(find.text('Another message'),findsOneWidget);
    await tester.tap(find.byTooltip('Dismiss message'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds:200));
    expect(find.text('Another message'),findsNothing);
    MintlyNotice.showGlobal(const SnackBar(content:Text('Account A message')));
    await tester.pumpAndSettle();
    ApiService().disconnectBackend();
    await tester.pump();
    expect(find.text('Account A message'),findsNothing);
    expect(tester.takeException(),isNull);
  });
  testWidgets('reduced motion appears immediately and stays above keyboard', (tester) async {
    await harness(tester,reduceMotion:true,keyboard:300);
    MintlyNotice.showGlobal(const SnackBar(content:Text('Settings saved')));
    await tester.pump();
    final card = find.byKey(const Key('mintly-notice-card'));
    expect(tester.getRect(card).bottom,lessThanOrEqualTo(844-300-16));
    final fade = tester.widget<AnimatedOpacity>(find.ancestor(of:card,matching:find.byType(AnimatedOpacity)));
    expect(fade.duration,Duration.zero);
    expect(fade.opacity,1);
    await tester.tap(find.byTooltip('Dismiss message'));
    await tester.pump();
    expect(card,findsNothing);
  });
  testWidgets('backgrounding clears an account notice and cancels timers', (tester) async {
    await harness(tester);
    await tester.tap(find.text('Show notice'));
    await tester.pumpAndSettle();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(find.text('Settings saved'),findsNothing);
    await tester.pump(const Duration(seconds:2));
    expect(tester.takeException(),isNull);
  });
}
