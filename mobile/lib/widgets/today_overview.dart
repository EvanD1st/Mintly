import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/drop_model.dart';
import '../models/network_metadata.dart';
import '../models/today_automation_status.dart';

class TodayAutomationCard extends StatelessWidget {
  const TodayAutomationCard({
    super.key,
    required this.status,
    required this.hasWallet,
    required this.onManage,
  });
  final AsyncValue<TodayAutomationStatus> status;
  final bool hasWallet;
  final VoidCallback onManage;

  bool _active(Map row) {
    final expiry = DateTime.tryParse('${row['expires_at']}');
    return row['status'] == 'active' &&
        expiry != null &&
        expiry.isAfter(DateTime.now().toUtc());
  }

  bool _waiting(Map row) {
    final note = '${row['note'] ?? ''}'.toLowerCase();
    return _active(row) &&
        (note.contains('below your chosen gas cap') ||
            note.contains('pending mint reservations'));
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final rows = status.valueOrNull?.approvals;
    final paused = status.valueOrNull?.paused == true;
    final networks = <int, Map<String, dynamic>>{};
    for (final row in rows ?? <Map<String, dynamic>>[]) {
      final chain = int.tryParse('${(row['snapshot'] as Map?)?['chain_id']}');
      if (chain != null) networks.putIfAbsent(chain, () => row);
    }
    final active = networks.values.where(_active).length;
    final waiting = networks.values.where(_waiting).length;
    final pending = networks.values.any(
      (row) => row['status'] == 'registering' || row['status'] == 'revoking',
    );
    final label = !hasWallet
        ? 'Choose a wallet first'
        : rows == null
        ? (status.hasError ? 'Status unavailable' : 'Checking status')
        : paused
        ? 'Paused'
        : active > 0
        ? 'On · $active ${active == 1 ? 'network' : 'networks'}'
        : pending
        ? 'Confirmation pending'
        : 'Off';
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            colors: [colors.primary.withValues(alpha: .10), colors.surface],
          ),
        ),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    'Auto-Arming',
                    style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                  ),
                ),
                TextButton(onPressed: onManage, child: const Text('Manage')),
              ],
            ),
            Text(
              '${status.hasError && rows != null ? 'Last known: ' : ''}$label',
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: active > 0 && !paused
                    ? colors.primary
                    : colors.onSurface,
              ),
            ),
            const SizedBox(height: 8),
            if (networks.isNotEmpty)
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final entry in networks.entries)
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 9,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: colors.surface.withValues(alpha: .7),
                        border: Border.all(
                          color: colors.outline.withValues(alpha: .35),
                        ),
                        borderRadius: BorderRadius.circular(9),
                      ),
                      child: Text(
                        '${networkNames[entry.key] ?? 'Chain ${entry.key}'}${_waiting(entry.value)
                            ? ' · Waiting'
                            : _active(entry.value)
                            ? (paused ? ' · Paused' : '')
                            : entry.value['status'] == 'registering'
                            ? ' · Pending'
                            : ' · Off'}',
                        style: const TextStyle(fontSize: 11),
                      ),
                    ),
                ],
              ),
            if (paused)
              const Padding(
                padding: EdgeInsets.only(top: 10),
                child: Text(
                  'All automation is paused. Resume it from Wallet when you are ready.',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            if (waiting > 0 && !paused)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(
                  '$waiting ${waiting == 1 ? 'network needs' : 'networks need'} attention. Check saved gas and signing allowance in Manage.',
                  style: TextStyle(color: colors.onSurface, fontSize: 12),
                ),
              ),
            if (status.hasError)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text(
                  'Status update delayed. Pull down to retry.',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            const SizedBox(height: 10),
            Text(
              'Eligible free mints only. Your saved gas limits apply.',
              style: TextStyle(
                fontSize: 12,
                color: colors.onSurface.withValues(alpha: .65),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class TodayMintSummary extends StatelessWidget {
  const TodayMintSummary({super.key, required this.drops});
  final List<DropModel> drops;
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final minted = drops
        .where(
          (drop) => [
            'confirmed',
            'already_minted',
          ].contains(drop.automaticMint?['status']),
        )
        .length;
    final armed = drops
        .where(
          (drop) =>
              drop.automaticMint != null &&
              ![
                'confirmed',
                'already_minted',
              ].contains(drop.automaticMint?['status']),
        )
        .length;
    final ready = drops
        .where(
          (drop) =>
              drop.automaticMint == null &&
              drop.walletCheck?['setup_enabled'] == true,
        )
        .length;
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final label in ['$ready ready', '$armed armed', '$minted minted'])
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: colors.outline.withValues(alpha: .4)),
            ),
            child: Text(
              label,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
            ),
          ),
      ],
    );
  }
}
