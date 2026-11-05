import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../services/wat_time.dart';
import '../theme/compatible_icons.dart';
import '../models/network_metadata.dart';

class FreeDropsScreen extends ConsumerStatefulWidget {
  const FreeDropsScreen({super.key});
  @override
  ConsumerState<FreeDropsScreen> createState() => _FreeDropsState();
}

class _FreeDropsState extends ConsumerState<FreeDropsScreen> {
  final _quantity = TextEditingController(text: '1'),
      _gas = TextEditingController();
  List<Map<String, dynamic>> _policies = [], _approvals = [], _wallets = [];
  Map<String, dynamic>? _policy, _current, _pending;
  DateTime? _approvalExpiry;
  bool _loading = true, _busy = false, _consent = false, _maximum = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _quantity.dispose();
    _gas.dispose();
    super.dispose();
  }

  String _units(dynamic value) {
    final n = BigInt.parse('$value');
    final scale = BigInt.from(10).pow(18);
    return '${n ~/ scale}.${(n % scale).toString().padLeft(18, '0')}';
  }

  void _select(Map<String, dynamic> policy) {
    _policy = policy;
    _current = null;
    _pending = null;
    _consent = false;
    for (final item in _approvals) {
      final s = item['snapshot'] as Map;
      if (s['wallet_id'] == policy['wallet_id'] &&
          s['chain_id'] == policy['chain_id'] &&
          ['active', 'registering', 'revoking'].contains(item['status'])) {
        _current = item;
        break;
      }
    }
    Map<String, dynamic>? saved = _current;
    for (final item in _approvals) {
      final snap = item['snapshot'] as Map;
      if (saved == null &&
          snap['wallet_id'] == policy['wallet_id'] &&
          snap['chain_id'] == policy['chain_id']) {
        saved = item;
      }
    }
    final s = saved?['snapshot'] as Map?;
    final expiry = DateTime.parse('${policy['expires_at']}').toUtc();
    final ceiling = DateTime.now().toUtc().add(const Duration(days: 60));
    _approvalExpiry = expiry.isBefore(ceiling) ? expiry : ceiling;
    _maximum = _current == null || s?['quantity_mode'] == 'wallet_max';
    _quantity.text = _maximum ? '65535' : '${s?['quantity'] ?? 1}';
    _gas.text = s == null ? '' : _units(s['fee_cap_wei']);
    if (_current?['status'] == 'registering') {
      _pending = {
        'request_id': _current!['id'],
        'grant_id': s!['grant_id'],
        'quantity': s['quantity'],
        if (_maximum) 'quantity_mode': 'wallet_max',
        'fee_cap': _gas.text,
        'native_symbol': policy['native_symbol'] ?? 'ETH',
        'expires_at': _current!['expires_at'],
        'consent': true,
      };
    }
  }

  Future<void> _load() async {
    try {
      final api = ref.read(apiServiceProvider);
      final results = await Future.wait<dynamic>([
        api.fetchAutomaticPolicies(),
        api.fetchFreeDropApprovals(),
        api.fetchWallets(),
      ]);
      if (!mounted) return;
      setState(() {
        _policies = (results[0] as List<Map<String, dynamic>>)
            .where((p) => p['status'] == 'enabled')
            .toList();
        _approvals = List<Map<String, dynamic>>.from(
          results[1]['approvals'] as List,
        );
        _wallets = results[2] as List<Map<String, dynamic>>;
        final selected = _policy?['id'];
        if (_policies.isNotEmpty) {
          _select(
            _policies.firstWhere(
              (p) => p['id'] == selected,
              orElse: () => _policies.firstWhere(
                (p) => p['wallet_id'] == api.selectedFeedWallet,
                orElse: () => _policies.first,
              ),
            ),
          );
        }
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = '$e';
        });
      }
    }
  }

  String _label(Map<String, dynamic> p) {
    final labels = _wallets.where((w) => w['id'] == p['wallet_id']);
    final label = labels.isEmpty
        ? 'Signing wallet'
        : '${labels.first['label']}';
    return '$label · ${networkNames[p['chain_id']] ?? 'Supported network'} · ${p['native_symbol'] ?? 'ETH'}';
  }

  Future<void> _enable() async {
    if (_busy || !_consent || _policy == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final count = int.tryParse(_quantity.text);
      if (count == null ||
          count < 1 ||
          count > (_maximum ? 65535 : 100) ||
          !RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(_gas.text.trim()) ||
          double.tryParse(_gas.text.trim()) == 0) {
        throw FormatException(
          _maximum
              ? 'Enter a positive maximum gas spend.'
              : 'Enter a quantity from 1 to 100 and a positive maximum gas spend.',
        );
      }
      if (_pending == null) {
        final bytes = List.generate(16, (_) => Random.secure().nextInt(256));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        final hex = bytes
            .map((b) => b.toRadixString(16).padLeft(2, '0'))
            .join();
        final id =
            '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
        _pending = {
          'request_id': id,
          'grant_id': _policy!['id'],
          'quantity': count,
          if (_maximum) 'quantity_mode': 'wallet_max',
          'fee_cap': _gas.text.trim(),
          'native_symbol': _policy!['native_symbol'] ?? 'ETH',
          'expires_at': _approvalExpiry!.toIso8601String(),
          'consent': true,
        };
      }
      await ref.read(apiServiceProvider).approveFreeDrops(_pending!);
      ref.invalidate(todayAutomationProvider);
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disable() async {
    if (_busy || _current == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(apiServiceProvider).revokeFreeDrops('${_current!['id']}');
      ref.invalidate(todayAutomationProvider);
      await _load();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final active = _current?['status'] == 'active';
    final pending = _current?['status'] == 'registering';
    return Scaffold(
      appBar: AppBar(title: const Text('Free drops automation')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Automatically arm eligible free WL, GTD, FCFS or public phases from Today’s @lakzonevn and @Cassio_Sch lists.',
          ),
          const SizedBox(height: 12),
          const Text(
            'Free means zero NFT price. Gas still costs money. Existing wallet budgets and daily limits apply. One collection is minted once; eligibility and supply are checked again before submission.',
          ),
          if (_loading) const LinearProgressIndicator(),
          if (!_loading && _policies.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Text('Set up a signing wallet in Wallet first.'),
            ),
          if (_policy != null) ...[
            DropdownButtonFormField<String>(
              key: ValueKey(_policy!['id']),
              initialValue: '${_policy!['id']}',
              isExpanded: true,
              icon: const RotatedBox(
                quarterTurns: 1,
                child: Icon(MintlyIcons.chevronRight),
              ),
              decoration: const InputDecoration(
                labelText: 'Wallet and network',
              ),
              items: _policies
                  .map(
                    (p) => DropdownMenuItem(
                      value: '${p['id']}',
                      child: Text(_label(p), overflow: TextOverflow.ellipsis),
                    ),
                  )
                  .toList(),
              onChanged: _busy
                  ? null
                  : (id) => setState(
                      () => _select(_policies.firstWhere((p) => p['id'] == id)),
                    ),
            ),
            if (_maximum)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  'NFTs per collection: Maximum allowed for this wallet',
                ),
              )
            else
              TextField(
                controller: _quantity,
                enabled: !_busy && _current == null && _pending == null,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'NFTs per collection',
                ),
              ),
            TextField(
              controller: _gas,
              enabled: !_busy && _current == null && _pending == null,
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              decoration: InputDecoration(
                labelText:
                    'Maximum gas per mint (${_policy!['native_symbol'] ?? 'ETH'})',
              ),
            ),
            const SizedBox(height: 12),
            if (_current == null && _approvalExpiry != null)
              Text('Approval ends ${WatTime.label(_approvalExpiry!)}'),
            if (_current != null) ...[
              Text(
                active
                    ? 'Enabled'
                    : pending
                    ? 'Signer confirmation pending'
                    : 'Stopping automation',
              ),
              Text('${_current!['note'] ?? ''}'),
              Text(
                'Expires ${WatTime.label(DateTime.parse('${_current!['expires_at']}'))}',
              ),
              const Text(
                'Your saved settings are shown above. Turn this approval off before changing its limits.',
              ),
              OutlinedButton(
                onPressed: _busy ? null : _disable,
                child: Text(
                  _busy ? 'Saving…' : 'Turn off free-drop automation',
                ),
              ),
            ],
            if (_current == null || pending) ...[
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _consent,
                onChanged: _busy
                    ? null
                    : (v) => setState(() => _consent = v == true),
                title: const Text(
                  'I approve eligible free daily-list mints for this wallet, quantity and gas cap, until the displayed signing approval expires (up to 60 days). Follow the same phase’s verified opening within the approved deadline.',
                ),
              ),
              FilledButton(
                onPressed: _busy || !_consent ? null : _enable,
                child: Text(
                  _busy
                      ? 'Saving…'
                      : pending
                      ? 'Retry signer confirmation'
                      : 'Enable automatic free mints',
                ),
              ),
            ],
          ],
          if (_error != null)
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          TextButton(
            onPressed: _busy ? null : _load,
            child: const Text('Refresh saved settings'),
          ),
        ],
      ),
    );
  }
}
