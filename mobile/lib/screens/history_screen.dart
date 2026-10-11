import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../state/app_state.dart';
import '../theme/compatible_icons.dart';
import '../widgets/screen_components.dart';
import '../widgets/collection_thumbnail.dart';
import '../services/external_url.dart';

class HistoryScreen extends ConsumerStatefulWidget {
  final bool embedded;
  const HistoryScreen({super.key, this.embedded = false});
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
      final api = ref.read(apiServiceProvider);
      final response = _section == 'copy_events'
          ? await api.fetchCopyActivity(offset: _next ?? 0)
          : await api.fetchHistory(_section, offset: _next ?? 0);
      final data = _section == 'copy_events'
          ? <String, dynamic>{
              'next_offset': response['next_offset'],
              'records': (response['events'] as List? ?? []).map((raw) {
                final event = Map<String, dynamic>.from(raw as Map);
                final observed = (event['observation'] as Map?) ?? {};
                return <String, dynamic>{
                  ...event,
                  'collection_name': observed['name'],
                  'chain': observed['chain'],
                  'created_at': event['observed_at'],
                  'actual_total_cost_wei': event['actual_cost_wei'],
                  'source_address': event['wallet_label'],
                  'contract_address': observed['contract'],
                  'artwork_reference': 'copy:${event['id']}',
                };
              }).toList(),
            }
          : response;
      if (!mounted || generation != _generation) return;
      if (reset) ref.invalidate(collectionArtworkProvider);
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
        : '${DateFormat('d MMM, HH:mm').format(date.toUtc().add(const Duration(hours: 1)))} WAT';
  }

  String _eth(dynamic value) {
    final n = BigInt.tryParse('$value');
    if (n == null) return '';
    final scale = BigInt.from(10).pow(18);
    final fraction = (n % scale)
        .toString()
        .padLeft(18, '0')
        .replaceFirst(RegExp(r'0+$'), '');
    return '${n ~/ scale}${fraction.isEmpty ? '' : '.$fraction'}';
  }

  Widget _recordAudit(Map<String, dynamic> record) {
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

  Widget _recordDetails(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map<String, dynamic>?) ?? record;
    final auth = data['authorization'] as Map<String, dynamic>?;
    final title =
        '${data['collection_name'] ?? data['drop_name'] ?? data['label'] ?? 'Wallet permission'}';
    final isCopy =
        data['artwork_reference']?.toString().startsWith('copy:') == true ||
        auth?['copy_source'] != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          title,
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 12),
        if (data['status'] != null)
          Align(
            alignment: Alignment.centerLeft,
            child: StatusBadge('${data['status']}'),
          ),
        const SizedBox(height: 20),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Summary',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
                if (data['chain'] != null)
                  DetailRow('Network', '${data['chain']}'),
                if (data['quantity'] != null)
                  DetailRow('Quantity', '${data['quantity']} NFTs'),
                if (data['chain'] != null)
                  DetailRow(
                    'Mint type',
                    isCopy ? 'Copy mint' : 'Automatic mint',
                  ),
                if (data['stage_name'] != null)
                  DetailRow('Phase', '${data['stage_name']}'),
                if (data['wallet_address'] != null)
                  DetailRow(
                    'Receiving wallet',
                    shortAddress('${data['wallet_address']}'),
                  ),
                if (data['source_address'] != null)
                  DetailRow(
                    'Followed wallet',
                    shortAddress('${data['source_address']}'),
                  ),
                if (data['confirmed_at'] != null)
                  DetailRow('Confirmed', _time(data['confirmed_at'])),
                if (data['actual_total_cost_wei'] != null) ...[
                  const Divider(height: 24),
                  DetailRow(
                    'Total spent',
                    '${_eth(data['actual_total_cost_wei'])} ETH',
                    emphasis: true,
                  ),
                  const Text(
                    'Includes mint value and charged network fees.',
                    style: TextStyle(fontSize: 12),
                  ),
                ],
                if (data['actual_total_cost_wei'] == null &&
                    data['total_cap_eth'] != null)
                  DetailRow(
                    'Approved spending cap',
                    '${data['total_cap_eth']} ETH',
                  ),
                for (final key in ['failure_reason', 'note', 'detail'])
                  if (data[key] != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text('${data[key]}'),
                    ),
              ],
            ),
          ),
        ),
        if (data['submitted_at'] != null || data['confirmed_at'] != null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Transaction timeline',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                  ),
                  if (data['authorized_at'] != null)
                    DetailRow('Approved', _time(data['authorized_at'])),
                  if (data['submitted_at'] != null)
                    DetailRow('Submitted', _time(data['submitted_at'])),
                  if (data['confirmed_at'] != null)
                    DetailRow('Confirmed', _time(data['confirmed_at'])),
                ],
              ),
            ),
          ),
        ExpansionTile(
          title: const Text('Approval & recovery history'),
          children: [_recordAudit(record)],
        ),
      ],
    );
  }

  Widget _record(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map<String, dynamic>?) ?? record;
    final auth = data['authorization'] as Map<String, dynamic>?;
    final title =
        '${data['collection_name'] ?? data['drop_name'] ?? data['label'] ?? 'Wallet permission'}';
    final status = '${data['status'] ?? record['event'] ?? ''}';
    final reference =
        data['artwork_reference'] as String? ??
        (data['drop_id'] != null
            ? 'drop:${data['drop_id']}'
            : record['snapshot'] != null && data['id'] != null
            ? 'plan:${data['id']}'
            : '');
    final isCopy = _section == 'copy_events' || auth?['copy_source'] != null;
    final note = data['failure_reason'] ?? data['note'] ?? data['detail'];
    return Card(
      margin: const EdgeInsets.only(bottom: 14),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CollectionThumbnail(name: title, reference: reference),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 6),
                      if (status.isNotEmpty) StatusBadge(status),
                      if (data['chain'] != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            '${isCopy ? 'Copy mint' : 'Automatic mint'} · ${data['chain']}',
                          ),
                        ),
                      if (data['quantity'] != null)
                        Text(
                          '${data['quantity']} NFT${data['quantity'] == 1 ? '' : 's'}',
                        ),
                    ],
                  ),
                ),
              ],
            ),
            if (note != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  '$note',
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            const SizedBox(height: 12),
            const Divider(),
            if (data['actual_total_cost_wei'] != null)
              DetailRow(
                'Total spent',
                '${_eth(data['actual_total_cost_wei'])} ETH',
                emphasis: true,
              ),
            if (data['actual_total_cost_wei'] == null &&
                data['total_cap_eth'] != null &&
                [
                  'armed',
                  'preparing',
                  'prepared',
                  'submitted',
                  'uncertain',
                ].contains(status))
              DetailRow('Approved cap', '${data['total_cap_eth']} ETH'),
            Row(
              children: [
                Expanded(
                  child: Text(
                    _time(record['recorded_at'] ?? data['created_at']),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                TextButton(
                  onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => Scaffold(
                        appBar: AppBar(
                          title: Text(
                            data['chain'] != null
                                ? 'Mint details'
                                : 'Activity details',
                          ),
                        ),
                        body: ListView(
                          padding: const EdgeInsets.all(20),
                          children: [
                            _recordDetails(record),
                            if (data['explorer_url'] is String &&
                                Uri.tryParse(data['explorer_url'])?.scheme ==
                                    'https')
                              FilledButton(
                                onPressed: () => openExternalUrl(
                                  context,
                                  Uri.parse(data['explorer_url']),
                                ),
                                child: const Text('View transaction'),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  child: const Text('View details'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: widget.embedded ? null : AppBar(title: const Text('Activity')),
    body: RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(20),
        children: [
          if (widget.embedded)
            const ScreenHeading('Activity', 'Your mints, copies and updates.'),
          Wrap(
            spacing: 8,
            children: [
              for (final item in [
                ('mints', 'Mints'),
                ('copy_events', 'Copies'),
                ('activity', 'Updates'),
              ])
                ChoiceChip(
                  label: Text(item.$2),
                  selected: _section == item.$1,
                  onSelected: (_) {
                    _section = item.$1;
                    _load(reset: true);
                  },
                ),
            ],
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            key: ValueKey(_section),
            initialValue: _section,
            icon: const RotatedBox(
              quarterTurns: 1,
              child: Icon(MintlyIcons.chevronRight),
            ),
            decoration: const InputDecoration(labelText: 'Records'),
            items: const [
              DropdownMenuItem(
                value: 'mints',
                child: Text('All mint transactions'),
              ),
              DropdownMenuItem(
                value: 'copy_events',
                child: Text('Copy events'),
              ),
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
          const Text(
            'Removed records stay in history. Pull down to refresh.',
            style: TextStyle(fontSize: 12),
          ),
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
