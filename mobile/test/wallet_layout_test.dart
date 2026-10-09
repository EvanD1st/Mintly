import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/wallet_screen.dart';
import 'package:mintly/screens/custody_import_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/wallet_secret.dart';
import 'package:mintly/state/app_state.dart';
import 'package:mintly/theme/app_theme.dart';
import 'wallet_secret_test.dart' show firstAddress, phrase;

void main() {
  testWidgets(
    'wallet and setup screens fit a phone; settings and technical details stay separate',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      // Local visual evidence uses a real font. CI only checks layout and behavior.
      final localFont = File('C:/Windows/Fonts/arial.ttf');
      if (localFont.existsSync()) {
        final loader = FontLoader('Roboto')
          ..addFont(
            Future.value(ByteData.sublistView(localFont.readAsBytesSync())),
          );
        await loader.load();
        final icons = File(
          '${Platform.environment['FLUTTER_ROOT'] ?? 'C:/Users/USER/develop/flutter'}/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
        );
        if (icons.existsSync()) {
          final iconLoader = FontLoader('MaterialIcons')
            ..addFont(
              Future.value(ByteData.sublistView(icons.readAsBytesSync())),
            );
          await iconLoader.load();
        }
      }
      final api = ApiService(
        client: MockClient((r) async {
          if (r.url.path.endsWith('/auth/login')) {
            return http.Response(
              '{"token":"token","user":{"username":"member"}}',
              200,
            );
          }
          if (r.url.path.endsWith('/wallets')) {
            return http.Response(
              '[{"id":"wallet","label":"MetaMask","address":"$firstAddress"}]',
              200,
            );
          }
          if (r.url.path.endsWith('/automatic/policies')) {
            return http.Response('[]', 200);
          }
          if (r.url.path.endsWith('/config')) {
            return http.Response(
              '{"chain_id":4663,"automatic_collection_selection":true,"phrase_wallet_setup":true}',
              200,
            );
          }
          return http.Response('{}', 200);
        }),
      );
      await api.login('member', 'test');
      final captureKey = GlobalKey();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiServiceProvider.overrideWith((ref) => api),
            walletSecretResolverProvider.overrideWith(
              (ref) =>
                  (input) async => resolveWalletSecret(input),
            ),
          ],
          child: RepaintBoundary(
            key: captureKey,
            child: MaterialApp(
              debugShowCheckedModeBanner: false,
              theme: MintlyTheme.light().copyWith(
                textTheme: MintlyTheme.light().textTheme.apply(
                  fontFamily: 'Roboto',
                ),
                primaryTextTheme: MintlyTheme.light().primaryTextTheme.apply(
                  fontFamily: 'Roboto',
                ),
                outlinedButtonTheme: OutlinedButtonThemeData(
                  style: MintlyTheme.light().outlinedButtonTheme.style
                      ?.copyWith(
                        textStyle: const WidgetStatePropertyAll(
                          TextStyle(
                            fontFamily: 'Roboto',
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ),
                ),
                appBarTheme: MintlyTheme.light().appBarTheme.copyWith(
                  titleTextStyle: MintlyTheme.light().appBarTheme.titleTextStyle
                      ?.copyWith(fontFamily: 'Roboto'),
                ),
              ),
              home: const Scaffold(body: SafeArea(child: WalletScreen())),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('Add wallet'), findsOneWidget);
      expect(find.text('Unlink'), findsOneWidget);
      expect(find.text('Connect MetaMask'), findsNothing);
      expect(find.text('New drop notifications'), findsNothing);
      expect(find.textContaining('Remaining:'), findsNothing);
      Future<void> capture(String name) async {
        if (!localFont.existsSync()) return;
        await tester.runAsync(() async {
          final image =
              await (captureKey.currentContext!.findRenderObject()
                      as RenderRepaintBoundary)
                  .toImage(pixelRatio: 2);
          final data = await image.toByteData(format: ui.ImageByteFormat.png);
          await Directory('build/wallet-review').create(recursive: true);
          await File(
            'build/wallet-review/$name.png',
          ).writeAsBytes(data!.buffer.asUint8List());
          image.dispose();
        });
      }

      await capture('wallets');
      await tester.tap(find.text('Settings'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('New drop notifications'), 200);
      await tester.pumpAndSettle();
      expect(find.text('New drop notifications'), findsOneWidget);
      expect(find.text('Live source'), findsNothing);
      await capture('account-settings');
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.tap(find.text('MetaMask'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Add or renew a network policy'));
      await tester.tap(find.text('Add or renew a network policy'));
      await tester.pumpAndSettle();
      expect(find.text('Secret recovery phrase'), findsOneWidget);
      expect(find.textContaining('Allowed NFT collection'), findsNothing);
      expect(tester.takeException(), isNull);
      await capture('phrase-import');
      expect(find.text('Private key'), findsNothing);
      await tester.enterText(
        find.byKey(const Key('custody-recovery-phrase')),
        phrase,
      );
      await tester.ensureVisible(find.text('Continue'));
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(find.text('Approve signing limits'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await capture('minting-limits');
    },
  );
}
