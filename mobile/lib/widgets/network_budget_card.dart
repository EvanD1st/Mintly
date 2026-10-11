import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../theme/compatible_icons.dart';

String formatNative(dynamic raw) {
  final value = BigInt.tryParse('$raw') ?? BigInt.zero;
  final scale = BigInt.from(10).pow(18);
  final fraction = (value % scale)
      .toString()
      .padLeft(18, '0')
      .replaceFirst(RegExp(r'0+$'), '');
  return '${value ~/ scale}${fraction.isEmpty ? '' : '.$fraction'}';
}

class NetworkAllowance {
  final int chainId;
  BigInt available = BigInt.zero, spent = BigInt.zero, reserved = BigInt.zero;
  NetworkAllowance(this.chainId);
  String get name =>
      const {
        1: 'Ethereum',
        8453: 'Base',
        4663: 'Robinhood',
        42161: 'Arbitrum',
        10: 'Optimism',
        11155111: 'Sepolia',
        31337: 'Local test',
      }[chainId] ??
      'Chain $chainId';
}

/// Aggregate existing grants once each. These are approvals, not wallet balances
/// or a new shared budget; narrower task/copy limits continue to apply.
List<NetworkAllowance> networkAllowances(
  List<Map<String, dynamic>> policies,
  DateTime now,
) {
  final networks = <int, NetworkAllowance>{};
  final seen = <String>{};
  for (final policy in policies) {
    final id = policy['id']?.toString();
    final chain = policy['chain_id'];
    final expiry = DateTime.tryParse('${policy['expires_at']}');
    if (id == null ||
        !seen.add(id) ||
        chain is! int ||
        policy['status'] != 'enabled' ||
        expiry == null ||
        !expiry.isAfter(now)) {
      continue;
    }
    final entry = networks.putIfAbsent(chain, () => NetworkAllowance(chain));
    BigInt amount(String key) {
      final value = BigInt.tryParse('${policy[key]}') ?? BigInt.zero;
      return value < BigInt.zero ? BigInt.zero : value;
    }

    entry.available += amount('remaining_wei');
    entry.spent += amount('spent_wei');
    entry.reserved += amount('reserved_wei');
  }
  return networks.values.toList()
    ..sort((a, b) => a.chainId.compareTo(b.chainId));
}

final networkBudgetsProvider = FutureProvider<List<Map<String, dynamic>>>((
  ref,
) async {
  final api = ref.watch(apiServiceProvider);
  if (!api.isLiveBackendConnected) return [];
  return api.fetchAutomaticPolicies();
});

class NetworkBudgetCard extends ConsumerStatefulWidget {
  const NetworkBudgetCard({super.key});
  @override
  ConsumerState<NetworkBudgetCard> createState() => _NetworkBudgetCardState();
}

class _NetworkBudgetCardState extends ConsumerState<NetworkBudgetCard> {
  int? _chain;
  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 18),
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: FutureBuilder<List<Map<String, dynamic>>>(
        future: ref.watch(networkBudgetsProvider.future),
        builder: (context, snapshot) {
          final entries = networkAllowances(
            snapshot.data ?? [],
            DateTime.now().toUtc(),
          );
          final selected =
              entries.where((e) => e.chainId == _chain).firstOrNull ??
              entries.firstOrNull;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'Spending budget',
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Refresh budget',
                    onPressed: () => ref.invalidate(networkBudgetsProvider),
                    icon: const Icon(Icons.refresh, size: 19),
                  ),
                ],
              ),
              if (snapshot.connectionState != ConnectionState.done)
                const LinearProgressIndicator()
              else if (snapshot.hasError)
                const Text('Budget unavailable. Tap refresh to retry.')
              else if (selected == null)
                const Text('No active spending allowance')
              else ...[
                PopupMenuButton<int>(
                  tooltip: 'Available budget by network',
                  onSelected: (value) => setState(() => _chain = value),
                  itemBuilder: (_) => entries
                      .map(
                        (e) => PopupMenuItem(
                          value: e.chainId,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(e.name),
                              Text(
                                'ETH ${formatNative(e.available)}',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                      )
                      .toList(),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            'ETH ${formatNative(selected.available)}',
                            style: Theme.of(context).textTheme.headlineSmall
                                ?.copyWith(fontWeight: FontWeight.w700),
                          ),
                        ),
                        const RotatedBox(
                          quarterTurns: 1,
                          child: Icon(MintlyIcons.chevronRight),
                        ),
                      ],
                    ),
                  ),
                ),
                Text(
                  selected.name,
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.primary,
                  ),
                ),
                const Divider(height: 24),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Spent'),
                          Text(
                            '${formatNative(selected.spent)} ETH',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Reserved'),
                          Text(
                            '${formatNative(selected.reserved)} ETH',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ],
              const SizedBox(height: 8),
              Text(
                'Signing allowance for mint + gas.\nIndividual copy and mint limits still apply.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          );
        },
      ),
    ),
  );
}
