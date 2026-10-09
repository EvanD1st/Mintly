import '../widgets/mintly_notice.dart';
import '../theme/compatible_icons.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../services/external_url.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';
import 'automatic_review_screen.dart';

class DropDetailScreen extends ConsumerWidget {
  final DropModel drop;
  const DropDetailScreen({super.key, required this.drop});

  String _wat(DateTime time) => DateFormat('d MMM yyyy, HH:mm').format(
    time.toUtc().add(const Duration(hours: 1)));

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);
    final muted = Theme.of(context).colorScheme.onSurface.withValues(alpha: .65);
    final uri = Uri.tryParse(drop.mintPageUrl);
    final trustedOpenSea = uri != null && uri.scheme == 'https' &&
      uri.host == 'opensea.io' && uri.path.startsWith('/collection/');
    return Scaffold(
      appBar: AppBar(title: const Text('Drop details')),
      body: ListView(padding: const EdgeInsets.all(20), children: [
        Text(drop.name, style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 6),
        Text('${drop.chain} · ${drop.siteLabel}', style: TextStyle(color: muted)),
        const SizedBox(height: 16),
        Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(drop.statusLabel, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(drop.manualNotice ?? 'Check the official mint page and your MetaMask confirmation.'),
            const SizedBox(height: 8),
            Text('Contract: ${drop.contractAddress ?? 'Not verified'}',
              style: TextStyle(color: muted, fontSize: 12)),
          ],
        ))),
        const SizedBox(height: 14),
        Text('Mint stages', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        if (drop.stages.isEmpty)
          const Card(child: Padding(padding: EdgeInsets.all(16),
            child: Text('Stage timing and price are not available from this source.')))
        else for (final stage in drop.stages) Card(child: ListTile(
          title: Text(stage.stageName),
          subtitle: Text('${_wat(stage.startTimeUtc)} WAT · Eligibility ${stage.eligibilityStatus.replaceAll('_', ' ')}'),
          trailing: Text(stage.priceEthStr.isEmpty ? 'See source' : '${stage.priceEthStr} ETH'),
        )),
        const SizedBox(height: 14),
        Card(child: ListTile(
          leading: const Icon(Icons.account_balance_wallet_outlined),
          title: const Text('Linked wallet'), subtitle: Text(state.checkedWalletLabel),
        )),
        const SizedBox(height: 12),
        const Text('A feed listing does not verify your wallet’s eligibility or authorize spending. '
          'Adding an address gives no signing access. Automatic signing is a separate, explicit custody setup; use a dedicated minting wallet. '
          'Never share a recovery phrase with a mint site or support contact.'),
        const SizedBox(height: 20),
        if (drop.stages.isNotEmpty) ...[
          FilledButton.icon(onPressed: () => Navigator.push(context, MaterialPageRoute(
            builder: (_) => AutomaticReviewScreen(drop: drop))),
            icon: const Icon(Icons.timer_outlined), label: const Text('Set up automatic mint')),
          const SizedBox(height: 12),
        ],
        if (trustedOpenSea)
          FilledButton.icon(onPressed: () async {
            try {
              if (!await openExternalUrl(context, uri)) {
                throw Exception('Could not open OpenSea.');
              }
            } catch (error) {
              if (context.mounted) {
                MintlyNotice.show(context, SnackBar(content: Text('$error')));
              }
            }
          }, icon: const Icon(MintlyIcons.openInNew), label: const Text('View on OpenSea'))
        else ...[
          const Text('Unverified external link. Confirm its address independently before visiting:'),
          const SizedBox(height: 8),
          SelectableText(drop.mintPageUrl),
        ],
      ]),
    );
  }
}
