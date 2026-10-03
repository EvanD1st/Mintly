import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';

class CustodyImportScreen extends ConsumerStatefulWidget {
  final String walletId;
  final String address;
  const CustodyImportScreen({super.key, required this.walletId, required this.address});
  @override
  ConsumerState<CustodyImportScreen> createState() => _CustodyImportScreenState();
}

class _CustodyImportScreenState extends ConsumerState<CustodyImportScreen> with WidgetsBindingObserver {
  final _form = GlobalKey<FormState>();
  final _key = TextEditingController();
  final _password = TextEditingController();
  final _contract = TextEditingController();
  final _budget = TextEditingController();
  final _maximum = TextEditingController();
  late final Future<Map<String, dynamic>> _config;
  late final String _requestId;
  late DateTime _expiry;
  int _days = 1;
  bool _consent = false, _busy = false, _attempted = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _config = ref.read(apiServiceProvider).custodyImportConfig();
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final hex = bytes.map((v) => v.toRadixString(16).padLeft(2, '0')).join();
    _requestId = '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
    _expiry = DateTime.now().toUtc().add(const Duration(days: 1));
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      _key.clear(); _password.clear();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    for (final c in [_key, _password, _contract, _budget, _maximum]) { c.clear(); c.dispose(); }
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_consent || !_form.currentState!.validate()) return;
    setState(() { _busy = true; _attempted = true; _error = null; });
    final payload = <String, dynamic>{'request_id': _requestId, 'wallet_id': widget.walletId,
      'private_key': _key.text.trim(), 'password': _password.text,
      'contract': _contract.text.trim(), 'budget_eth': _budget.text.trim(),
      'max_task_eth': _maximum.text.trim(), 'expires_at': _expiry.toIso8601String(), 'consent': true};
    _key.clear(); _password.clear();
    try {
      await ref.read(apiServiceProvider).importCustodyWallet(payload);
      if (mounted) Navigator.pop(context, true);
    } catch (_) {
      if (mounted) setState(() => _error = 'Import not confirmed. Refresh wallet policies if the connection was interrupted. Otherwise re-enter your key and Mintly password to retry with the same limits.');
    } finally {
      payload.remove('private_key'); payload.remove('password');
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _amount(String? value) {
    final text = (value ?? '').trim();
    final number = double.tryParse(text);
    return !RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(text) || number == null || !number.isFinite || number <= 0
      ? 'Enter a positive ETH amount with up to 18 decimals' : null;
  }

  @override
  Widget build(BuildContext context) => PopScope(canPop: !_busy, child: Scaffold(
    appBar: AppBar(title: const Text('Import for automatic minting')),
    body: FutureBuilder<Map<String, dynamic>>(future: _config, builder: (context, snapshot) {
      if (snapshot.hasError) return const Padding(padding: EdgeInsets.all(24), child: Text('Secure wallet import is not available on this server yet. No key has been requested or sent.'));
      if (!snapshot.hasData) return const Center(child: CircularProgressIndicator());
      return Form(key: _form, child: ListView(padding: const EdgeInsets.all(20), children: [
        SelectableText(widget.address),
        const SizedBox(height: 12),
        Text('Network: ${snapshot.data!['chain_id'] == 4663 ? 'Robinhood mainnet' : 'Chain ${snapshot.data!['chain_id']}'}'),
        const SizedBox(height: 12),
        const Text('Mintly will hold your wallet’s private key, encrypted on its signer server. The server can sign for this wallet. These limits are enforced by Mintly software, not by MetaMask or the blockchain.'),
        const SizedBox(height: 12),
        TextFormField(controller: _contract, enabled: !_busy && !_attempted, decoration: const InputDecoration(labelText: 'Allowed NFT collection contract (0x…)'),
          validator: (v) => RegExp(r'^0x[0-9a-fA-F]{40}$').hasMatch((v ?? '').trim()) ? null : 'Enter the collection contract address'),
        TextFormField(controller: _budget, enabled: !_busy && !_attempted, decoration: const InputDecoration(labelText: 'Total minting budget (ETH, including gas)'), validator: _amount),
        TextFormField(controller: _maximum, enabled: !_busy && !_attempted, decoration: const InputDecoration(labelText: 'Maximum per mint task (ETH, including gas)'),
          validator: (v) => _amount(v) ?? ((double.tryParse(v ?? '') ?? 0) > (double.tryParse(_budget.text) ?? 0) ? 'Must fit the total budget' : null)),
        DropdownButtonFormField<int>(
          icon: const RotatedBox(quarterTurns: 1, child: Icon(Icons.chevron_right)),initialValue: _days, decoration: const InputDecoration(labelText: 'Permission expires after'),
          items: [for (final days in [1, 7, 30]) DropdownMenuItem(value: days, child: Text('$days day${days == 1 ? '' : 's'}'))],
          onChanged: _busy || _attempted ? null : (v) => setState(() { _days = v!; _expiry = DateTime.now().toUtc().add(Duration(days: v)); })),
        Text('Expires: ${_expiry.toIso8601String()}'),
        const SizedBox(height: 12),
        TextFormField(key: const Key('custody-private-key'), controller: _key, enabled: !_busy, obscureText: true, autocorrect: false, enableSuggestions: false,
          autofillHints: const [], keyboardType: TextInputType.visiblePassword,
          decoration: const InputDecoration(labelText: 'Private key', helperText: '64 hex characters, optionally starting with 0x. Never enter a recovery phrase.'),
          validator: (v) => RegExp(r'^(0x)?[0-9a-fA-F]{64}$').hasMatch((v ?? '').trim()) ? null : 'Enter a valid private key, not a recovery phrase'),
        TextFormField(key: const Key('custody-password'), controller: _password, enabled: !_busy, obscureText: true, autocorrect: false, enableSuggestions: false,
          autofillHints: const [], decoration: const InputDecoration(labelText: 'Confirm your Mintly password'),
          validator: (v) => (v ?? '').isEmpty ? 'Enter your Mintly password' : null),
        CheckboxListTile(contentPadding: EdgeInsets.zero, value: _consent,
          onChanged: _busy ? null : (v) => setState(() => _consent = v ?? false),
          title: const Text('I authorize server custody with these limits. I understand that disabling minting does not erase the key or cancel signed transactions.')),
        const Text('Importing does not mint anything. Review and arm each automatic mint in the app. ETH limits are not a guaranteed USD limit.'),
        if (_error != null) Padding(padding: const EdgeInsets.symmetric(vertical: 12), child: Text(_error!)),
        const SizedBox(height: 16),
        FilledButton(onPressed: _busy || !_consent ? null : _submit, child: Text(_busy ? 'Importing…' : 'Import wallet')),
      ]));
    }),
  ));
}
