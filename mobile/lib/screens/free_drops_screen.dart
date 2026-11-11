import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../services/wat_time.dart';
import '../theme/compatible_icons.dart';
import '../models/network_metadata.dart';
import '../widgets/screen_components.dart';

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
  bool _loading = true,
      _busy = false,
      _consent = false,
      _maximum = false,
      _paused = false;
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
    return '${n ~/ scale}.${(n % scale).toString().padLeft(18, '0')}'
        .replaceFirst(RegExp(r'0+$'), '')
        .replaceFirst(RegExp(r'\.$'), '');
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
    _gas.text = s == null
        ? ((policy['native_symbol'] ?? 'ETH') == 'ETH' ? '0.00002' : '')
        : _units(saved?['effective_fee_cap_wei'] ?? s['fee_cap_wei']);
    if (_current?['status'] == 'registering') {
      _pending = {
        'request_id': _current!['id'],
        'grant_id': s!['grant_id'],
        'quantity': s['quantity'],
        if (_maximum) 'quantity_mode': 'wallet_max',
        'fee_cap': _units(s['fee_cap_wei']),
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
        _paused = results[1]['automation_paused'] == true;
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

  Widget _panel(List<Widget> children) => Card(
    margin: const EdgeInsets.only(bottom: 14),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final active = _current?['status'] == 'active';
    final pending = _current?['status'] == 'registering';
    final stopping = _current?['status'] == 'revoking';
    final note = '${_current?['note'] ?? ''}';
    final allowanceLow = active && note.contains('below your chosen gas cap');
    final reserved = active && note.contains('pending mint reservations');
    final budgetBlocked = allowanceLow || reserved;
    final title = _paused
        ? 'Paused'
        : pending
        ? 'Finishing setup'
        : stopping
        ? 'Turning off'
        : budgetBlocked
        ? 'Needs attention'
        : active
        ? 'Enabled'
        : 'Off';
    final description = _paused
        ? 'Resume automation from Wallet.'
        : pending
        ? 'Retry to finish setup with your saved limits.'
        : stopping
        ? 'New signing is blocked while we confirm.'
        : allowanceLow
        ? 'Your signing allowance is below this gas limit.'
        : reserved
        ? 'Another mint is using part of your signing allowance.'
        : active
        ? 'Your saved settings are loaded.'
        : 'Choose your limits, then turn it on.';
    final expiry = _current == null
        ? _approvalExpiry
        : DateTime.tryParse('${_current!['expires_at']}');
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Free drops automation',
          style: TextStyle(fontFamily: 'Roboto'),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Text(
            'Free mints, on autopilot',
            style: Theme.of(
              context,
            ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          const Text('Mintly arms free mints you qualify for from Today.'),
          const SizedBox(height: 16),
          if (_loading) const LinearProgressIndicator(),
          if (!_loading && _policies.isEmpty)
            _panel([const Text('Set up a signing wallet in Wallet first.')]),
          if (_policy != null) ...[
            _panel([
              Text(
                'AUTO-ARMING',
                style: TextStyle(
                  fontSize: 11,
                  letterSpacing: 1.3,
                  color: colors.onSurface.withValues(alpha: .65),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                title,
                style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w700,
                  color: active && !_paused && !budgetBlocked
                      ? colors.primary
                      : colors.onSurface,
                ),
              ),
              const SizedBox(height: 4),
              Text(description),
              if (expiry != null) ...[
                const SizedBox(height: 12),
                Text(
                  'Approval ends ${WatTime.label(expiry)}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ]),
            _panel([
              Text(
                'Wallet & limits',
                style: Theme.of(
                  context,
                ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 16),
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
                        () =>
                            _select(_policies.firstWhere((p) => p['id'] == id)),
                      ),
              ),
              const SizedBox(height: 18),
              if (_maximum) ...[
                const Text(
                  'NFTs per collection',
                  style: TextStyle(fontSize: 12),
                ),
                const SizedBox(height: 4),
                const Text(
                  'Maximum allowed for this wallet',
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
              ] else
                TextField(
                  controller: _quantity,
                  style: TextStyle(color: colors.onSurface),
                  enabled: !_busy && _current == null && _pending == null,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'NFTs per collection',
                  ),
                ),
              const SizedBox(height: 18),
              TextField(
                controller: _gas,
                style: TextStyle(color: colors.onSurface),
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
              Text(
                (_policy!['native_symbol'] ?? 'ETH') == 'ETH'
                    ? 'Auto-Arming uses up to 0.00002 ETH per mint. Higher fees wait.'
                    : 'Free NFTs. Gas still costs money.',
                style: TextStyle(
                  color: colors.onSurface.withValues(alpha: .75),
                ),
              ),
              if (_current != null && !pending) ...[
                const SizedBox(height: 8),
                const Text(
                  'Turn off before changing these limits.',
                  style: TextStyle(fontSize: 12),
                ),
              ],
            ]),
            if (_current == null || pending) ...[
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _consent,
                onChanged: _busy
                    ? null
                    : (v) => setState(() => _consent = v == true),
                title: const Text(
                  'Allow eligible free mints with these limits until the expiry shown.',
                ),
              ),
              const SizedBox(height: 8),
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
            if (_current != null)
              OutlinedButton(
                onPressed: _busy ? null : _disable,
                child: Text(
                  _busy ? 'Saving…' : 'Turn off free-drop automation',
                  style: const TextStyle(fontFamily: 'Roboto'),
                ),
              ),
          ],
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(_error!, style: TextStyle(color: colors.error)),
            ),
          const SizedBox(height: 12),
          Card(
            child: DisclosureSection(
              title: const Text('How it works'),
              children: const [
                Padding(
                  padding: EdgeInsets.fromLTRB(16, 0, 16, 16),
                  child: Text(
                    'Eligible free WL, GTD, FCFS and public phases from @lakzonevn and @Cassio_Sch.\n\nYour wallet budgets and daily limits still apply. Eligibility and supply are checked again before minting.\n\nMintly follows the phase’s verified opening, within your approval deadline. One mint per collection.',
                  ),
                ),
              ],
            ),
          ),
          if (note.isNotEmpty && !note.startsWith('Watching '))
            DisclosureSection(
              title: const Text('Latest activity'),
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: Text(note),
                ),
              ],
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
