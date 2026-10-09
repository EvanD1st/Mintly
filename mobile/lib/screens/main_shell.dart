import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';
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

class _MainShellState extends ConsumerState<MainShell> with WidgetsBindingObserver {
  int _currentIndex = 0;

  @override
  void initState() { super.initState(); WidgetsBinding.instance.addObserver(this); }
  @override
  void dispose() { WidgetsBinding.instance.removeObserver(this); super.dispose(); }
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) ref.read(mintlyProvider.notifier).loadInitialData();
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
      body: IndexedStack(
        index: _currentIndex,
        children: _screens,
      ),
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
                _buildNavItem(1, Icons.timer_outlined, 'Mint plans', green, muted),
                _buildCopyNavItem(green, muted),
                _buildNavItem(3, Icons.history, 'Activity', green, muted),
                _buildNavItem(4, Icons.account_balance_wallet_outlined, 'Wallet', green, muted),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildNavItem(int index, IconData icon, String label, Color activeColor, Color inactiveColor) {
    final isSelected = _currentIndex == index;
    return InkWell(
      onTap: () {
        setState(() => _currentIndex = index);
        if (index == 1) ref.read(mintlyProvider.notifier).loadInitialData();
      },
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 22,
              color: isSelected ? activeColor : inactiveColor,
            ),
            const SizedBox(height: 3),
            Text(
              label,
              style: TextStyle(
                fontSize: 10,
                fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                color: isSelected ? activeColor : inactiveColor,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCopyNavItem(Color green, Color muted) => InkWell(
    onTap: () => setState(() => _currentIndex = 2),
    child: Padding(padding:const EdgeInsets.symmetric(horizontal:8,vertical:6),child:Column(mainAxisSize:MainAxisSize.min,children:[
      const CopyGlyph('copy',size:22),
      const SizedBox(height:3),Text('Copy',style:TextStyle(fontSize:10,color:_currentIndex == 2 ? green : muted)),
    ])),
  );
}
