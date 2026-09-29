import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';
import 'review_screen.dart';

class ConfigureScreen extends ConsumerStatefulWidget {
  const ConfigureScreen({super.key});

  @override
  ConsumerState<ConfigureScreen> createState() => _ConfigureScreenState();
}

class _ConfigureScreenState extends ConsumerState<ConfigureScreen> {
  late TextEditingController _feeController;

  @override
  void initState() {
    super.initState();
    final state = ref.read(mintlyProvider);
    _feeController = TextEditingController(text: state.feeCap);
  }

  @override
  void dispose() {
    _feeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
    final stage = state.selectedStage ?? (drop != null && drop.stages.isNotEmpty ? drop.stages.first : null);

    if (drop == null || stage == null) {
      return Scaffold(
        appBar: AppBar(),
        body: const Center(child: Text('No drop selected.')),
      );
    }

    final double unitPrice = double.tryParse(stage.priceEthStr) ?? 0.0;
    final double fee = double.tryParse(state.feeCap) ?? 0.0001;
    final double totalCap = (state.selectedQty * unitPrice) + fee;
    final totalCapStr = totalCap.toStringAsFixed(6).replaceAll(RegExp(r'0+$'), '').replaceAll(RegExp(r'\.$'), '');

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        leadingWidth: 120,
        leading: TextButton.icon(
          onPressed: () => Navigator.of(context).pop(),
          icon: Icon(Icons.arrow_back, size: 16, color: muted),
          label: Text('Drop details', style: TextStyle(color: muted, fontSize: 13)),
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        children: [
          Text(
            'PLAN YOUR MINT',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
              color: muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Ready before the drop.',
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
            'Choose your limits. You’ll review before arming.',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 18),

          // Drop Summary Panel
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: line, width: 1),
            ),
            child: Row(
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: soft,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Center(
                    child: Icon(Icons.filter_vintage_outlined, size: 24, color: green),
                  ),
                ),
                const SizedBox(width: 14),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      drop.name,
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: ink),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${drop.chain} · ${stage.stageName} · ${stage.startTimeUtc.hour.toString().padLeft(2, '0')}:00 WAT',
                      style: TextStyle(fontSize: 12, color: muted),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),

          // Minting Wallet
          Text(
            'Minting wallet',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ink),
          ),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: line, width: 1),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Jenny · Demo address', style: TextStyle(fontSize: 14, color: ink)),
                Icon(Icons.keyboard_arrow_down, size: 20, color: muted),
              ],
            ),
          ),
          const SizedBox(height: 18),

          // Quantity Counter
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Quantity',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ink),
              ),
              Text(
                '· Max ${stage.limitPerWallet}',
                style: TextStyle(fontSize: 11, color: muted),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: line, width: 1),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                IconButton(
                  onPressed: state.selectedQty > 1 ? () => notifier.decrementQuantity() : null,
                  icon: const Icon(Icons.remove),
                  style: IconButton.styleFrom(
                    backgroundColor: soft,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                ),
                Text(
                  '${state.selectedQty}',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: ink),
                ),
                IconButton(
                  onPressed: state.selectedQty < stage.limitPerWallet ? () => notifier.incrementQuantity() : null,
                  icon: const Icon(Icons.add),
                  style: IconButton.styleFrom(
                    backgroundColor: soft,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 18),

          // Max Transaction Fee
          Text(
            'Maximum transaction fee (ETH)',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ink),
          ),
          const SizedBox(height: 6),
          TextField(
            controller: _feeController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            style: TextStyle(fontSize: 15, color: ink, fontWeight: FontWeight.w500),
            onChanged: (val) {
              notifier.setFeeCap(val);
            },
            decoration: InputDecoration(
              hintText: '0.0001',
              suffixText: 'ETH',
              suffixStyle: TextStyle(color: muted, fontSize: 13),
            ),
          ),
          const SizedBox(height: 20),

          // Money Summary Panel
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: panel,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: line, width: 1),
            ),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Mint price cap · each', style: TextStyle(fontSize: 12, color: muted)),
                    Text('${stage.priceEthStr} ETH', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: ink)),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text('Total spending cap', style: TextStyle(fontSize: 12, color: muted)),
                    Text('$totalCapStr ETH', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: green)),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          Text(
            'Skip if the mint price rises or fees exceed your cap. Stop when your selected quantity is minted.',
            style: TextStyle(fontSize: 11, color: muted, height: 1.4),
          ),
          const SizedBox(height: 24),

          // Primary Button: Review mint
          ElevatedButton(
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ReviewScreen()),
              );
            },
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text('Review mint'),
                SizedBox(width: 8),
                Icon(Icons.arrow_forward, size: 16),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
