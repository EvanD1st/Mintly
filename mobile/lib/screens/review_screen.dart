import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';
import 'success_screen.dart';

class ReviewScreen extends ConsumerWidget {
  const ReviewScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

    final drop = state.selectedDrop;
    final stage = state.selectedStage;

    if (drop == null || stage == null) {
      return Scaffold(
        appBar: AppBar(),
        body: const Center(child: Text('No task to review.')),
      );
    }

    final double unitPrice = double.tryParse(stage.priceEthStr) ?? 0.0;
    final double fee = double.tryParse(state.feeCap) ?? 0.0001;
    final double totalCap = (state.selectedQty * unitPrice) + fee;
    final totalCapStr = totalCap.toStringAsFixed(6).replaceAll(RegExp(r'0+$'), '').replaceAll(RegExp(r'\.$'), '');
    final timeStr = '${stage.startTimeUtc.hour.toString().padLeft(2, '0')}:00';

    final rows = [
      ['Wallet', 'Jenny · Demo address'],
      ['Network', drop.chain],
      ['Stage', stage.stageName],
      ['Start', 'Today · $timeStr WAT'],
      ['Quantity', '${state.selectedQty} NFTs'],
      ['Mint price cap', '${stage.priceEthStr} ETH each'],
      ['Fee cap', '${state.feeCap} ETH'],
      ['Total cap', '$totalCapStr ETH'],
    ];

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        leadingWidth: 120,
        leading: TextButton.icon(
          onPressed: () => Navigator.of(context).pop(),
          icon: Icon(Icons.arrow_back, size: 16, color: muted),
          label: Text('Edit setup', style: TextStyle(color: muted, fontSize: 13)),
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        children: [
          Text(
            'FINAL REVIEW',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
              color: muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Your mint, your limits.',
            style: TextStyle(
              fontSize: 26,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.8,
              color: ink,
              height: 1.15,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Review the task before automatic submission.',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 18),

          // Breakdown Panel
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
                  drop.name,
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: ink),
                ),
                const SizedBox(height: 12),
                Container(height: 1, color: line),
                const SizedBox(height: 12),
                ...rows.map((row) {
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(row[0], style: TextStyle(fontSize: 12, color: muted)),
                        Text(
                          row[1],
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: row[0] == 'Total cap' ? green : ink,
                          ),
                        ),
                      ],
                    ),
                  );
                }),
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
              'Demo signing is ready. The real app must verify signing access before a task can be armed.',
              style: TextStyle(fontSize: 12, color: ink, height: 1.4),
            ),
          ),
          const SizedBox(height: 16),

          // Consent Checkbox
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Checkbox(
                value: state.isConsentChecked,
                activeColor: green,
                onChanged: (val) => notifier.setConsent(val ?? false),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'I authorize this task within the limits above. A successful mint is not guaranteed.',
                    style: TextStyle(fontSize: 12, color: muted, height: 1.4),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),

          // Primary Arm Button
          ElevatedButton.icon(
            onPressed: state.isConsentChecked
                ? () async {
                    final task = await notifier.armCurrentTask();
                    if (context.mounted && task != null) {
                      Navigator.of(context).pushReplacement(
                        MaterialPageRoute(builder: (_) => SuccessScreen(task: task)),
                      );
                    }
                  }
                : null,
            icon: const Icon(Icons.flash_on, size: 18),
            label: const Text('Arm demo mint'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
