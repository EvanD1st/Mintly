import '../models/network_metadata.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'refresh_glyph.dart';
import 'screen_components.dart';

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
  String get symbol => nativeSymbol(chainId);
  String get name =>
      const {
        1: 'Ethereum',
        8453: 'Base',
        4663: 'Robinhood',
        999: 'HyperEVM',
        33139: 'ApeChain',
        57073: 'Ink',
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
  return networks.values.toList()..sort((a, b) {
    const order = {1: 0, 8453: 1, 4663: 2};
    final priority = (order[a.chainId] ?? 3).compareTo(order[b.chainId] ?? 3);
    return priority != 0 ? priority : a.chainId.compareTo(b.chainId);
  });
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
  final _networkMenuKey = GlobalKey<PopupMenuButtonState<int>>();
  @override
  Widget build(BuildContext context) => AppPanel(
    padding: const EdgeInsets.all(14),
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
        final total = selected == null
            ? BigInt.zero
            : selected.available + selected.spent + selected.reserved;
        final fraction = total == BigInt.zero
            ? 0.0
            : (selected!.available * BigInt.from(10000) ~/ total).toDouble() /
                  10000;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    'Spending budget',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                  ),
                ),
                SizedBox(
                  width: 28,
                  height: 28,
                  child: IconButton(
                    tooltip: 'Refresh budget',
                    constraints: const BoxConstraints.tightFor(
                      width: 28,
                      height: 28,
                    ),
                    padding: EdgeInsets.zero,
                    onPressed: () => ref.invalidate(networkBudgetsProvider),
                    icon: const RefreshGlyph(size: 17),
                  ),
                ),
              ],
            ),
            if (snapshot.connectionState != ConnectionState.done &&
                selected == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: LinearProgressIndicator(),
              )
            else if (snapshot.hasError)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('Budget unavailable. Tap refresh to retry.'),
              )
            else if (selected == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('No active spending allowance'),
              )
            else ...[
              LayoutBuilder(
                builder: (context, constraints) {
                  final tight =
                      constraints.maxWidth < 270 ||
                      MediaQuery.textScalerOf(context).scale(1) > 1.2;
                  final amount = Row(
                    children: [
                      Expanded(
                        child: InkWell(
                          onTap: () =>
                              _networkMenuKey.currentState?.showButtonMenu(),
                          child: NativeAmountText(
                            selected.available,
                            symbol: selected.symbol,
                            prefix: true,
                            fontSize: 23,
                            bold: true,
                          ),
                        ),
                      ),
                      PopupMenuButton<int>(
                        key: _networkMenuKey,
                        tooltip: 'Available budget by network',
                        padding: EdgeInsets.zero,
                        position: PopupMenuPosition.under,
                        color: const Color(0xFF15251B),
                        surfaceTintColor: Colors.transparent,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14),
                          side: const BorderSide(color: Color(0xFF3E5946)),
                        ),
                        constraints: const BoxConstraints(
                          minWidth: 270,
                          maxWidth: 320,
                        ),
                        icon: Container(
                          width: 30,
                          height: 30,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(9),
                            border: Border.all(color: const Color(0xFF3E5946)),
                          ),
                          child: const RotatedBox(
                            quarterTurns: 1,
                            child: AppGlyph('arrow', size: 17),
                          ),
                        ),
                        onSelected: (value) => setState(() => _chain = value),
                        itemBuilder: (_) => [
                          const PopupMenuItem<int>(
                            enabled: false,
                            height: 32,
                            child: Text(
                              'Available budget by network',
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: Color(0xFFECF3EA),
                              ),
                            ),
                          ),
                          ...entries.map(
                            (e) => PopupMenuItem<int>(
                              value: e.chainId,
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                              ),
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 8,
                                ),
                                decoration: BoxDecoration(
                                  color: e.chainId == selected.chainId
                                      ? Theme.of(context).colorScheme.primary
                                            .withValues(alpha: .1)
                                      : Colors.transparent,
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Row(
                                  children: [
                                    CircleAvatar(
                                      radius: 12,
                                      backgroundColor: e.chainId == 8453
                                          ? const Color(0xFF355D80)
                                          : const Color(0xFF345C40),
                                      child: Text(
                                        e.name.substring(0, 1),
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: Colors.white,
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      flex: 3,
                                      child: Text(
                                        e.name,
                                        style: const TextStyle(fontSize: 12),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      flex: 3,
                                      child: NativeAmountText(
                                        e.available,
                                        symbol: e.symbol,
                                        prefix: true,
                                        fontSize: 12,
                                      ),
                                    ),
                                    if (e.chainId == selected.chainId) ...[
                                      const SizedBox(width: 6),
                                      const AppGlyph('check', size: 14),
                                    ],
                                  ],
                                ),
                              ),
                            ),
                          ),
                          const PopupMenuItem<int>(
                            enabled: false,
                            height: 30,
                            child: Text(
                              'Each network has its own allowance.',
                              style: TextStyle(fontSize: 10),
                            ),
                          ),
                        ],
                      ),
                    ],
                  );
                  if (tight) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [amount, NetworkBadge(selected.name)],
                    );
                  }
                  return Row(
                    children: [
                      Expanded(flex: 3, child: amount),
                      const SizedBox(width: 12),
                      Expanded(
                        flex: 2,
                        child: Align(
                          alignment: Alignment.centerRight,
                          child: NetworkBadge(selected.name),
                        ),
                      ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 3),
              const Text(
                'Available for mint + gas',
                style: TextStyle(fontSize: 11),
              ),
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: fraction,
                  minHeight: 5,
                  backgroundColor: Theme.of(
                    context,
                  ).colorScheme.primary.withValues(alpha: .15),
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Spent', style: TextStyle(fontSize: 10)),
                        NativeAmountText(
                          selected.spent,
                          symbol: selected.symbol,
                          fontSize: 12,
                          bold: true,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 10, child: VerticalDivider()),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Reserved', style: TextStyle(fontSize: 10)),
                        NativeAmountText(
                          selected.reserved,
                          symbol: selected.symbol,
                          fontSize: 12,
                          bold: true,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 7),
            const Text(
              'Signing allowance · individual mint and copy limits apply.',
              style: TextStyle(fontSize: 10, height: 1.2),
            ),
          ],
        );
      },
    ),
  );
}

