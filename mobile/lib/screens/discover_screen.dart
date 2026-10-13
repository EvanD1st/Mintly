import '../widgets/collection_thumbnail.dart';
import '../widgets/mintly_notice.dart';
import '../theme/compatible_icons.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';
import 'drop_detail_screen.dart';
import 'import_screen.dart';
import 'source_screen.dart';
import '../widgets/delete_icon.dart';
import 'dart:async';
import 'saved_plan_screen.dart';

class DiscoverScreen extends ConsumerStatefulWidget {
  const DiscoverScreen({super.key});
  @override
  ConsumerState<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends ConsumerState<DiscoverScreen> {
  final _removing = <String>{};
  Timer? _timer;
  bool _refreshing = false;
  final _preparing = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _refresh());
    _timer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (mounted &&
          TickerMode.valuesOf(context).enabled &&
          ModalRoute.of(context)?.isCurrent == true) {
        _refresh();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh({String? walletId}) async {
    if (_refreshing || !mounted) return;
    _refreshing = true;
    try {
      await ref.read(mintlyProvider.notifier).refreshFeed(walletId: walletId);
    } catch (_) {
      /* Stored cards remain visible during an outage. */
    } finally {
      _refreshing = false;
    }
  }

  String _wat(DateTime time) => DateFormat(
    'd MMM, HH:mm',
  ).format(time.toUtc().add(const Duration(hours: 1)));

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);
    final api = ref.watch(apiServiceProvider);
    final muted = Theme.of(
      context,
    ).colorScheme.onSurface.withValues(alpha: .65);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(collectionArtworkProvider);
        await notifier.loadInitialData();
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        children: [
          Text(
            DateFormat('EEEE, d MMMM')
                .format(DateTime.now().toUtc().add(const Duration(hours: 1)))
                .toUpperCase(),
            style: TextStyle(color: muted, fontSize: 11, letterSpacing: 1.5),
          ),
          const SizedBox(height: 6),
          Text('Today', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 5),
          Text(
            'Welcome, ${api.username}. Review source details before using MetaMask.',
            style: TextStyle(color: muted),
          ),
          const SizedBox(height: 18),
          if (api.feedWallets.isNotEmpty)
            Card(
              child: ListTile(
                leading: const Icon(Icons.account_balance_wallet_outlined),
                title: const Text('Check eligibility for wallet'),
                subtitle: Text(
                  api.feedWallets.firstWhere(
                        (w) => w['id'] == api.selectedFeedWallet,
                        orElse: () => api.feedWallets.first,
                      )['label']
                      as String,
                ),
                trailing: const Icon(MintlyIcons.chevronRight),
                onTap: () async {
                  final chosen = await showModalBottomSheet<String>(
                    context: context,
                    builder: (context) => SafeArea(
                      child: ListView(
                        shrinkWrap: true,
                        children: [
                          for (final wallet in api.feedWallets)
                            ListTile(
                              title: Text(wallet['label'] as String),
                              subtitle: Text(wallet['address'] as String),
                              trailing: wallet['id'] == api.selectedFeedWallet
                                  ? const Icon(Icons.check)
                                  : null,
                              onTap: () => Navigator.pop(
                                context,
                                wallet['id'] as String,
                              ),
                            ),
                        ],
                      ),
                    ),
                  );
                  if (chosen != null && mounted) {
                    await _refresh(walletId: chosen);
                  }
                },
              ),
            ),
          const SizedBox(height: 12),
          if (api.isAdmin)
            Card(
              child: ListTile(
                leading: const Icon(MintlyIcons.public),
                title: const Text('@lakzonevn drops'),
                subtitle: Text(state.sourceStatusText),
                trailing: const Icon(MintlyIcons.chevronRight),
                onTap: () => Navigator.of(
                  context,
                ).push(MaterialPageRoute(builder: (_) => const SourceScreen())),
              ),
            ),
          if (api.isAdmin) const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: Text(
                  'Current drops',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              TextButton.icon(
                onPressed: () => Navigator.of(
                  context,
                ).push(MaterialPageRoute(builder: (_) => const ImportScreen())),
                icon: const Icon(Icons.add),
                label: const Text('Prepare mint'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              RawChip(
                deleteIcon: const Icon(Icons.close),
                label: const Text('All'),
                selected: state.filter == 'all',
                onSelected: (_) => notifier.setFilter('all'),
              ),
              RawChip(
                deleteIcon: const Icon(Icons.close),
                label: const Text('Unverified'),
                selected: state.filter == 'unknown',
                onSelected: (_) => notifier.setFilter('unknown'),
              ),
              RawChip(
                deleteIcon: const Icon(Icons.close),
                label: const Text('Not eligible'),
                selected: state.filter == 'manual',
                onSelected: (_) => notifier.setFilter('manual'),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (state.isLoading)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(32),
                child: CircularProgressIndicator(),
              ),
            ),
          if (state.error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  'Some data could not refresh. Pull down to retry.\n${state.error}',
                ),
              ),
            ),
          if (!state.isLoading && state.drops.isEmpty && state.error == null)
            const Card(
              child: Padding(
                padding: EdgeInsets.all(18),
                child: Text(
                  'No current drops. Pull down to refresh or prepare a mint from a collection link.',
                ),
              ),
            )
          else
            for (final drop in state.drops) _dropCard(context, notifier, drop),
          const SizedBox(height: 16),
          Text(
            state.checkedWalletLabel,
            style: TextStyle(color: muted, fontSize: 12),
          ),
          Text(
            state.lastCheckedText,
            style: TextStyle(color: muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _dropCard(
    BuildContext context,
    MintlyNotifier notifier,
    DropModel drop,
  ) {
    if (drop.walletCheck != null) return _verifiedCard(context, drop);
    final stage = drop.stages.isNotEmpty ? drop.stages.first : null;
    final price = stage == null || stage.priceEthStr.isEmpty
        ? 'Price on source'
        : '${stage.priceEthStr} ETH';
    final schedule = stage == null
        ? 'Schedule on source'
        : '${_wat(stage.startTimeUtc)} WAT';
    return Card(
      child: ListTile(
        leading: CollectionThumbnail(
          name: drop.name,
          reference: 'drop:${drop.id}',
          size: 52,
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        title: Text(drop.name),
        subtitle: Text(
          '${drop.chain} · ${drop.siteLabel}\n$schedule · $price\n${drop.statusLabel}',
        ),
        isThreeLine: true,
        trailing: IconButton(
          tooltip: 'Remove drop',
          onPressed: _removing.contains(drop.id)
              ? null
              : () async {
                  setState(() => _removing.add(drop.id));
                  try {
                    await notifier.removeDrop(drop.id);
                    if (context.mounted) {
                      MintlyNotice.show(
                        context,
                        const SnackBar(
                          content: Text('Drop removed from Today.'),
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
                  } finally {
                    if (mounted) setState(() => _removing.remove(drop.id));
                  }
                },
          icon: const DeleteDropIcon(),
        ),
        onTap: () {
          notifier.selectDrop(drop);
          Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => DropDetailScreen(drop: drop)),
          );
        },
      ),
    );
  }

  Widget _verifiedCard(BuildContext context, DropModel drop) {
    final check = drop.walletCheck!;
    final stage = check['recommended_stage'] as Map<String, dynamic>?;
    final checked = DateTime.tryParse(check['checked_at'] as String? ?? '');
    final fresh =
        checked != null &&
        DateTime.now().toUtc().difference(checked.toUtc()) <
            const Duration(seconds: 60);
    final enabled =
        fresh &&
        check['setup_enabled'] == true &&
        !_preparing.contains(drop.id);
    final status = fresh
        ? switch (check['status']) {
            'eligible' => 'Eligible',
            'not_eligible' => 'Not eligible',
            _ => 'Not verified',
          }
        : 'Not verified';
    final price = stage?['price_wei'] == null
        ? null
        : double.tryParse('${stage!['price_wei']}');
    final starts = DateTime.tryParse(stage?['starts_at'] as String? ?? '');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CollectionThumbnail(
                  name: drop.name,
                  reference: 'drop:${drop.id}',
                  size: 64,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        drop.name,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text('${drop.chain} · ${drop.nativeCurrency}'),
                      Text(status),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (stage != null && fresh)
              Text(
                '${stage['name']} · ${price == 0 ? 'Free' : '${(price! / 1e18).toStringAsFixed(6)} ${drop.nativeCurrency}'}',
              ),
            if (starts != null && fresh) Text('Opens ${_wat(starts)} WAT'),
            if (!fresh || stage == null)
              Text(
                'Source price: ${drop.sourcePriceText ?? 'Not provided'}\nSource time: ${drop.sourceTimeText ?? 'Not provided'}',
              ),
            if (checked != null)
              Text(
                'Checked ${_wat(checked)} WAT',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            if (check['note'] != null) Text('${check['note']}'),
            const SizedBox(height: 10),
            FilledButton(
              onPressed: enabled
                  ? () async {
                      setState(() => _preparing.add(drop.id));
                      final api = ref.read(apiServiceProvider);
                      final revision = api.sessionRevision;
                      try {
                        final plan = await api.prepareFeedPlan(drop);
                        if (context.mounted &&
                            revision == api.sessionRevision) {
                          await Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => SavedPlanScreen(plan: plan),
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
                      } finally {
                        if (mounted) setState(() => _preparing.remove(drop.id));
                      }
                    }
                  : null,
              child: Text(
                _preparing.contains(drop.id)
                    ? 'Checking stage…'
                    : 'Set up automatic mint',
              ),
            ),
            TextButton(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => DropDetailScreen(drop: drop)),
              ),
              child: const Text('View collection and all stages'),
            ),
          ],
        ),
      ),
    );
  }
}
