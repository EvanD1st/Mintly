import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'theme/app_theme.dart';
import 'screens/splash_screen.dart';
import 'services/push_service.dart';
import 'services/wallet_licenses.dart';
import 'widgets/mintly_notice.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  registerWalletLicenses();
  await PushService.instance.initialize();
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  runApp(const ProviderScope(child: MintlyApp()));
}

class MintlyApp extends StatelessWidget {
  const MintlyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Mintly',
      debugShowCheckedModeBanner: false,
      scaffoldMessengerKey: PushService.instance.messengerKey,
      navigatorKey: MintlyNotice.navigatorKey,
      theme: MintlyTheme.light(),
      darkTheme: MintlyTheme.dark(),
      themeMode: ThemeMode.system,
      home: const SplashScreen(),
    );
  }
}
