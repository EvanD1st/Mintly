import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../widgets/mintly_notice.dart';
import 'custody_import_screen.dart';

class WalletSetupScreen extends ConsumerStatefulWidget {
  final int? initialChain;
  final String? walletId, address;
  const WalletSetupScreen({super.key, this.initialChain, this.walletId, this.address});
  @override
  ConsumerState<WalletSetupScreen> createState() => _WalletSetupState();
}

class _WalletSetupState extends ConsumerState<WalletSetupScreen> {
  final _address = TextEditingController(), _name = TextEditingController();
  bool _busy = false;
  @override
  void dispose() { _address.dispose(); _name.dispose(); super.dispose(); }

  Future<void> _addAddress() async {
    if (!RegExp(r'^0x[0-9a-fA-F]{40}$').hasMatch(_address.text.trim())) {
      MintlyNotice.show(context, const SnackBar(content: Text('Enter a valid wallet address.')));
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(apiServiceProvider).addWatchWallet(_address.text.trim(), _name.text.trim().isEmpty ? 'Wallet' : _name.text.trim());
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) MintlyNotice.show(context, SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _automatic() async {
    final result = await Navigator.push<bool>(context, MaterialPageRoute(
      builder: (_) => CustodyImportScreen(initialChain: widget.initialChain,walletId:widget.walletId,address:widget.address)));
    if (mounted && result == true) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Set up wallet')),
    body: ListView(padding: const EdgeInsets.all(20), children: [
      Text('Choose how to use your wallet', style: Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height: 16),
      Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('Add an address', style: TextStyle(fontWeight: FontWeight.w700)),
          const Text('View mint readiness and save plans. This does not prove ownership or give Mintly signing access. No recovery phrase is needed.'),
          const SizedBox(height: 12),
          TextField(controller: _name, decoration: const InputDecoration(labelText: 'Wallet name')),
          TextField(controller: _address, decoration: const InputDecoration(labelText: 'Wallet address')),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: _busy ? null : _addAddress, child: const Text('Add address only')),
        ],
      ))),
      const SizedBox(height: 16),
      Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('Enable automatic signing', style: TextStyle(fontWeight: FontWeight.w700)),
          const Text('Mintly derives the selected account on this device and sends its private key over HTTPS to the custody service, which stores it encrypted. The recovery phrase is not sent. The server holds signing access; Mintly’s software enforces your approved limits.'),
          const SizedBox(height: 10),
          const Text('Use a dedicated minting wallet. Choose the networks and finite spending limits you want to approve.'),
          const SizedBox(height: 12),
          FilledButton(onPressed: _busy ? null : _automatic, child: const Text('Continue to automatic signing')),
        ],
      ))),
    ]),
  );
}
