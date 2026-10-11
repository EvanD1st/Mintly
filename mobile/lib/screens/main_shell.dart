import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
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

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final green = MintlyColors.getGreen(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final line = MintlyColors.getLine(isDark);

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(toolbarHeight: 0),
      body: IndexedStack(index: _currentIndex, children: _screens),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: panel,
          border: Border(top: BorderSide(color: line, width: 1)),
        ),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _buildNavItem(0, Icons.today, 'Today', green, muted),
                _buildNavItem(
                  1,
                  Icons.timer_outlined,
                  'Mint plans',
                  green,
                  muted,
                ),
                _buildNavItem(2, Icons.history, 'Copy', green, muted),
                _buildNavItem(3, Icons.history, 'Activity', green, muted),
                _buildNavItem(
                  4,
                  Icons.account_balance_wallet_outlined,
                  'Wallet',
                  green,
                  muted,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildNavItem(
    int index,
    IconData icon,
    String label,
    Color activeColor,
    Color inactiveColor,
  ) {
    final isSelected = _currentIndex == index;
    return Expanded(
      child: InkWell(
        onTap: () {
          setState(() => _currentIndex = index);
          if (index == 2 || index == 4) ref.invalidate(networkBudgetsProvider);
          if (index == 1) ref.read(mintlyProvider.notifier).loadInitialData();
        },
        borderRadius: BorderRadius.circular(12),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          decoration: BoxDecoration(
            color: isSelected
                ? activeColor.withValues(alpha: .12)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(14),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 10),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (index == 2)
                CopyGlyph(
                  'copy',
                  size: 22,
                  color: isSelected ? activeColor : inactiveColor,
                )
              else
                Icon(
                  icon,
                  size: 22,
                  color: isSelected ? activeColor : inactiveColor,
                ),
              const SizedBox(height: 3),
              Text(
                label,
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                  color: isSelected ? activeColor : inactiveColor,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
