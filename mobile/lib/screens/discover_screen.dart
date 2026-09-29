import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../theme/colors.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';
import 'drop_detail_screen.dart';
import 'source_screen.dart';
import 'import_screen.dart';

class DiscoverScreen extends ConsumerWidget {
  const DiscoverScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final soft = MintlyColors.getSoft(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);

    // Format current date in Lagos WAT
    final dateStr = DateFormat('EEEE, d MMMM').format(DateTime.now()).toUpperCase();

    return RefreshIndicator(
      onRefresh: () => notifier.loadInitialData(),
      color: green,
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        children: [
          // Eyebrow & Title
          Text(
            dateStr,
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
              color: muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Find your next mint.',
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w700,
              letterSpacing: -1.0,
              color: ink,
              height: 1.15,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Hey Jenny. Your shortlist is ready.',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 16),

          // Source Card
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: soft,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: panel,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: line, width: 1),
                  ),
                  child: const Center(
                    child: Text(
                      '𝕏',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "LAKZONE’s daily list",
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: ink,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        state.isMonitoring
                            ? 'Last synced 17:02 · ${state.drops.length} drops'
                            : 'Monitoring paused · saved list',
                        style: TextStyle(fontSize: 11, color: muted),
                      ),
                    ],
                  ),
                ),
                TextButton(
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const SourceScreen()),
                    );
                  },
                  style: TextButton.styleFrom(
                    foregroundColor: green,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                  ),
                  child: const Text('View →', style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),

          // Section Header: Today's drops & Import button
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Text(
                    "Today’s drops",
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.3,
                      color: ink,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: soft,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '${state.drops.length}',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: muted),
                    ),
                  ),
                ],
              ),
              TextButton(
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const ImportScreen()),
                  );
                },
                style: TextButton.styleFrom(
                  foregroundColor: green,
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                ),
                child: const Text('+ Import', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ],
          ),
          const SizedBox(height: 10),

          // Filter Chips
          Wrap(
            spacing: 8,
            children: [
              _buildFilterChip('all', 'All drops', state.filter, notifier, ink, panel, line),
              _buildFilterChip('eligible', 'Eligible · 2', state.filter, notifier, ink, panel, line),
              _buildFilterChip('manual', 'Needs review · 1', state.filter, notifier, ink, panel, line),
            ],
          ),
          const SizedBox(height: 14),

          // Drops List
          if (state.isLoading)
            const Center(child: Padding(padding: EdgeInsets.all(32), child: CircularProgressIndicator()))
          else
            ...state.drops.map((drop) => _buildDropCard(context, drop, isDark, ink, muted, line, panel, soft, green, notifier)),

          const SizedBox(height: 16),

          // Footer Status & Recheck
          Container(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Wallet: Jenny · Demo address',
                      style: TextStyle(fontSize: 11, color: muted),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      state.isRechecked
                          ? 'Eligibility refreshed · just now'
                          : 'Eligibility checked at 17:03',
                      style: TextStyle(fontSize: 11, color: muted),
                    ),
                  ],
                ),
                TextButton.icon(
                  onPressed: () {
                    notifier.recheckEligibility();
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Demo scan complete: 2 eligible, 1 needs review.'),
                        duration: Duration(seconds: 2),
                      ),
                    );
                  },
                  icon: Icon(Icons.refresh, size: 14, color: green),
                  label: Text('Recheck', style: TextStyle(color: green, fontWeight: FontWeight.w600, fontSize: 12)),
                  style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 8)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _buildFilterChip(
    String key,
    String label,
    String currentFilter,
    MintlyNotifier notifier,
    Color ink,
    Color panel,
    Color line,
  ) {
    final isSelected = currentFilter == key;
    return GestureDetector(
      onTap: () => notifier.setFilter(key),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? ink : panel,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: isSelected ? ink : line, width: 1),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w500,
            color: isSelected ? (ink == Colors.white ? Colors.black : Colors.white) : ink,
          ),
        ),
      ),
    );
  }

  Widget _buildDropCard(
    BuildContext context,
    DropModel drop,
    bool isDark,
    Color ink,
    Color muted,
    Color line,
    Color panel,
    Color soft,
    Color green,
    MintlyNotifier notifier,
  ) {
    // Select artwork colors
    Color artBg = MintlyColors.artPaperBgLight;
    Color artFg = MintlyColors.artPaperFgLight;
    IconData artIcon = Icons.diamond_outlined;

    if (drop.iconName == 'flower-2') {
      artBg = isDark ? MintlyColors.artOrbitBgDark : MintlyColors.artOrbitBgLight;
      artFg = isDark ? MintlyColors.artOrbitFgDark : MintlyColors.artOrbitFgLight;
      artIcon = Icons.filter_vintage_outlined;
    } else if (drop.iconName == 'moon-star') {
      artBg = isDark ? MintlyColors.artMidnightBgDark : MintlyColors.artMidnightBgLight;
      artFg = isDark ? MintlyColors.artMidnightFgDark : MintlyColors.artMidnightFgLight;
      artIcon = Icons.nights_stay_outlined;
    } else {
      artBg = isDark ? MintlyColors.artPaperBgDark : MintlyColors.artPaperBgLight;
      artFg = isDark ? MintlyColors.artPaperFgDark : MintlyColors.artPaperFgLight;
      artIcon = Icons.diamond_outlined;
    }

    final isManual = drop.statusKind == 'manual';
    final badgeBg = isManual
        ? (isDark ? MintlyColors.warnBgDark : MintlyColors.warnBgLight)
        : soft;
    final badgeFg = isManual
        ? (isDark ? MintlyColors.warnTextDark : MintlyColors.warnTextLight)
        : green;

    final primaryStage = drop.stages.isNotEmpty ? drop.stages.first : null;
    final timeStr = primaryStage != null ? '${primaryStage.startTimeUtc.hour.toString().padLeft(2, '0')}:00' : '18:00';
    final priceStr = primaryStage != null ? '${primaryStage.priceEthStr} ETH' : '0.0002 ETH';

    return GestureDetector(
      onTap: () {
        notifier.selectDrop(drop);
        Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => DropDetailScreen(drop: drop)),
        );
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: panel,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: line, width: 1),
        ),
        child: Column(
          children: [
            // Top Row
            Row(
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: artBg,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Center(
                    child: Icon(artIcon, size: 28, color: artFg),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        drop.name,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: ink,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        '${drop.chain} · ${drop.siteLabel}',
                        style: TextStyle(fontSize: 12, color: muted),
                      ),
                    ],
                  ),
                ),
                Text(
                  priceStr,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: ink,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Container(height: 1, color: line),
            const SizedBox(height: 10),
            // Bottom Row
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: badgeBg,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    drop.statusLabel,
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                      color: badgeFg,
                    ),
                  ),
                ),
                Text(
                  '$timeStr WAT →',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: ink,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
