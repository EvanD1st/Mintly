import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import 'discover_screen.dart';
import 'queue_screen.dart';
import 'activity_screen.dart';
import 'wallet_screen.dart';

class MainShell extends ConsumerStatefulWidget {
  const MainShell({super.key});

  @override
  ConsumerState<MainShell> createState() => _MainShellState();
}

class _MainShellState extends ConsumerState<MainShell> {
  int _currentIndex = 0;

  final List<Widget> _screens = const [
    DiscoverScreen(),
    QueueScreen(),
    ActivityScreen(),
    WalletScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final ink = MintlyColors.getInk(isDark);
    final green = MintlyColors.getGreen(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final line = MintlyColors.getLine(isDark);
    final soft = MintlyColors.getSoft(isDark);

    return Scaffold(
      backgroundColor: bg,
      appBar: PreferredSize(
        preferredSize: const Size.fromHeight(64),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                // Brand Wordmark + Logo
                Row(
                  children: [
                    Container(
                      width: 32,
                      height: 32,
                      decoration: BoxDecoration(
                        color: green,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Center(
                        child: Icon(Icons.adjust, size: 20, color: Colors.white),
                      ),
                    ),
                    const SizedBox(width: 8),
                    RichText(
                      text: TextSpan(
                        style: TextStyle(
                          fontSize: 25,
                          fontWeight: FontWeight.w700,
                          letterSpacing: -1.0,
                          color: ink,
                          fontFamily: 'Roboto',
                        ),
                        children: [
                          const TextSpan(text: 'mintly'),
                          TextSpan(
                            text: '.',
                            style: TextStyle(color: green),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                // Jenny's Avatar
                GestureDetector(
                  onTap: () {
                    setState(() => _currentIndex = 3); // switch to wallet tab
                  },
                  child: Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(
                      color: soft,
                      shape: BoxShape.circle,
                      border: Border.all(color: line, width: 1),
                    ),
                    child: Center(
                      child: Text(
                        'J',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: ink,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
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
                _buildNavItem(1, Icons.timer_outlined, 'Queue', green, muted),
                _buildNavItem(2, Icons.history, 'Activity', green, muted),
                _buildNavItem(3, Icons.account_balance_wallet_outlined, 'Wallet', green, muted),
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
      onTap: () => setState(() => _currentIndex = index),
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
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
}
