import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';
import '../models/mint_plan_model.dart';

class QueueScreen extends ConsumerWidget {
  const QueueScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

    final hasTasks = state.queue.isNotEmpty;
    final hasPlans = state.mintPlans.isNotEmpty;

    return RefreshIndicator(onRefresh: notifier.loadInitialData, child: ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      children: [
        Text(
          'ACTIVITY',
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.6,
            color: muted,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'Mint plans',
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
          'OpenSea checks the stage and linked wallet. MetaMask asks you to approve each mint.',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        const SizedBox(height: 20),

        if (hasPlans) ...[
          ...state.mintPlans.map((plan) => _planCard(context, notifier, plan, ink, muted, panel, line)),
          const SizedBox(height: 16),
        ],

        if (!hasPlans && !hasTasks) ...[
          const SizedBox(height: 40),
          Center(
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: soft,
                shape: BoxShape.circle,
              ),
              child: Center(
                child: Icon(Icons.timer_outlined, size: 32, color: green),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Center(
            child: Text(
              'No mint plans yet',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: ink),
            ),
          ),
          const SizedBox(height: 8),
          Center(
            child: Text(
              'Import an OpenSea collection link to check its stage and your linked wallet.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: muted, height: 1.4),
            ),
          ),
        ] else if (hasTasks) ...[
          Text('Previous mint task records', style: TextStyle(color: ink, fontWeight: FontWeight.w600)),
          ...state.queue.map((task) {
            return Container(
              margin: const EdgeInsets.only(bottom: 14),
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
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: soft,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          task.status,
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: green,
                          ),
                        ),
                      ),
                      Text(
                        task.timeWatLabel,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: ink,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Row(
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
                            task.dropName,
                            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: ink),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${task.quantity} NFTs · ${task.chain}',
                            style: TextStyle(fontSize: 12, color: muted),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Container(height: 1, color: line),
                  const SizedBox(height: 10),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Total cap', style: TextStyle(fontSize: 12, color: muted)),
                      Text(
                        '${task.totalCapEth} ETH',
                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: ink),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: () async {
                      try {
                        await notifier.disarmTask(task.id);
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                            content: Text('Task disarmed.'),
                          ));
                        }
                      } catch (error) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
                        }
                      }
                    },
                    child: const Text('Disarm task'),
                  ),
                ],
              ),
            );
          }),
          const SizedBox(height: 8),
          Center(
            child: Text(
              'Times shown in WAT. New mints require approval in MetaMask.',
              style: TextStyle(fontSize: 11, color: muted),
            ),
          ),
        ],
        const SizedBox(height: 24),
      ],
    ));
  }

  Widget _planCard(BuildContext context, MintlyNotifier notifier, MintPlanModel plan,
      Color ink, Color muted, Color panel, Color line) {
    final starts = plan.startsAt == null ? 'Time unavailable' :
      '${DateFormat('d MMM, HH:mm').format(plan.startsAt!.toUtc().add(const Duration(hours: 1)))} WAT';
    final ready = plan.status == 'ready_for_approval';
    return Card(color: panel, margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: BorderSide(color: line)),
      child: Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(plan.collectionName, style: TextStyle(color: ink, fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('${plan.chain} · ${plan.stageName ?? 'No scheduled stage'} · $starts',
            style: TextStyle(color: muted)),
          const SizedBox(height: 8),
          Text(plan.statusNote),
          Text('Checked wallet: ${plan.walletAddress.substring(0, 6)}…${plan.walletAddress.substring(plan.walletAddress.length - 4)}',
            style: TextStyle(color: muted, fontSize: 12)),
          const SizedBox(height: 8),
          Text('${plan.quantity} NFT${plan.quantity == 1 ? '' : 's'} · Unit stage price: ${plan.priceEth ?? 'Unknown'} ETH', style: TextStyle(color: muted)),
          Text('Prepared mint value: ${plan.mintValueEth ?? 'Not yet verified'}${plan.mintValueEth == null ? '' : ' ETH'}',
            style: TextStyle(color: ink)),
          Text('Estimated network fee: ${plan.estimatedNetworkFeeEth ?? 'Unavailable'} ETH',
            style: TextStyle(color: muted)),
          Text('Estimated total: ${plan.estimatedTotalEth ?? 'Unavailable'}${plan.estimatedTotalEth == null ? '' : ' ETH'}', style: TextStyle(color: ink, fontWeight: FontWeight.w700)),
          Text('≈ ${plan.estimatedTotalUsdt ?? 'Unavailable'}${plan.estimatedTotalUsdt == null ? '' : ' USDT'}', style: TextStyle(color: ink)),
          Text('Total includes mint value and estimated gas. USDT is a Coinbase ETH-USDT display estimate, not payment in USDT. Missing gas means no complete total.', style: TextStyle(color: muted, fontSize: 11)),
          Text('MetaMask shows the final network fee before approval.',
            style: TextStyle(color: muted, fontSize: 11)),
          const SizedBox(height: 8),
          SelectableText(plan.openSeaUrl, style: TextStyle(color: muted, fontSize: 11)),
          const SizedBox(height: 10),
          Wrap(spacing: 8, children: [
            OutlinedButton(onPressed: () async {
              final controller = TextEditingController(text: '${plan.quantity}');
              final selected = await showDialog<int>(context: context, builder: (dialogContext) => AlertDialog(
                title: const Text('NFT quantity'),
                content: TextField(controller: controller, keyboardType: TextInputType.number, decoration: const InputDecoration(helperText: '1–100; OpenSea checks stage limits')),
                actions: [TextButton(onPressed: () => Navigator.pop(dialogContext), child: const Text('Cancel')),
                  FilledButton(onPressed: () { final quantity = int.tryParse(controller.text); if (quantity != null && quantity >= 1 && quantity <= 100) Navigator.pop(dialogContext, quantity); }, child: const Text('Check quantity'))],
              ));
              if (selected == null) return;
              try { await notifier.importOpenSeaMint(plan.openSeaUrl, quantity: selected, walletId: plan.walletId); }
              catch (error) { if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error'))); }
            }, child: const Text('Change quantity')),
            OutlinedButton(onPressed: () async {
              try {
                await notifier.refreshMintPlan(plan.id);
              } catch (error) {
                if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
              }
            }, child: const Text('Check again')),
            if (ready) FilledButton(onPressed: () async {
              try {
                final latest = await notifier.refreshMintPlan(plan.id);
                if (latest.status != 'ready_for_approval') {
                  throw StateError('OpenSea no longer reports this wallet ready. Check the plan.');
                }
                final uri = Uri.parse(latest.openSeaUrl);
                if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
                  throw StateError('Could not open OpenSea.');
                }
              } catch (error) {
                if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
              }
            }, child: const Text('Open on OpenSea')),
            TextButton(onPressed: () async {
              try { await notifier.removeMintPlan(plan.id); }
              catch (error) {
                if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
              }
            }, child: const Text('Remove')),
          ]),
        ],
      )));
  }
}