String compactNative(dynamic raw, {int decimals = 8}) {
  final full = formatNative(raw);
  final parts = full.split('.');
  if (parts.length == 1 || parts[1].length <= decimals) return full;
  final fraction = parts[1]
      .substring(0, decimals)
      .replaceFirst(RegExp(r'0+$'), '');
  if (parts[0] == '0' && fraction.isEmpty) return '<0.${'0' * (decimals - 1)}1';
  return '${parts[0]}${fraction.isEmpty ? '' : '.$fraction'}…';
}

/// Compact display only. Approval and signing amounts continue to use exact wei.
class NativeAmountText extends StatelessWidget {
  final dynamic wei;
  final String symbol;
  final bool prefix, bold;
  final double fontSize;
  const NativeAmountText(
    this.wei, {
    super.key,
    this.symbol = 'ETH',
    this.prefix = false,
    this.bold = false,
    this.fontSize = 14,
  });
  @override
  Widget build(BuildContext context) => Tooltip(
    message: '${formatNative(wei)} $symbol',
    child: FittedBox(
      fit: BoxFit.scaleDown,
      alignment: Alignment.centerLeft,
      child: Text(
        prefix
            ? '$symbol ${compactNative(wei)}'
            : '${compactNative(wei)} $symbol',
        maxLines: 1,
        style: TextStyle(
          fontSize: fontSize,
          fontWeight: bold ? FontWeight.w700 : FontWeight.w500,
        ),
      ),
    ),
  );
}
