import 'package:flutter/material.dart';
import '../services/wat_time.dart';
import '../theme/compatible_icons.dart';

class WalletReadinessPanel extends StatelessWidget {
  final String walletId;
  final Future<Map<String, dynamic>> readiness;
  const WalletReadinessPanel({super.key, required this.walletId, required this.readiness});

  String _amount(dynamic raw) {
    final value = BigInt.tryParse('$raw');
    if (value == null) return 'Unavailable';
    final scale = BigInt.from(10).pow(18);
    if (value > BigInt.zero && value < BigInt.from(10).pow(12)) return '< 0.000001 ETH';
    final fraction = (value % scale).toString().padLeft(18, '0').substring(0, 6).replaceFirst(RegExp(r'0+$'), '');
    return '${value ~/ scale}${fraction.isEmpty ? '' : '.$fraction'} ETH';
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
    future: readiness,
    builder: (context, snapshot) => ExpansionTile(
      key: ValueKey('readiness-$walletId'),
      title: const Text('Network readiness', style: TextStyle(fontSize: 14)),
      trailing: const Icon(MintlyIcons.chevronRight, size: 20),
      children: [_content(context, snapshot)],
    ),
  );

  Widget _content(BuildContext context, AsyncSnapshot<Map<String, dynamic>> snapshot) {
        if (snapshot.hasError || snapshot.data?['unavailable'] == true) return const Padding(padding: EdgeInsets.all(16), child: Text('Readiness unavailable. Refresh wallets to retry.'));
        if (!snapshot.hasData) return const Padding(padding: EdgeInsets.all(16), child: Text('Checking networks…'));
        final wallets = snapshot.data!['wallets'] as List? ?? [];
        final own = wallets.where((wallet) => wallet['wallet_id'] == walletId);
        final networks = own.isEmpty ? [] : own.first['networks'] as List? ?? [];
        return Padding(padding: const EdgeInsets.fromLTRB(16, 0, 16, 16), child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (snapshot.data!['automation_paused'] == true) const Text('Automation paused in Settings.'),
            for (final network in networks) Container(
              margin: const EdgeInsets.only(top: 10), padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(12)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${network['network']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 6),
                Text('ETH balance: ${_amount(network['balance_wei'])}'),
                Text('${network['gas_status']}'),
                Text('Approval: ${network['approval_status']}'),
                Text('Available spending budget: ${_amount(network['approved_remaining_wei'])}'),
                if (DateTime.tryParse('${network['approval_expires_at']}') case final expires?)
                  Text('Ends ${WatTime.label(expires)}'),
                if (network['advance_check'] != null) Text('${network['advance_check']}'),
              ]),
            ),
          ],
        ));
  }
}
