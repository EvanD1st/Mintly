import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';
import 'configure_screen.dart';

class DropDetailScreen extends ConsumerWidget {
  final DropModel drop;

  const DropDetailScreen({super.key, required this.drop});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

    final isManual = drop.statusKind == 'manual';
    final badgeBg = isManual
        ? (isDark ? MintlyColors.warnBgDark : MintlyColors.warnBgLight)
        : soft;
    final badgeFg = isManual
        ? (isDark ? MintlyColors.warnTextDark : MintlyColors.warnTextLight)
        : green;

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
    }

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        leadingWidth: 100,
        leading: TextButton.icon(
          onPressed: () => Navigator.of(context).pop(),
          icon: Icon(Icons.arrow_back, size: 16, color: muted),
          label: Text('All drops', style: TextStyle(color: muted, fontSize: 13)),
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        children: [
          // Hero Row
          Row(
            children: [
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  color: artBg,
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Center(
                  child: Icon(artIcon, size: 36, color: artFg),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${drop.chain.toUpperCase()} · ${drop.siteLabel.toUpperCase()}',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.5,
                        color: muted,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      drop.name,
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.6,
                        color: ink,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
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
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),

          // Your Mint Stages Panel
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: line, width: 1),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Your mint stages',
                      style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: ink),
                    ),
                    Text('WAT', style: TextStyle(fontSize: 11, color: muted, fontWeight: FontWeight.w600)),
                  ],
                ),
                const SizedBox(height: 12),
                Container(height: 1, color: line),
                const SizedBox(height: 12),
                if (isManual)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      "This project’s eligibility checker isn’t supported yet.",
                      style: TextStyle(fontSize: 13, color: muted),
                    ),
                  )
                else
                  ...drop.stages.map((stage) {
                    final time = '${stage.startTimeUtc.hour.toString().padLeft(2, '0')}:00';
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                stage.stageName,
                                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: ink),
                              ),
                              const SizedBox(height: 2),
                              Text('Today at $time', style: TextStyle(fontSize: 12, color: muted)),
                            ],
                          ),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text(
                                '${stage.priceEthStr} ETH',
                                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: ink),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                '${stage.limitPerWallet} per wallet',
                                style: TextStyle(fontSize: 11, color: muted),
                              ),
                            ],
                          ),
                        ],
                      ),
                    );
                  }),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // Checking Wallet Panel
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: line, width: 1),
            ),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Checking for', style: TextStyle(fontSize: 13, color: muted)),
                    Text(
                      "Jenny’s wallet",
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: ink),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Demo address · Checked 17:03', style: TextStyle(fontSize: 11, color: muted)),
                    GestureDetector(
                      onTap: () {
                        notifier.recheckEligibility();
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Demo scan complete: 2 eligible, 1 needs review.')),
                        );
                      },
                      child: Text(
                        'Recheck',
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: green),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // Notice Banner
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: soft,
              borderRadius: const BorderRadius.only(
                topRight: Radius.circular(10),
                bottomRight: Radius.circular(10),
              ),
              border: Border(left: BorderSide(color: green, width: 3)),
            ),
            child: Text(
              isManual
                  ? 'Review this drop on the project’s mint page. Automatic minting is unavailable until its integration is supported.'
                  : 'Eligibility applies to this wallet and stage. Review the mint page before scheduling.',
              style: TextStyle(fontSize: 12, color: ink, height: 1.4),
            ),
          ),
          const SizedBox(height: 24),

          // Primary Button: Set up mint / Automatic mint unavailable
          ElevatedButton.icon(
            onPressed: isManual
                ? null
                : () {
                    notifier.selectDrop(drop);
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const ConfigureScreen()),
                    );
                  },
            icon: const Icon(Icons.timer_outlined, size: 18),
            label: Text(isManual ? 'Automatic mint unavailable' : 'Set up mint'),
          ),
          const SizedBox(height: 10),

          // Secondary Button: View mint page
          OutlinedButton(
            onPressed: () {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Preview only. In the app, this opens the project’s verified mint page.')),
              );
            },
            child: const Text('View mint page ↗'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
