import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';

class SourceScreen extends ConsumerWidget {
  const SourceScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

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
          Text(
            'YOUR DAILY SOURCE',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
              color: muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'LAKZONE',
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
            '@lakzonevn · sample post preview',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 18),

          // Drops Post Panel
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: line, width: 1),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Daily Mint Drops · September 29',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: ink),
                ),
                const SizedBox(height: 6),
                Text(
                  'Sample content for this UI draft',
                  style: TextStyle(fontSize: 12, color: muted),
                ),
                const SizedBox(height: 14),
                Container(height: 1, color: line),
                const SizedBox(height: 10),
                ...state.drops.map((drop) {
                  final stage = drop.stages.isNotEmpty ? drop.stages.first : null;
                  final time = stage != null ? '${stage.startTimeUtc.hour.toString().padLeft(2, '0')}:00' : '18:00';
                  final price = stage != null ? '${stage.priceEthStr} ETH' : '0.0002 ETH';
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          drop.name,
                          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: ink),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          '${drop.chain} · $time WAT\n${drop.siteLabel} · $price',
                          style: TextStyle(fontSize: 12, color: muted, height: 1.35),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // Notice
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
              'Original posts and later corrections stay attached to the imported list.',
              style: TextStyle(fontSize: 12, color: ink, height: 1.4),
            ),
          ),
          const SizedBox(height: 24),

          ElevatedButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Review the drops'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
