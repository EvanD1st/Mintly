import '../widgets/mintly_notice.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../services/external_url.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';
import '../models/mint_plan_model.dart';
import '../models/drop_model.dart';
import 'automatic_review_screen.dart';
import 'history_screen.dart';

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

    return RefreshIndicator(
      onRefresh: notifier.loadInitialData,
      child: ListView(
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
            'Review a plan and arm its automatic mint. Armed tasks execute on the server while the app is closed.',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 20),
          TextButton(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const HistoryScreen()),
            ),
            child: const Text('View mint history'),
          ),

          ...state.mintPermissions
              .where(
                (permission) =>
                    [
                      'awaiting_signature',
                      'armed',
                      'prepared',
                      'submitted',
                      'uncertain',
                    ].contains(permission['status']) ||
                    permission['can_revoke'] == true,
              )
              .map(
                (permission) => Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (permission['status'] != 'cancelled') ...[
                          Text('Automatic mint: ${permission['status']}'),
                          Text('${permission['note'] ?? ''}'),
                        ],
                        if (permission['tx_hash'] != null)
                          SelectableText('${permission['tx_hash']}'),
                        if ([
                          'awaiting_signature',
                          'armed',
                        ].contains(permission['status']))
                          TextButton(
                            onPressed: () async {
                              try {
                                await notifier.cancelMintPermission(
                                  permission['id'] as String,
                                );
                              } catch (error) {
                                if (context.mounted) {
                                  MintlyNotice.show(context, 
                                    SnackBar(content: Text('$error')),
                                  );
                                }
                              }
                            },
                            child: const Text('Cancel permission'),
                          ),
                        if (permission['can_revoke'] == true)
                          TextButton(
                            onPressed: () async {
                              try {
                                final result = await notifier
                                    .requestMintRevocation(
                                      permission['id'] as String,
                                    );
                                if (context.mounted) {
                                  await _revocationDialog(context, result);
                                }
                              } catch (error) {
                                if (context.mounted) {
                                  MintlyNotice.show(context, 
                                    SnackBar(content: Text('$error')),
                                  );
                                }
                              }
                            },
                            child: const Text('Revoke on-chain'),
                          ),
                      ],
                    ),
                  ),
                ),
              ),

          if (state.isLoading) const LinearProgressIndicator(),
          if (state.error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  'Some data could not refresh. Pull down to retry.\n${state.error}',
                ),
              ),
            ),

          if (hasPlans) ...[
            ...state.mintPlans.map(
              (plan) => _planCard(
                context,
                ref,
                notifier,
                plan,
                ink,
                muted,
                panel,
                line,
              ),
            ),
            const SizedBox(height: 16),
          ],

          if (!hasPlans &&
              !hasTasks &&
              !state.isLoading &&
              state.error == null) ...[
            const SizedBox(height: 40),
            Center(
              child: Container(
                width: 64,
                height: 64,
                decoration: BoxDecoration(color: soft, shape: BoxShape.circle),
                child: Center(
                  child: Icon(Icons.timer_outlined, size: 32, color: green),
                ),
              ),
            ),
            const SizedBox(height: 18),
            Center(
              child: Text(
                'No mint plans yet',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: ink,
                ),
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
            Text(
              'Automatic tasks',
              style: TextStyle(color: ink, fontWeight: FontWeight.w600),
            ),
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
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 3,
                          ),
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
                            child: Icon(
                              Icons.filter_vintage_outlined,
                              size: 24,
                              color: green,
                            ),
                          ),
                        ),
                        const SizedBox(width: 14),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              task.dropName,
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w600,
                                color: ink,
                              ),
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
                        Text(
                          'Total cap',
                          style: TextStyle(fontSize: 12, color: muted),
                        ),
                        Text(
                          '${task.totalCapEth} ETH',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: ink,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text('Status: ${task.status}'),
                    if (task.failureReason != null) Text(task.failureReason!),
                    if (task.transactionHash != null)
                      SelectableText(task.transactionHash!),
                    if (task.explorerUrl != null)
                      TextButton(
                        onPressed: () async {
                          final uri = Uri.tryParse(task.explorerUrl!);
                          if (uri != null &&
                              uri.scheme == 'https' &&
                              uri.host == 'sepolia.etherscan.io') {
                            await openExternalUrl(context, uri);
                          }
                        },
                        child: const Text('View transaction'),
                      ),
                    if ([
                      'prepared',
                      'submitted',
                      'uncertain',
                    ].contains(task.status))
                      const Text(
                        'Transaction may be in flight. A database cancellation cannot undo it.',
                      ),
                    if (['armed', 'preparing'].contains(task.status))
                      OutlinedButton(
                        onPressed: () async {
                          try {
                            await notifier.disarmTask(task.id);
                            if (context.mounted) {
                              MintlyNotice.show(context, 
                                const SnackBar(content: Text('Task disarmed.')),
                              );
                            }
                          } catch (error) {
                            if (context.mounted) {
                              MintlyNotice.show(context, SnackBar(content: Text('$error')));
                            }
                          }
                        },
                        child: const Text('Disarm task'),
                      ),
                    TextButton(
                      onPressed: () async {
                        try {
                          final inFlight = await notifier.removeTask(task.id);
                          if (context.mounted) {
                            MintlyNotice.show(context, 
                              SnackBar(
                                content: Text(
                                  inFlight
                                      ? 'Removed. Transaction tracking continues in Settings → History.'
                                      : 'Removed. Record saved in Settings → History.',
                                ),
                              ),
                            );
                          }
                        } catch (error) {
                          if (context.mounted) {
                            MintlyNotice.show(context, SnackBar(content: Text('$error')));
                          }
                        }
                      },
                      child: const Text('Remove'),
                    ),
                  ],
                ),
              );
            }),
            const SizedBox(height: 8),
            Center(
              child: Text(
                'Times shown in WAT. Only armed tasks authorize automatic execution.',
                style: TextStyle(fontSize: 11, color: muted),
              ),
            ),
          ],
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Future<void> _revocationDialog(
    BuildContext context,
    Map<String, dynamic> result,
  ) => showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Revoke in MetaMask'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Revocation requires your confirmation in MetaMask and costs network gas. It revokes an existing signed permission; it does not mint.',
            ),
            Text(
              'Open ${result['approve_url']} in your MetaMask browser. Enter this code and review the revocation transaction.',
            ),
            SelectableText('${result['code']}'),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () =>
              Clipboard.setData(ClipboardData(text: result['code'] as String)),
          child: const Text('Copy code'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('Done'),
        ),
      ],
    ),
  );

  Widget _planCard(
    BuildContext context,
    WidgetRef ref,
    MintlyNotifier notifier,
    MintPlanModel plan,
    Color ink,
    Color muted,
    Color panel,
    Color line,
  ) {
    final starts = plan.startsAt == null
        ? 'Time unavailable'
        : '${DateFormat('d MMM, HH:mm').format(plan.startsAt!.toUtc().add(const Duration(hours: 1)))} WAT';
    final ready = plan.status == 'ready_for_approval';
    return Card(
      color: panel,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: line),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              plan.collectionName,
              style: TextStyle(
                color: ink,
                fontSize: 17,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '${plan.chain} · ${plan.stageName ?? 'No scheduled stage'} · $starts',
              style: TextStyle(color: muted),
            ),
            const SizedBox(height: 8),
            Text(plan.statusNote),
            Text(
              'Checked wallet: ${plan.walletAddress.substring(0, 6)}…${plan.walletAddress.substring(plan.walletAddress.length - 4)}',
              style: TextStyle(color: muted, fontSize: 12),
            ),
            const SizedBox(height: 8),
            Text(
              '${plan.quantity} NFT${plan.quantity == 1 ? '' : 's'} · Unit stage price: ${plan.priceEth ?? 'Unknown'} ETH',
              style: TextStyle(color: muted),
            ),
            Text(
              'Prepared mint value: ${plan.mintValueEth ?? 'Not yet verified'}${plan.mintValueEth == null ? '' : ' ETH'}',
              style: TextStyle(color: ink),
            ),
            Text(
              'Estimated network fee: ${plan.estimatedNetworkFeeEth ?? 'Unavailable'} ETH',
              style: TextStyle(color: muted),
            ),
            Text(
              'Estimated total: ${plan.estimatedTotalEth ?? 'Unavailable'}${plan.estimatedTotalEth == null ? '' : ' ETH'}',
              style: TextStyle(color: ink, fontWeight: FontWeight.w700),
            ),
            Text(
              '≈ ${plan.estimatedTotalUsdt ?? 'Unavailable'}${plan.estimatedTotalUsdt == null ? '' : ' USDT'}',
              style: TextStyle(color: ink),
            ),
            Text(
              'Total includes mint value and estimated gas. USDT is a Coinbase ETH-USDT display estimate, not payment in USDT. Missing gas means no complete total.',
              style: TextStyle(color: muted, fontSize: 11),
            ),
            Text(
              'MetaMask shows the final network fee before approval.',
              style: TextStyle(color: muted, fontSize: 11),
            ),
            const SizedBox(height: 8),
            SelectableText(
              plan.openSeaUrl,
              style: TextStyle(color: muted, fontSize: 11),
            ),
            const SizedBox(height: 10),
            if ([
              'ready_for_approval',
              'scheduled',
              'unverified',
            ].contains(plan.status))
              FilledButton(
                onPressed: () async {
                  try {
                    final data = await ref
                        .read(apiServiceProvider)
                        .automaticPlanContext(plan.id);
                    if (!context.mounted) return;
                    await Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => AutomaticReviewScreen(
                          drop: DropModel.fromJson(
                            data['drop'] as Map<String, dynamic>,
                          ),
                          plan: MintPlanModel.fromJson(
                            data['plan'] as Map<String, dynamic>,
                          ),
                          initialMintKind: data['mint_kind'] as String,
                        ),
                      ),
                    );
                    await notifier.loadInitialData();
                  } catch (error) {
                    if (context.mounted) {
                      MintlyNotice.show(context, SnackBar(content: Text('$error')));
                    }
                  }
                },
                child: const Text('Set up automatic mint'),
              ),
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton(
                  onPressed: () async {
                    final controller = TextEditingController(
                      text: '${plan.quantity}',
                    );
                    final selected = await showDialog<int>(
                      context: context,
                      builder: (dialogContext) => AlertDialog(
                        title: const Text('NFT quantity'),
                        content: TextField(
                          controller: controller,
                          keyboardType: TextInputType.number,
                          decoration: const InputDecoration(
                            helperText: '1–100; OpenSea checks stage limits',
                          ),
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(dialogContext),
                            child: const Text('Cancel'),
                          ),
                          FilledButton(
                            onPressed: () {
                              final quantity = int.tryParse(controller.text);
                              if (quantity != null &&
                                  quantity >= 1 &&
                                  quantity <= 100) {
                                Navigator.pop(dialogContext, quantity);
                              }
                            },
                            child: const Text('Check quantity'),
                          ),
                        ],
                      ),
                    );
                    if (selected == null) return;
                    try {
                      await notifier.importOpenSeaMint(
                        plan.openSeaUrl,
                        quantity: selected,
                        walletId: plan.walletId,
                      );
                    } catch (error) {
                      if (context.mounted) {
                        MintlyNotice.show(context, SnackBar(content: Text('$error')));
                      }
                    }
                  },
                  child: const Text('Change quantity'),
                ),
                OutlinedButton(
                  onPressed: () async {
                    try {
                      await notifier.refreshMintPlan(plan.id);
                    } catch (error) {
                      if (context.mounted) {
                        MintlyNotice.show(context, SnackBar(content: Text('$error')));
                      }
                    }
                  },
                  child: const Text('Check again'),
                ),
                if (ready)
                  FilledButton(
                    onPressed: () async {
                      try {
                        final latest = await notifier.refreshMintPlan(plan.id);
                        if (latest.status != 'ready_for_approval') {
                          throw StateError(
                            'OpenSea no longer reports this wallet ready. Check the plan.',
                          );
                        }
                        final uri = Uri.parse(latest.openSeaUrl);
                        if (!context.mounted) return;
                        if (!await openExternalUrl(context, uri)) {
                          throw StateError('Could not open OpenSea.');
                        }
                      } catch (error) {
                        if (context.mounted) {
                          MintlyNotice.show(context, SnackBar(content: Text('$error')));
                        }
                      }
                    },
                    child: const Text('Open on OpenSea'),
                  ),
                TextButton(
                  onPressed: () async {
                    try {
                      final inFlight = await notifier.removeMintPlan(plan.id);
                      if (context.mounted) {
                        MintlyNotice.show(context, 
                          SnackBar(
                            content: Text(
                              inFlight
                                  ? 'Removed. Transaction tracking continues in Settings → History.'
                                  : 'Removed. Any unsent mint was canceled; record saved in Settings → History.',
                            ),
                          ),
                        );
                      }
                    } catch (error) {
                      if (context.mounted) {
                        MintlyNotice.show(context, SnackBar(content: Text('$error')));
                      }
                    }
                  },
                  child: const Text('Remove'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
