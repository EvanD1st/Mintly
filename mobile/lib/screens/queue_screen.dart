import '../widgets/mintly_notice.dart';
import '../widgets/mint_progress.dart';
import '../widgets/automation_control.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../services/external_url.dart';
import '../state/app_state.dart';
import '../models/mint_plan_model.dart';
import '../models/drop_model.dart';
import 'automatic_review_screen.dart';
import 'history_screen.dart';
import 'mint_stages_screen.dart';

import '../models/task_model.dart';
import '../widgets/screen_components.dart';
import '../widgets/collection_thumbnail.dart';

class QueueScreen extends ConsumerStatefulWidget {
  const QueueScreen({super.key});
  @override
  ConsumerState<QueueScreen> createState() => _QueueScreenState();
}

class _QueueScreenState extends ConsumerState<QueueScreen> {
  String _filter = 'all';
  @override
  Widget build(BuildContext context) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);
    final scheme = Theme.of(context).colorScheme;
    const activeStatuses = [
      'armed',
      'preparing',
      'prepared',
      'submitted',
      'uncertain',
    ];
    final activePlans = state.queue
        .where((task) => activeStatuses.contains(task.status))
        .map((task) => task.planId)
        .whereType<String>()
        .toSet();
    final plans = state.mintPlans
        .where(
          (p) =>
              (_filter == 'all' || _filter == 'review') &&
              !activePlans.contains(p.id),
        )
        .toList();
    final tasks = state.queue
        .where(
          (t) =>
              _filter == 'all' ||
              (_filter == 'tasks' && activeStatuses.contains(t.status)),
        )
        .toList();
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(collectionArtworkProvider);
        await notifier.loadInitialData();
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
        children: [
          const ScreenHeading(
            'Mint plans',
            'Review saved plans. Track armed mints.',
          ),
          const AutomationControl(compact: true),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final item in [
                ('all', 'All'),
                ('review', 'Saved'),
                ('tasks', 'Armed / active'),
              ])
                ChoiceChip(
                  label: Text(item.$2),
                  selected: _filter == item.$1,
                  onSelected: (_) => setState(() => _filter = item.$1),
                ),
            ],
          ),
          const SizedBox(height: 20),
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
          if (tasks.isNotEmpty) ...[
            _section('Automatic mints', tasks.length),
            ...tasks.map((task) => _taskCard(context, notifier, task)),
            const SizedBox(height: 12),
          ],
          if (plans.isNotEmpty) ...[
            _section('Saved plans', plans.length),
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text(
                'Review and approve a plan before automatic execution.',
                style: TextStyle(fontSize: 12),
              ),
            ),
            ...plans.map((plan) => _planCard(context, notifier, plan)),
          ],
          if (plans.isEmpty &&
              tasks.isEmpty &&
              !state.isLoading &&
              state.error == null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 40),
              child: Column(
                children: [
                  Icon(Icons.timer_outlined, size: 40, color: scheme.primary),
                  const SizedBox(height: 16),
                  Text(
                    _filter == 'all'
                        ? 'No mint plans yet'
                        : 'No matching mints',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Import an OpenSea collection link to check its stage and your linked wallet.',
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          if (state.mintPermissions.isNotEmpty)
            ExpansionTile(
              title: const Text('Wallet permissions'),
              subtitle: const Text('Manage approvals and revocations'),
              children: [
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
                                        MintlyNotice.show(
                                          context,
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
                                        await _revocationDialog(
                                          context,
                                          result,
                                        );
                                      }
                                    } catch (error) {
                                      if (context.mounted) {
                                        MintlyNotice.show(
                                          context,
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
              ],
            ),
          TextButton(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const HistoryScreen()),
            ),
            child: const Text('View mint history'),
          ),
          const Text(
            'Times shown in WAT. Only armed tasks authorize automatic execution.',
            style: TextStyle(fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _section(String title, int count) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Row(
      children: [
        Flexible(
          child: Text(
            title,
            style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
          ),
        ),
        const SizedBox(width: 10),
        Text(
          '$count',
          style: TextStyle(color: Theme.of(context).colorScheme.primary),
        ),
      ],
    ),
  );

  Widget _planCard(
    BuildContext context,
    MintlyNotifier notifier,
    MintPlanModel plan,
  ) {
    void details() {
      final colors = Theme.of(context).colorScheme;
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (detailContext) => Consumer(
            builder: (context, detailRef, _) {
              final current =
                  detailRef
                      .watch(mintlyProvider)
                      .mintPlans
                      .where((p) => p.id == plan.id)
                      .firstOrNull ??
                  plan;
              return Scaffold(
                appBar: AppBar(title: const Text('Plan details')),
                body: ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    _planDetails(
                      context,
                      detailRef,
                      notifier,
                      current,
                      colors.onSurface,
                      colors.onSurface.withValues(alpha: .65),
                      colors.surface,
                      colors.outline,
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      );
    }

    final starts = plan.startsAt == null
        ? 'Time unavailable'
        : '${DateFormat('d MMM, HH:mm').format(plan.startsAt!.toUtc().add(const Duration(hours: 1)))} WAT';
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                CollectionThumbnail(
                  name: plan.collectionName,
                  reference: 'plan:${plan.id}',
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        plan.collectionName,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(plan.chain),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: StatusBadge(plan.status),
            ),
            const SizedBox(height: 8),
            DetailRow('Mint time', starts),
            DetailRow('Phase', plan.stageName ?? 'Not selected'),
            DetailRow('Quantity', '${plan.quantity} NFTs'),
            DetailRow(
              'Mint price',
              plan.priceEth == null
                  ? 'Unverified'
                  : double.tryParse(plan.priceEth!) == 0
                  ? 'Free'
                  : '${plan.priceEth} ETH each',
            ),
            const SizedBox(height: 10),
            FilledButton(onPressed: details, child: const Text('Review mint')),
          ],
        ),
      ),
    );
  }

  Widget _taskCard(
    BuildContext context,
    MintlyNotifier notifier,
    MintTaskModel task,
  ) {
    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                CollectionThumbnail(
                  name: task.dropName,
                  reference: 'drop:${task.dropId}',
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        task.dropName,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Text(task.chain),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: StatusBadge(task.status),
            ),
            DetailRow('Mint time', task.timeWatLabel),
            DetailRow('Phase', task.stageName),
            DetailRow('Quantity', '${task.quantity} NFTs'),
            DetailRow(
              'Mint price',
              double.tryParse(task.unitPriceEth) == 0
                  ? 'Free'
                  : '${task.unitPriceEth} ETH each',
            ),
            DetailRow('Gas cap', '${task.feeCapEth} ETH'),
            if (task.failureReason != null)
              Text(
                task.failureReason!,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            OutlinedButton(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (detailContext) => Scaffold(
                    appBar: AppBar(title: const Text('Mint details')),
                    body: ListView(
                      padding: const EdgeInsets.all(20),
                      children: [
                        Text(
                          task.dropName,
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        DetailRow(
                          'Approved total cap',
                          '${task.totalCapEth} ETH',
                        ),
                        if (task.progress != null)
                          MintProgress(progress: task.progress!)
                        else
                          Text('Status: ${task.status}'),
                        if (task.failureReason != null)
                          Text(task.failureReason!),
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
                                if (detailContext.mounted) {
                                  Navigator.pop(detailContext);
                                }
                                if (context.mounted) {
                                  MintlyNotice.show(
                                    context,
                                    const SnackBar(
                                      content: Text('Task disarmed.'),
                                    ),
                                  );
                                }
                              } catch (error) {
                                if (context.mounted) {
                                  MintlyNotice.show(
                                    context,
                                    SnackBar(content: Text('$error')),
                                  );
                                }
                              }
                            },
                            child: const Text('Disarm task'),
                          ),
                        TextButton(
                          onPressed: () async {
                            try {
                              final inFlight = await notifier.removeTask(
                                task.id,
                              );
                              if (detailContext.mounted) {
                                Navigator.pop(detailContext);
                              }
                              if (context.mounted) {
                                MintlyNotice.show(
                                  context,
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
                                MintlyNotice.show(
                                  context,
                                  SnackBar(content: Text('$error')),
                                );
                              }
                            }
                          },
                          child: const Text('Remove'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              child: const Text('View mint details'),
            ),
          ],
        ),
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

  Widget _planDetails(
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
            Row(
              children: [
                CollectionThumbnail(
                  name: plan.collectionName,
                  reference: 'plan:${plan.id}',
                  size: 72,
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        plan.collectionName,
                        style: const TextStyle(
                          fontSize: 21,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Text(plan.chain),
                      const SizedBox(height: 8),
                      StatusBadge(plan.status),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 22),
            const Text(
              'Mint details',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
            ),
            DetailRow('Phase', plan.stageName ?? 'Not selected'),
            DetailRow('Mint time', starts),
            DetailRow('Quantity', '${plan.quantity} NFTs'),
            DetailRow('Receiving wallet', shortAddress(plan.walletAddress)),
            const Divider(height: 28),
            const Text(
              'Estimated cost',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
            ),
            DetailRow(
              'Mint price per NFT',
              plan.priceEth == null ? 'Unverified' : '${plan.priceEth} ETH',
            ),
            DetailRow(
              'Mint value',
              plan.mintValueEth == null
                  ? 'Unverified'
                  : '${plan.mintValueEth} ETH',
            ),
            DetailRow(
              'Network fee',
              plan.estimatedNetworkFeeEth == null
                  ? 'Unavailable'
                  : '${plan.estimatedNetworkFeeEth} ETH',
            ),
            DetailRow(
              'Estimated total',
              plan.estimatedTotalEth == null
                  ? 'Unavailable'
                  : '${plan.estimatedTotalEth} ETH',
              emphasis: true,
            ),
            const Text(
              'Final fees are checked before signing. Review spending limits before approval.',
              style: TextStyle(fontSize: 12),
            ),
            const SizedBox(height: 14),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: const Text('Collection & validation details'),
              children: [
                Text(plan.statusNote),
                SelectableText(plan.walletAddress),
                SelectableText(plan.contractAddress),
                SelectableText(plan.openSeaUrl),
                if (plan.estimatedTotalUsdt != null)
                  Text(
                    '≈ ${plan.estimatedTotalUsdt} USDT · display estimate only',
                  ),
              ],
            ),
            const SizedBox(height: 14),
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
                      MintlyNotice.show(
                        context,
                        SnackBar(content: Text('$error')),
                      );
                    }
                  }
                },
                child: const Text('Review & arm'),
              ),
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton(
                  onPressed: () async {
                    final selected = await Navigator.push<MintPlanModel>(
                      context,
                      MaterialPageRoute(
                        builder: (_) => MintStagesScreen(plan: plan),
                      ),
                    );
                    if (selected != null) await notifier.loadInitialData();
                  },
                  child: const Text('Choose mint phase'),
                ),
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
                        MintlyNotice.show(
                          context,
                          SnackBar(content: Text('$error')),
                        );
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
                        MintlyNotice.show(
                          context,
                          SnackBar(content: Text('$error')),
                        );
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
                          MintlyNotice.show(
                            context,
                            SnackBar(content: Text('$error')),
                          );
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
                        Navigator.pop(context);
                        MintlyNotice.show(
                          context,
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
                        MintlyNotice.show(
                          context,
                          SnackBar(content: Text('$error')),
                        );
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
