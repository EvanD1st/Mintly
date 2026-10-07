import '../theme/compatible_icons.dart';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/wallet_secret.dart';
import '../state/app_state.dart';

final walletSecretResolverProvider =
    Provider<Future<Uint8List?> Function(Map<String, String>)>(
      (ref) =>
          (input) => compute(resolveWalletSecret, input),
    );

class CustodyImportScreen extends ConsumerStatefulWidget {
  final String? walletId;
  final String? address;
  const CustodyImportScreen({super.key, this.walletId, this.address});
  @override
  ConsumerState<CustodyImportScreen> createState() =>
      _CustodyImportScreenState();
}

class _CustodyImportScreenState extends ConsumerState<CustodyImportScreen>
    with WidgetsBindingObserver {
  final _form = GlobalKey<FormState>();
  final _key = TextEditingController();
  final _accountNumber = TextEditingController(text: '1');
  final _label = TextEditingController(text: 'Wallet');
  String? _selectedAddress;
  final _password = TextEditingController();
  final _budget = TextEditingController();
  final _maximum = TextEditingController();
  late final Future<Map<String, dynamic>> _config;
  late final String _requestId;
  late DateTime _expiry;
  Uint8List? _walletKey;
  int _days = 7, _generation = 0;
  int? _chainId;
  bool _limits = false,
      _moreLimits = false,
      _consent = false,
      _busy = false,
      _attempted = false;
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
    _requestId =
        '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
    _expiry = DateTime.now().toUtc().add(Duration(days: _days));
  }

  void _clearKey() {
    _walletKey?.fillRange(0, _walletKey!.length, 0);
    _walletKey = null;
    _selectedAddress = null;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      _generation++;
      _key.clear();
      _password.clear();
      _clearKey();
      if (mounted) setState(() => _limits = false);
    }
  }

  @override
  void dispose() {
    _generation++;
    WidgetsBinding.instance.removeObserver(this);
    _clearKey();
    for (final c in [
      _key,
      _password,
      _budget,
      _maximum,
      _accountNumber,
      _label,
    ]) {
      c.clear();
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _continue() async {
    if (!_form.currentState!.validate()) return;
    final generation = _generation;
    final secret = <String, String>{
      'kind': 'phrase',
      'secret': _key.text,
      if (widget.address != null) 'address': widget.address!,
      if (widget.address == null)
        'account_index': '${(int.tryParse(_accountNumber.text) ?? 1) - 1}',
    };
    _key.clear();
    setState(() {
      _busy = true;
      _error = null;
    });
    Uint8List? derived;
    try {
      derived = await ref.read(walletSecretResolverProvider)(secret);
      if (!mounted || generation != _generation) {
        derived?.fillRange(0, derived.length, 0);
        return;
      }
      if (derived == null) {
        setState(
          () => _error =
              'This phrase does not contain the selected wallet account.',
        );
      } else {
        final accountAddress = walletAddressFromKey(derived);
        if (widget.walletId == null && !_attempted) {
          final wallets = await ref.read(apiServiceProvider).fetchWallets();
          if (!mounted || generation != _generation) {
            derived.fillRange(0, derived.length, 0);
            return;
          }
          if (wallets.any(
            (w) =>
                '${w['address']}'.toLowerCase() == accountAddress.toLowerCase(),
          )) {
            derived.fillRange(0, derived.length, 0);
            setState(
              () => _error =
                  'This account is already linked. Choose another account number or phrase.',
            );
            return;
          }
        }
        _clearKey();
        _walletKey = derived;
        _selectedAddress = accountAddress;
        setState(() => _limits = true);
      }
    } catch (_) {
      derived?.fillRange(0, derived.length, 0);
      if (mounted) {
        setState(
          () => _error =
              'Could not check this wallet. Re-enter the secret to try again.',
        );
      }
    } finally {
      secret.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    if (!_consent || _walletKey == null || !_form.currentState!.validate()) {
      return;
    }
    setState(() {
      _busy = true;
      _attempted = true;
      _error = null;
    });
    final payload = <String, dynamic>{
      'request_id': _requestId,
      if (widget.walletId != null) 'wallet_id': widget.walletId,
      'account_address': _selectedAddress,
      'wallet_label': _label.text.trim().isEmpty
          ? 'Wallet'
          : _label.text.trim(),
      if (_chainId != null) 'chain_id': _chainId,
      'private_key': _walletKey!
          .map((v) => v.toRadixString(16).padLeft(2, '0'))
          .join(),
      'password': _password.text,
      'collection_scope': 'reviewed_mints',
      'budget_eth': _budget.text.trim(),
      'max_task_eth': _maximum.text.trim().isEmpty
          ? _budget.text.trim()
          : _maximum.text.trim(),
      'expires_at': _expiry.toIso8601String(),
      'consent': true,
    };
    _clearKey();
    _password.clear();
    try {
      await ref.read(apiServiceProvider).importCustodyWallet(payload);
      if (mounted) Navigator.pop(context, true);
    } catch (_) {
      if (mounted) {
        setState(() {
          _limits = false;
          _error =
              'Import not confirmed. Refresh your wallet status if the connection was interrupted. Re-enter your secret and Mintly password to retry with the same limits.';
        });
      }
    } finally {
      payload.remove('private_key');
      payload.remove('password');
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _amount(String? value) {
    final text = (value ?? '').trim();
    final number = double.tryParse(text);
    return !RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(text) ||
            number == null ||
            !number.isFinite ||
            number <= 0
        ? 'Enter a positive ETH amount with up to 18 decimals'
        : null;
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_busy,
    child: Scaffold(
      appBar: AppBar(
        title: Text(_limits ? 'Minting limits' : 'Import MetaMask wallet'),
      ),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _config,
        builder: (context, snapshot) {
          if (snapshot.hasError ||
              (snapshot.hasData &&
                  (snapshot.data!['automatic_collection_selection'] != true ||
                      (widget.walletId == null &&
                          snapshot.data!['phrase_wallet_setup'] != true)))) {
            return const Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'Secure wallet import is not available on this server yet. No secret has been requested or sent.',
              ),
            );
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final networks = (snapshot.data!['networks'] as List? ?? [])
              .cast<Map<String, dynamic>>();
          return Form(
            key: _form,
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text(
                  _limits
                      ? 'Choose your spending limit'
                      : 'Use your existing wallet',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                if (networks.length > 1)
                  DropdownButtonFormField<int>(
                    initialValue: _chainId ?? snapshot.data!['chain_id'] as int,
                    icon: const RotatedBox(
                      quarterTurns: 1,
                      child: Icon(MintlyIcons.chevronRight),
                    ),
                    decoration: const InputDecoration(
                      labelText: 'Network for this wallet policy',
                    ),
                    items: networks
                        .map(
                          (n) => DropdownMenuItem(
                            value: n['chain_id'] as int,
                            child: Text('${n['name']}'),
                          ),
                        )
                        .toList(),
                    onChanged: _busy || _attempted
                        ? null
                        : (value) => setState(() => _chainId = value),
                  )
                else
                  Text(
                    'Network: ${snapshot.data!['chain_id'] == 4663 ? 'Robinhood mainnet' : 'Chain ${snapshot.data!['chain_id']}'}',
                  ),
                if (_chainId == 8453)
                  const Text(
                    'Base parent-chain fees can change until inclusion. Limits are checked before submission.',
                  ),
                const SizedBox(height: 8),
                if (_selectedAddress != null || widget.address != null)
                  SelectableText(
                    _selectedAddress ?? widget.address!,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                const SizedBox(height: 24),
                if (!_limits) ...[
                  const Text(
                    'Your phrase stays on this device. Mintly stores the selected account’s encrypted key for automatic minting.',
                  ),
                  const SizedBox(height: 16),
                  if (widget.walletId == null) ...[
                    TextFormField(
                      controller: _label,
                      enabled: !_busy,
                      maxLength: 80,
                      decoration: const InputDecoration(
                        labelText: 'Wallet name',
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _accountNumber,
                      enabled: !_busy,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(
                        labelText: 'Account number',
                        helperText: 'Account 1, 2, etc. from this phrase',
                      ),
                      validator: (value) =>
                          (int.tryParse(value ?? '') ?? 0) < 1 ||
                              (int.tryParse(value ?? '') ?? 21) > 20
                          ? 'Choose account 1 to 20'
                          : null,
                    ),
                    const SizedBox(height: 16),
                  ],
                  TextFormField(
                    key: const Key('custody-recovery-phrase'),
                    controller: _key,
                    enabled: !_busy,
                    obscureText: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    autofillHints: const [],
                    keyboardType: TextInputType.visiblePassword,
                    decoration: const InputDecoration(
                      labelText: 'Secret recovery phrase',
                      helperText: '12 or 24 words, in order',
                    ),
                    validator: (v) =>
                        [12, 24].contains(
                          (v ?? '').trim().split(RegExp(r'\s+')).length,
                        )
                        ? null
                        : 'Enter 12 or 24 words',
                  ),
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _busy ? null : _continue,
                    child: Text(_busy ? 'Checking wallet…' : 'Continue'),
                  ),
                ] else ...[
                  const Text('Approve access for this selected account.'),
                  const SizedBox(height: 20),
                  TextFormField(
                    key: const Key('custody-budget'),
                    controller: _budget,
                    enabled: !_busy && !_attempted,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(
                      labelText: 'Total budget (ETH)',
                      helperText: 'Includes NFT prices and network fees',
                    ),
                    validator: _amount,
                  ),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<int>(
                    initialValue: _days,
                    icon: const RotatedBox(
                      quarterTurns: 1,
                      child: Icon(MintlyIcons.chevronRight),
                    ),
                    decoration: const InputDecoration(
                      labelText: 'Allow automatic minting for',
                    ),
                    items: [
                      for (final days in [1, 7, 30])
                        DropdownMenuItem(
                          value: days,
                          child: Text('$days day${days == 1 ? '' : 's'}'),
                        ),
                    ],
                    onChanged: _busy || _attempted
                        ? null
                        : (v) => setState(() {
                            _days = v!;
                            _expiry = DateTime.now().toUtc().add(
                              Duration(days: v),
                            );
                          }),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('custody-password'),
                    controller: _password,
                    enabled: !_busy,
                    obscureText: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    autofillHints: const [],
                    decoration: const InputDecoration(
                      labelText: 'Confirm your Mintly password',
                    ),
                    validator: (v) =>
                        (v ?? '').isEmpty ? 'Enter your Mintly password' : null,
                  ),
                  const SizedBox(height: 16),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _consent,
                    onChanged: _busy
                        ? null
                        : (v) => setState(() => _consent = v ?? false),
                    title: const Text(
                      'I authorize Mintly to store this account’s encrypted key and mint within my limits.',
                    ),
                    subtitle: const Text(
                      'The server has signing access. Limits are enforced by Mintly software.',
                    ),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _busy || !_consent ? null : _submit,
                    child: Text(_busy ? 'Importing…' : 'Import wallet'),
                  ),
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => setState(() {
                            _clearKey();
                            _password.clear();
                            _limits = false;
                          }),
                    child: const Text('Change account'),
                  ),
                  TextButton(
                    onPressed: () => setState(() => _moreLimits = !_moreLimits),
                    child: Text(
                      _moreLimits
                          ? 'Hide access and limits'
                          : 'More about access and limits',
                    ),
                  ),
                  if (_moreLimits)
                    Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        children: [
                          TextFormField(
                            controller: _maximum,
                            enabled: !_busy && !_attempted,
                            decoration: const InputDecoration(
                              labelText: 'Maximum per mint (ETH, optional)',
                              helperText: 'Blank uses your total budget',
                            ),
                            validator: (v) => (v ?? '').trim().isEmpty
                                ? null
                                : _amount(v) ??
                                      ((double.tryParse(v ?? '') ?? 0) >
                                              (double.tryParse(_budget.text) ??
                                                  0)
                                          ? 'Must fit the total budget'
                                          : null),
                          ),
                          const SizedBox(height: 12),
                          const Text(
                            'Importing does not submit a mint. Review each automatic mint in Mintly. Disabling stops future signing; it cannot erase the key or cancel signed transactions. ETH limits are not a guaranteed USD limit.',
                          ),
                        ],
                      ),
                    ),
                ],
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(_error!),
                  ),
              ],
            ),
          );
        },
      ),
    ),
  );
}
