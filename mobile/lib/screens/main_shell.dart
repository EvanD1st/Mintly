import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../widgets/main_navigation.dart';
import '../state/app_state.dart';
import '../widgets/network_budget_card.dart';
import '../widgets/collection_thumbnail.dart';
import 'discover_screen.dart';
import 'queue_screen.dart';
import 'history_screen.dart';
import 'copy_mints_screen.dart';
import 'wallet_screen.dart';

class MainShell extends ConsumerStatefulWidget {
  const MainShell({super.key});

  @override
  ConsumerState<MainShell> createState() => _MainShellState();
}

class _MainShellState extends ConsumerState<MainShell>
    with WidgetsBindingObserver {
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _showCopyUpdate());
  }

  Future<void> _showCopyUpdate() async {
    final api = ref.read(apiServiceProvider);
    try {
      if (!await api.showFreePhaseNotice() || !mounted) return;
      final openCopy = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (context) => PopScope(
          canPop: false,
          child: AlertDialog(
            title: const Text('New: copy any eligible free phase'),
            content: const Text(
              'A followed wallet minted in a phase you cannot join? Mintly can now try another free phase you qualify for in the same collection.\n\nGo to Copy, tap Manage for the wallet you follow, select Free mints only, then enable Copy any eligible free phase and approve your settings.\n\nYour saved settings will already be filled in. Gas limits still apply, and FCFS supply is not guaranteed.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Got it'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Go to Copy'),
              ),
            ],
          ),
        ),
      );
      if (!mounted) return;
      if (openCopy == true) _selectTab(2);
      await api.markFreePhaseNoticeSeen();
    } catch (_) {
      // Retry a failed notice check on the next authenticated opening.
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      ref.read(mintlyProvider.notifier).loadInitialData();
      ref.invalidate(networkBudgetsProvider);
      ref.invalidate(collectionArtworkProvider);
    }
  }

  final List<Widget> _screens = const [
    DiscoverScreen(),
    QueueScreen(),
    CopyMintsScreen(),
    HistoryScreen(embedded: true),
    WalletScreen(),
  ];

  void _selectTab(int index) {
    setState(() => _currentIndex = index);
    if (index == 2 || index == 4) ref.invalidate(networkBudgetsProvider);
    if (index == 1) ref.read(mintlyProvider.notifier).loadInitialData();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(toolbarHeight: 0),
    body: MainNavigationScope(
      onSelected: _selectTab,
      child: IndexedStack(index: _currentIndex, children: _screens),
    ),
    bottomNavigationBar: AppNavigationBar(
      selected: _currentIndex,
      onSelected: _selectTab,
    ),
  );
}
