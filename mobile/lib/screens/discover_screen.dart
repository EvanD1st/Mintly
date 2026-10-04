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

class DiscoverScreen extends ConsumerStatefulWidget {
  const DiscoverScreen({super.key});
  @override
  ConsumerState<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends ConsumerState<DiscoverScreen> {
  final _removing = <String>{};

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
      onRefresh: notifier.loadInitialData,
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
          Text(
            'Find your next mint.',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 5),
          Text(
            'Welcome, ${api.username}. Review source details before using MetaMask.',
            style: TextStyle(color: muted),
          ),
          const SizedBox(height: 18),
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
                label: const Text('Manual review'),
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
    final stage = drop.stages.isNotEmpty ? drop.stages.first : null;
    final price = stage == null || stage.priceEthStr.isEmpty
        ? 'Price on source'
        : '${stage.priceEthStr} ETH';
    final schedule = stage == null
        ? 'Schedule on source'
        : '${_wat(stage.startTimeUtc)} WAT';
    return Card(
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        leading: const CircleAvatar(child: Icon(Icons.diamond_outlined)),
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
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Drop removed from Today.'),
                        ),
                      );
                    }
                  } catch (error) {
                    if (context.mounted) {
                      ScaffoldMessenger.of(
                        context,
                      ).showSnackBar(SnackBar(content: Text('$error')));
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
}
