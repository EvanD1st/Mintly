import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../state/app_state.dart';
import '../widgets/screen_components.dart';
import '../widgets/collection_thumbnail.dart';
import '../services/external_url.dart';
import '../widgets/main_navigation.dart';
import '../widgets/network_budget_card.dart';

class HistoryScreen extends ConsumerStatefulWidget {
  final bool embedded;
  final String initialSection;
  const HistoryScreen({
    super.key,
    this.embedded = false,
    this.initialSection = 'all',
  });
  @override
  ConsumerState<HistoryScreen> createState() => _HistoryState();
}

class _HistoryState extends ConsumerState<HistoryScreen> {
  late String _section;
  Map<String, int?> _allOffsets = {'mints': 0, 'copy_events': 0, 'activity': 0};
  final List<Map<String, dynamic>> _records = [];
  int? _next = 0;
  int _generation = 0;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _section = widget.initialSection;
    _load(reset: true);
  }

  Map<String, dynamic> _copyRecord(Map raw) {
    final event = Map<String, dynamic>.from(raw);
    final observed = (event['observation'] as Map?) ?? {};
    return {
      ...event,
      '_source': 'copy_events',
      'collection_name': observed['name'],
      'chain': observed['chain'],
      'created_at': event['observed_at'],
      'actual_total_cost_wei': event['actual_cost_wei'],
      'source_address': observed['source_address'],
      '_source_label': event['wallet_label'],
      'contract_address': observed['contract'],
      'artwork_reference': 'copy:${event['id']}',
    };
  }

  Future<void> _load({bool reset = false}) async {
    if (!reset && (_busy || _next == null)) return;
    final generation = reset ? ++_generation : _generation;
    final section = _section;
    setState(() {
      _busy = true;
      _error = null;
      if (reset) {
        _records.clear();
        _next = 0;
        _allOffsets = {'mints': 0, 'copy_events': 0, 'activity': 0};
      }
    });
    try {
      final api = ref.read(apiServiceProvider);
      final nextOffsets = Map<String, int?>.from(_allOffsets);
      final incoming = <Map<String, dynamic>>[];
      int? next;
      if (section == 'all') {
        final streams = _allOffsets.entries
            .where((e) => e.value != null)
            .toList();
        final replies = await Future.wait(
          streams.map(
            (entry) => entry.key == 'copy_events'
                ? api.fetchCopyActivity(offset: entry.value!)
                : api.fetchHistory(entry.key, offset: entry.value!),
          ),
        );
        for (var i = 0; i < replies.length; i++) {
          final source = streams[i].key;
          final reply = replies[i];
          incoming.addAll(
            source == 'copy_events'
                ? (reply['events'] as List? ?? []).map(
                    (r) => _copyRecord(r as Map),
                  )
                : (reply['records'] as List).map(
                    (r) => {
                      ...Map<String, dynamic>.from(r as Map),
                      '_source': source,
                    },
                  ),
          );
          nextOffsets[source] = reply['next_offset'] as int?;
        }
        next = nextOffsets.values.any((v) => v != null) ? 1 : null;
      } else {
        final reply = section == 'copy_events'
            ? await api.fetchCopyActivity(offset: _next ?? 0)
            : await api.fetchHistory(section, offset: _next ?? 0);
        incoming.addAll(
          section == 'copy_events'
              ? (reply['events'] as List? ?? []).map(
                  (r) => _copyRecord(r as Map),
                )
              : (reply['records'] as List).map(
                  (r) => {
                    ...Map<String, dynamic>.from(r as Map),
                    '_source': section,
                  },
                ),
        );
        next = reply['next_offset'] as int?;
      }
      if (!mounted || generation != _generation) return;
      if (reset) ref.invalidate(collectionArtworkProvider);
      setState(() {
        final existing = _records.map((r) => r['id']).toSet();
        _records.addAll(incoming.where((r) => existing.add(r['id'])));
        if (section == 'all') {
          final copies = {
            for (final r in _records.where(
              (r) => r['_source'] == 'copy_events' && r['task_id'] != null,
            ))
              '${r['task_id']}': r,
          };
          final taskIds = _records
              .where((r) => r['_source'] == 'mints')
              .map((r) => '${r['id']}')
              .toSet();
          for (final task in _records.where((r) => r['_source'] == 'mints')) {
            final copy = copies['${task['id']}'];
            if (copy != null) {
              task['_copy'] = true;
              task['_source_label'] = copy['_source_label'];
              task['artwork_reference'] = copy['artwork_reference'];
            }
          }
          _records.removeWhere(
            (r) =>
                r['_source'] == 'copy_events' &&
                taskIds.contains('${r['task_id']}'),
          );
          _records.sort((a, b) {
            final order = _recordDate(b).compareTo(_recordDate(a));
            return order != 0 ? order : '${a['id']}'.compareTo('${b['id']}');
          });
        }
        _allOffsets = nextOffsets;
        _next = next;
      });
    } catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _error = '$error');
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  DateTime _recordDate(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map?) ?? record;
    return DateTime.tryParse(
          '${record['recorded_at'] ?? data['created_at']}',
        )?.toUtc() ??
        DateTime.fromMillisecondsSinceEpoch(0, isUtc: true);
  }

  String _artworkReference(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map?) ?? record;
    if (data['artwork_reference'] is String) return data['artwork_reference'];
    if (data['plan_id'] != null) return 'plan:${data['plan_id']}';
    if (data['drop_id'] != null) return 'drop:${data['drop_id']}';
    if (record['snapshot'] != null && data['id'] != null) {
      return 'plan:${data['id']}';
    }
    return '';
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
    final copy = auth?['copy_source'] as Map?;
    final isCopy =
        record['_source'] == 'copy_events' ||
        record['_copy'] == true ||
        copy != null;
    final title =
        '${data['collection_name'] ?? data['drop_name'] ?? data['label'] ?? 'Activity record'}';
    final source =
        data['_source_label'] ??
        copy?['source_address'] ??
        data['source_address'];
    final total = BigInt.tryParse('${data['actual_total_cost_wei']}');
    final gasUsed = BigInt.tryParse('${data['actual_gas_used']}');
    final gasPrice = BigInt.tryParse('${data['actual_effective_gas_price']}');
    final gas = gasUsed != null && gasPrice != null ? gasUsed * gasPrice : null;
    final mint = total != null && gas != null && total >= gas
        ? total - gas
        : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CollectionHeader(
          name: title,
          network: '${data['chain'] ?? ''}',
          status: '${data['status'] ?? ''}',
          artwork: CollectionThumbnail(
            name: title,
            reference: _artworkReference(record),
            size: 72,
          ),
        ),
        if (data['chain'] != null)
          Padding(
            padding: const EdgeInsets.only(top: 7, bottom: 10),
            child: Text(
              '${isCopy ? 'Copy mint' : 'Automatic mint'}${source == null ? '' : ' · From ${shortAddress('$source')}'}',
              style: const TextStyle(fontSize: 12),
            ),
          ),
        AppPanel(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Summary',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
              ),
              const Divider(height: 15),
              if (data['quantity'] != null)
                DetailRow(
                  'Quantity',
                  '${data['quantity']} NFT${data['quantity'] == 1 ? '' : 's'}',
                ),
              if (source != null)
                DetailRow('Copied from', shortAddress('$source')),
              if (data['wallet_address'] != null)
                DetailRow(
                  'Receiving wallet',
                  shortAddress('${data['wallet_address']}'),
                ),
              if (data['stage_name'] != null)
                DetailRow('Phase', '${data['stage_name']}'),
              if (data['confirmed_at'] != null)
                DetailRow('Confirmed', _time(data['confirmed_at'])),
              for (final key in ['failure_reason', 'note', 'detail'])
                if (data[key] != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      '${data[key]}',
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
            ],
          ),
        ),
        if (total != null || data['total_cap_eth'] != null)
          AppPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  total != null ? 'Actual spend' : 'Approved limits',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Divider(height: 15),
                if (mint != null)
                  Tooltip(
                    message: '${_eth(mint)} ETH',
                    child: DetailRow(
                      'Mint value',
                      mint == BigInt.zero
                          ? 'Free'
                          : '${compactNative(mint)} ETH',
                    ),
                  ),
                if (gas != null && total != null && total >= gas)
                  Tooltip(
                    message: '${_eth(gas)} ETH',
                    child: DetailRow(
                      'Network fee',
                      '${compactNative(gas)} ETH',
                    ),
                  ),
                if (total != null)
                  DetailRow(
                    'Total spent',
                    '${_eth(total)} ETH',
                    emphasis: true,
                  ),
                if (total == null)
                  DetailRow(
                    'Approved spending cap',
                    '${data['total_cap_eth']} ETH',
                    emphasis: true,
                  ),
                if (total != null && gas == null)
                  const Text(
                    'Includes mint value and charged network fees.',
                    style: TextStyle(fontSize: 10),
                  ),
              ],
            ),
          ),
        if (data['authorized_at'] != null ||
            data['submitted_at'] != null ||
            data['confirmed_at'] != null)
          AppPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Status timeline',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                if (data['authorized_at'] != null)
                  _timeline(
                    'Approved',
                    'Spending authorization recorded.',
                    data['authorized_at'],
                  ),
                if (data['submitted_at'] != null)
                  _timeline(
                    'Submitted',
                    'Transaction submitted to the network.',
                    data['submitted_at'],
                  ),
                if (data['confirmed_at'] != null)
                  _timeline(
                    'Confirmed',
                    'Transaction confirmed on chain.',
                    data['confirmed_at'],
                  ),
              ],
            ),
          ),
        AppPanel(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          child: DisclosureSection(
            tilePadding: EdgeInsets.zero,
            title: const Text(
              'Approval & recovery history',
              style: TextStyle(fontSize: 12),
            ),
            children: [_recordAudit(record)],
          ),
        ),
      ],
    );
  }

  Widget _timeline(String label, String detail, dynamic time) => Padding(
    padding: const EdgeInsets.only(top: 12),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.primary,
            shape: BoxShape.circle,
          ),
          child: const AppGlyph('check', size: 13, color: Color(0xFF102013)),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      label,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  Text(_time(time), style: const TextStyle(fontSize: 10)),
                ],
              ),
              Text(detail, style: const TextStyle(fontSize: 10)),
            ],
          ),
        ),
      ],
    ),
  );

  void _details(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map<String, dynamic>?) ?? record;
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => Scaffold(
          appBar: AppBar(
            title: Text(
              data['chain'] != null ? 'Mint details' : 'Activity details',
            ),
          ),
          bottomNavigationBar: detailsNavigation(context, 3),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _recordDetails(record),
              if (data['explorer_url'] is String &&
                  Uri.tryParse(data['explorer_url'])?.scheme == 'https')
                FilledButton(
                  onPressed: () =>
                      openExternalUrl(context, Uri.parse(data['explorer_url'])),
                  child: const Text('View transaction'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _record(Map<String, dynamic> record) {
    final data = (record['snapshot'] as Map<String, dynamic>?) ?? record;
    final auth = data['authorization'] as Map<String, dynamic>?;
    final isCopy =
        record['_source'] == 'copy_events' ||
        record['_copy'] == true ||
        auth?['copy_source'] != null;
    final isMint = data['chain'] != null;
    final title =
        '${data['collection_name'] ?? data['drop_name'] ?? data['label'] ?? 'Activity record'}';
    final status = '${data['status'] ?? record['event'] ?? ''}';
    final note = data['failure_reason'] ?? data['note'] ?? data['detail'];
    final source = data['_source_label'];
    final spent = data['actual_total_cost_wei'];
    final cap = data['total_cap_eth'];
    final hasCap =
        spent == null &&
        cap != null &&
        [
          'armed',
          'preparing',
          'prepared',
          'submitted',
          'uncertain',
        ].contains(status);
    return AppPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: () => _details(record),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (isMint)
                  CollectionThumbnail(
                    name: title,
                    reference: _artworkReference(record),
                    size: 62,
                  )
                else
                  const AppGlyph('wallet', size: 28),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        children: [
                          Text(
                            title,
                            style: const TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w700,
                              height: 1.15,
                            ),
                          ),
                          if (status.isNotEmpty)
                            StatusBadge(status, compact: true),
                        ],
                      ),
                      const SizedBox(height: 5),
                      if (isMint)
                        Text(
                          '${isCopy ? 'Copy mint' : 'Automatic mint'} · ${'${data['chain']}'.replaceAll(' Chain', '')}',
                          style: const TextStyle(fontSize: 11),
                        ),
                      if (data['quantity'] != null)
                        Text(
                          '${data['quantity']} NFT${data['quantity'] == 1 ? '' : 's'}${source == null ? '' : ' · From $source'}',
                          style: const TextStyle(fontSize: 11),
                        ),
                      if (note != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            '$note',
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 11, height: 1.25),
                          ),
                        ),
                    ],
                  ),
                ),
                const AppGlyph('arrow', size: 15),
              ],
            ),
          ),
          const Divider(height: 15),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (spent != null) ...[
                      const Text('Total spent', style: TextStyle(fontSize: 10)),
                      NativeAmountText(spent, fontSize: 13, bold: true),
                    ],
                    if (hasCap) ...[
                      const Text(
                        'Approved cap',
                        style: TextStyle(fontSize: 10),
                      ),
                      Text(
                        '$cap ETH',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                    if (spent == null && !hasCap)
                      Text(
                        _time(record['recorded_at'] ?? data['created_at']),
                        style: const TextStyle(fontSize: 10),
                      ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  if (spent != null || hasCap)
                    Text(
                      _time(record['recorded_at'] ?? data['created_at']),
                      style: const TextStyle(fontSize: 10),
                    ),
                  TextButton(
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: const Size(0, 26),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    onPressed: () => _details(record),
                    child: const Text(
                      'View details',
                      style: TextStyle(fontSize: 11),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  List<Widget> _groupedRecords() {
    final children = <Widget>[];
    String? last;
    final now = DateTime.now().toUtc().add(const Duration(hours: 1));
    for (final record in _records) {
      final date = _recordDate(record).add(const Duration(hours: 1));
      final day = date.year == 1970
          ? 'HISTORY'
          : DateFormat('d MMM').format(date).toUpperCase();
      if (day != last) {
        children.add(
          Padding(
            padding: const EdgeInsets.only(top: 10, bottom: 7),
            child: Text(
              '${date.year == now.year && date.month == now.month && date.day == now.day ? 'TODAY · ' : ''}$day',
              style: const TextStyle(fontSize: 10, letterSpacing: 1.6),
            ),
          ),
        );
        last = day;
      }
      children.add(_record(record));
    }
    return children;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: widget.embedded ? null : AppBar(title: const Text('Activity')),
    body: RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: [
          if (widget.embedded)
            const ScreenHeading('Activity', 'Your mints, copies and updates.'),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              for (final item in [
                ('all', 'All'),
                ('mints', 'Mints'),
                ('copy_events', 'Copies'),
              ])
                FilterChip(
                  deleteIcon: const SizedBox.shrink(),
                  label: Text(item.$2),
                  selected: _section == item.$1,
                  showCheckmark: false,
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  selectedColor: Theme.of(context).colorScheme.primary,
                  labelStyle: TextStyle(
                    fontSize: 11,
                    color: _section == item.$1
                        ? Theme.of(context).colorScheme.onPrimary
                        : Theme.of(context).colorScheme.onSurface,
                  ),
                  onSelected: (_) {
                    _section = item.$1;
                    _load(reset: true);
                  },
                ),
              SizedBox(
                width: 122,
                child: DropdownButtonFormField<String>(
                  key: ValueKey(_section),
                  initialValue: _section,
                  isExpanded: true,
                  style: const TextStyle(fontSize: 11, fontFamily: 'Roboto'),
                  iconSize: 16,
                  icon: const RotatedBox(
                    quarterTurns: 1,
                    child: AppGlyph('arrow', size: 14),
                  ),
                  decoration: const InputDecoration(
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 9,
                      vertical: 9,
                    ),
                  ),
                  selectedItemBuilder: (_) => [
                    for (final label in [
                      'All records',
                      'Mint records',
                      'Copy records',
                      'Plan history',
                      'Updates',
                      'Permissions',
                      'Copy approvals',
                    ])
                      Text(label, overflow: TextOverflow.ellipsis),
                  ],
                  items: const [
                    DropdownMenuItem(value: 'all', child: Text('All records')),
                    DropdownMenuItem(
                      value: 'mints',
                      child: Text('All mint transactions'),
                    ),
                    DropdownMenuItem(
                      value: 'copy_events',
                      child: Text('Copy events'),
                    ),
                    DropdownMenuItem(
                      value: 'plans',
                      child: Text('Plan history'),
                    ),
                    DropdownMenuItem(
                      value: 'activity',
                      child: Text('Account activity'),
                    ),
                    DropdownMenuItem(
                      value: 'permissions',
                      child: Text('Wallet permissions'),
                    ),
                    DropdownMenuItem(
                      value: 'copies',
                      child: Text('Copy approvals'),
                    ),
                  ],
                  onChanged: (value) {
                    if (value != null) {
                      _section = value;
                      _load(reset: true);
                    }
                  },
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ..._groupedRecords(),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null) Text(_error!),
          if (!_busy && _records.isEmpty && _error == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 25),
              child: Text('No records yet.'),
            ),
          if (!_busy && _next != null)
            TextButton(
              onPressed: () => _load(),
              child: Text(_error == null ? 'Load more' : 'Retry'),
            ),
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text(
              'Removed records stay in history. Pull down to refresh.',
              style: TextStyle(fontSize: 10),
            ),
          ),
        ],
      ),
    ),
  );
}
