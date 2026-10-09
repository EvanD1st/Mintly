import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../state/app_state.dart';
import '../theme/compatible_icons.dart';

class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key});
  @override
  ConsumerState<HistoryScreen> createState() => _HistoryState();
}

class _HistoryState extends ConsumerState<HistoryScreen> {
  String _section = 'mints';
  final List<Map<String, dynamic>> _records = [];
  int? _next = 0;
  int _generation = 0;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load(reset: true);
  }

  Future<void> _load({bool reset = false}) async {
    if (!reset && (_busy || _next == null)) return;
    final generation = reset ? ++_generation : _generation;
    setState(() {
      _busy = true;
      _error = null;
      if (reset) {
        _records.clear();
        _next = 0;
      }
    });
    try {
      final data = await ref
          .read(apiServiceProvider)
          .fetchHistory(_section, offset: _next ?? 0);
      if (!mounted || generation != _generation) return;
      setState(() {
        final existing = _records.map((r) => r['id']).toSet();
        _records.addAll(
          (data['records'] as List).cast<Map<String, dynamic>>().where(
            (r) => !existing.contains(r['id']),
          ),
        );
        _next = data['next_offset'] as int?;
      });
    } catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _error = '$error');
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  String _time(dynamic value) {
    final date = DateTime.tryParse('$value');
    return date == null
        ? ''
        : DateFormat('d MMM yyyy, HH:mm').format(date.toLocal());
  }

  String _eth(dynamic value) {
    final n = BigInt.tryParse('$value');
    if (n == null) return '';
    final scale = BigInt.from(10).pow(18);
    return '${n ~/ scale}.${(n % scale).toString().padLeft(18, '0')}';
  }

  Widget _record(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map<String, dynamic>?) ?? record;
    final authorization = data['authorization'] as Map<String, dynamic>?;
    final title =
        data['collection_name'] ??
        data['drop_name'] ??
        data['label'] ??
        'Mint permission';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$title', style: Theme.of(context).textTheme.titleMedium),
            Text(_time(record['recorded_at'] ?? data['created_at'])),
            if (record['event'] != null) Text('Plan ${record['event']}'),
            if (data['status'] != null) Text('Status: ${data['status']}'),
            if (data['archived_at'] != null)
              Text('Removed ${_time(data['archived_at'])} · record retained'),
            if (data['quantity'] != null)
              Text(
                authorization?['quantity_mode'] == 'max_free'
                    ? 'Max free quantity (up to ${data['quantity']} NFTs) · ${data['chain'] ?? ''}'
                    : '${data['quantity']} NFTs · ${data['chain'] ?? ''}',
              ),
            if (authorization?['contract'] != null)
              SelectableText('Collection: ${authorization!['contract']}'),
            if (authorization?['copy_source'] != null) ...[
              SelectableText(
                'Copied from: ${authorization!['copy_source']['source_address']}',
              ),
              SelectableText(
                'Source mint: ${authorization['copy_source']['source_hash']}',
              ),
            ],
            if (authorization?['price_cap_wei'] != null)
              Text(
                'Price ceiling per NFT: ${_eth(authorization!['price_cap_wei'])} ETH',
              ),
            if (data['authorized_at'] != null)
              Text('Authorized: ${_time(data['authorized_at'])}'),
            if (data['expires_at_utc'] != null)
              Text('Submission expiry: ${_time(data['expires_at_utc'])}'),
            if (data['stage_name'] != null)
              Text('Stage: ${data['stage_name']}'),
            if (data['scheduled_for_utc'] != null || data['starts_at'] != null)
              Text(
                'Scheduled: ${_time(data['scheduled_for_utc'] ?? data['starts_at'])}',
              ),
            if (data['price_eth'] != null)
              Text('Price per NFT: ${data['price_eth']} ETH'),
            if (data['fee_cap_eth'] != null)
              Text('Gas limit: ${data['fee_cap_eth']} ETH'),
            if (data['total_cap_eth'] != null)
              Text('Authorized total: ${data['total_cap_eth']} ETH'),
            if (data['actual_total_cost_wei'] != null)
              Text('Actual spend: ${_eth(data['actual_total_cost_wei'])} ETH'),
            if (data['wallet_address'] != null)
              SelectableText('Wallet: ${data['wallet_address']}'),
            if (data['source_address'] != null)
              SelectableText('Following: ${data['source_address']}'),
            if (data['budget_wei'] != null)
              Text('Copy budget: ${_eth(data['budget_wei'])} ETH'),
            if (data['spent_wei'] != null)
              Text('Copy spend: ${_eth(data['spent_wei'])} ETH'),
            if (data['reserved_wei'] != null)
              Text('Pending reservations: ${_eth(data['reserved_wei'])} ETH'),
            if (authorization?['fee_cap_wei'] != null)
              Text(
                'Network fee ceiling: ${_eth(authorization!['fee_cap_wei'])} ETH',
              ),
            if (data['expires_at'] != null)
              Text('Permission ends: ${_time(data['expires_at'])}'),
            if (data['contract_address'] != null)
              SelectableText('Collection: ${data['contract_address']}'),
            if (data['transaction_hash'] != null)
              SelectableText('Transaction: ${data['transaction_hash']}'),
            for (final recovery in (data['recoveries'] as List? ?? [])) ...[
              Text('Same-nonce recovery: ${recovery['status']}'),
              Text(
                'Authorized: ${_time(recovery['authorized_at'])} · nonce ${recovery['nonce']}',
              ),
              Text('Recovery expiry: ${_time(recovery['expires_at'])}'),
              SelectableText(
                'Original transaction: ${recovery['previous_hash']}',
              ),
              if (recovery['replacement_hash'] != null)
                SelectableText(
                  'Replacement transaction: ${recovery['replacement_hash']}',
                ),
            ],
            if (data['confirmed_at'] != null)
              Text('Receipt confirmed: ${_time(data['confirmed_at'])}'),
            for (final key in [
              'status_note',
              'failure_reason',
              'detail',
              'note',
            ])
              if (data[key] != null) Text('${data[key]}'),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('History')),
    body: RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Your saved plans and mint records stay here after removal. Pull down to refresh transactions still in flight.',
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            initialValue: _section,
            icon: const RotatedBox(
              quarterTurns: 1,
              child: Icon(MintlyIcons.chevronRight),
            ),
            decoration: const InputDecoration(labelText: 'Records'),
            items: const [
              DropdownMenuItem(value: 'mints', child: Text('Automatic mints')),
              DropdownMenuItem(value: 'plans', child: Text('Plan history')),
              DropdownMenuItem(
                value: 'activity',
                child: Text('Account activity'),
              ),
              DropdownMenuItem(
                value: 'permissions',
                child: Text('Wallet permissions'),
              ),
              DropdownMenuItem(value: 'copies', child: Text('Copy approvals')),
            ],
            onChanged: (value) {
              if (value == null) return;
              _section = value;
              _load(reset: true);
            },
          ),
          const SizedBox(height: 16),
          ..._records.map(_record),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null) Text(_error!),
          if (!_busy && _records.isEmpty && _error == null)
            const Text('No records yet.'),
          if (!_busy && _next != null)
            TextButton(
              onPressed: () => _load(),
              child: Text(_error == null ? 'Load more' : 'Retry'),
            ),
        ],
      ),
    ),
  );
}
