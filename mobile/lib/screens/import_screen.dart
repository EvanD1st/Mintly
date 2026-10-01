import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';

class ImportScreen extends ConsumerStatefulWidget {
  const ImportScreen({super.key});

  @override
  ConsumerState<ImportScreen> createState() => _ImportScreenState();
}

class _ImportScreenState extends ConsumerState<ImportScreen> {
  final TextEditingController _textController = TextEditingController();
  bool _isImporting = false;
  int _quantity = 1;

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final notifier = ref.read(mintlyProvider.notifier);
    final api = ref.watch(apiServiceProvider);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        leadingWidth: 100,
        leading: TextButton.icon(
          onPressed: () => Navigator.of(context).pop(),
          icon: Icon(Icons.arrow_back, size: 16, color: muted),
          label: Text('All drops', style: TextStyle(color: muted, fontSize: 13)),
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        children: [
          Text(
            'PREPARE AN OPENSEA MINT',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
              color: muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Check a mint.',
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
            api.isAdmin ? 'Paste a direct OpenSea collection link or an admin list.' :
              'Paste a direct OpenSea collection link for your linked MetaMask wallet.',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 20),

          Text(
            'OpenSea collection link${api.isAdmin ? ' or list text' : ''}',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ink),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _textController,
            maxLines: 7,
            style: TextStyle(fontSize: 14, color: ink),
            decoration: const InputDecoration(
              hintText: 'https://opensea.io/collection/example',
            ),
          ),
          const SizedBox(height: 14),

          Row(children: [
            const Expanded(child: Text('NFT quantity')),
            TextButton(onPressed: _isImporting || _quantity <= 1 ? null : () => setState(() => _quantity--), child: const Text('−')),
            Text('$_quantity'),
            TextButton(onPressed: _isImporting || _quantity >= 100 ? null : () => setState(() => _quantity++), child: const Text('+')),
          ]),
          Text('OpenSea checks this quantity against your wallet’s stage limit and remaining supply.', style: TextStyle(color: muted, fontSize: 11)),

          Text(
            'Supports native-ETH SeaDrop V1 drops on Ethereum, Base, Robinhood Chain, Arbitrum One and Optimism. Mintly checks stage timing and wallet readiness. Gas is estimated. Approve in MetaMask on the drop’s network; importing does not sign a mint.',
            style: TextStyle(fontSize: 11, color: muted, height: 1.4),
          ),
          const SizedBox(height: 24),

          ElevatedButton(
            onPressed: _isImporting ? null : () async {
              final text = _textController.text.trim();
              if (text.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Paste an OpenSea link or list first.'),
                    duration: Duration(seconds: 2),
                  ),
                );
                return;
              }

              setState(() => _isImporting = true);
              try {
                final uri = Uri.tryParse(text);
                final isOpenSeaLink = uri != null && uri.scheme == 'https' && uri.host == 'opensea.io' &&
                  uri.pathSegments.length >= 2 && uri.pathSegments.first == 'collection';
                if (isOpenSeaLink) {
                  await notifier.importOpenSeaMint(text, quantity: _quantity);
                } else if (api.isAdmin) {
                  await notifier.importList(text);
                } else {
                  throw StateError('Members can import direct OpenSea collection links only.');
                }
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(isOpenSeaLink ? 'Mint check saved. See Mint plans.' : 'List imported.'),
                  ));
                  Navigator.of(context).pop();
                }
              } catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
                }
              } finally {
                if (mounted) setState(() => _isImporting = false);
              }
            },
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(_isImporting ? 'Checking OpenSea…' : 'Import and check'),
                const SizedBox(width: 8),
                const Icon(Icons.arrow_forward, size: 16),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
