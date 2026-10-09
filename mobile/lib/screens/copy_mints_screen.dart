import 'dart:async';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';
import '../widgets/mint_progress.dart';
import '../widgets/automation_control.dart';
import '../theme/colors.dart';
import 'automatic_review_screen.dart';
import 'history_screen.dart';
import 'wallet_setup_screen.dart';

// Drawn icons keep this section compatible with installed OTA font subsets.
class CopyGlyph extends StatelessWidget {
  final String kind;
  final double size;
  const CopyGlyph(this.kind, {super.key, this.size = 24});
  @override
  Widget build(BuildContext context) => Semantics(
    label: kind,
    child: CustomPaint(
      size: Size.square(size),
      painter: _GlyphPainter(kind, Theme.of(context).colorScheme.primary),
    ),
  );
}

class _GlyphPainter extends CustomPainter {
  final String kind;
  final Color color;
  _GlyphPainter(this.kind, this.color);
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..strokeCap = StrokeCap.round;
    switch (kind) {
      case 'add':
        canvas.drawLine(const Offset(12, 5), const Offset(12, 19), p);
        canvas.drawLine(const Offset(5, 12), const Offset(19, 12), p);
        break;
      case 'down':
        canvas.drawPath(
          Path()
            ..moveTo(6, 9)
            ..lineTo(12, 15)
            ..lineTo(18, 9),
          p,
        );
        break;
      case 'pause':
        canvas.drawLine(const Offset(8, 5), const Offset(8, 19), p);
        canvas.drawLine(const Offset(16, 5), const Offset(16, 19), p);
      case 'play':
        canvas.drawPath(
          Path()
            ..moveTo(7, 5)
            ..lineTo(19, 12)
            ..lineTo(7, 19)
            ..close(),
          p,
        );
      case 'wallets':
        canvas.drawCircle(const Offset(9, 7), 3, p);
        canvas.drawArc(const Rect.fromLTWH(3, 12, 13, 9), pi, pi, false, p);
        canvas.drawArc(const Rect.fromLTWH(14, 4, 6, 6), -pi / 2, pi, false, p);
        canvas.drawArc(
          const Rect.fromLTWH(16, 12, 5, 8),
          -pi / 2,
          pi,
          false,
          p,
        );
      case 'activity':
        for (var i = 0; i < 3; i++) {
          canvas.drawCircle(Offset(4, 6 + 6.0 * i), .5, p);
          canvas.drawLine(Offset(9, 6 + 6.0 * i), Offset(21, 6 + 6.0 * i), p);
        }
      case 'search':
        canvas.drawCircle(const Offset(10, 10), 6, p);
        canvas.drawLine(const Offset(15, 15), const Offset(21, 21), p);
      case 'more':
        for (var i = 0; i < 3; i++) {
          canvas.drawCircle(Offset(5 + 7.0 * i, 12), .9, p);
        }
      default:
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            const Rect.fromLTWH(8, 8, 12, 13),
            const Radius.circular(2),
          ),
          p,
        );
        canvas.drawPath(
          Path()
            ..moveTo(15, 4)
            ..lineTo(4, 4)
            ..lineTo(4, 16),
          p,
        );
    }
  }

  @override
  bool shouldRepaint(_GlyphPainter old) =>
      old.kind != kind || old.color != color;
}

String copyEth(dynamic wei) {
  final value = BigInt.tryParse('$wei') ?? BigInt.zero;
  final unit = BigInt.from(10).pow(18);
  final fraction = (value % unit)
      .toString()
      .padLeft(18, '0')
      .replaceFirst(RegExp(r'0+$'), '');
  return '${value ~/ unit}${fraction.isEmpty ? '' : '.$fraction'}';
}

String _short(String address) => address.length < 15
    ? address
    : '${address.substring(0, 6)}…${address.substring(address.length - 4)}';
String _network(dynamic id) =>
    {
      1: 'Ethereum',
      8453: 'Base',
      4663: 'Robinhood',
      31337: 'Local test',
      11155111: 'Sepolia',
    }[id] ??
    'Chain $id';
String _date(dynamic value) {
  final date = DateTime.tryParse('$value')?.toLocal();
  if (date == null) return 'Awaiting first check';
  return '${date.day}/${date.month} ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
}

class _Panel extends StatelessWidget {
  final Widget child;
  final bool highlighted;
  const _Panel({required this.child, this.highlighted = false});
  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: highlighted
            ? MintlyColors.getSoft(dark)
            : MintlyColors.getPanel(dark),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: MintlyColors.getLine(dark)),
      ),
      child: Material(type: MaterialType.transparency, child: child),
    );
  }
}

class _Avatar extends StatelessWidget {
  final String name;
  const _Avatar(this.name);
  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      width: 54,
      height: 54,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
          colors: [
            MintlyColors.getSoft(dark),
            MintlyColors.getGreen(dark).withValues(alpha: .25),
          ],
        ),
        border: Border.all(
          color: MintlyColors.getGreen(dark).withValues(alpha: .25),
        ),
      ),
      child: Text(
        name.isEmpty ? '?' : name.substring(0, 1).toUpperCase(),
        style: TextStyle(
          fontSize: 23,
          fontWeight: FontWeight.w700,
          color: MintlyColors.getGreen(dark),
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String text;
  const _Chip(this.text);
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.primary.withValues(alpha: .09),
      borderRadius: BorderRadius.circular(9),
    ),
    child: Text(
      text,
      style: TextStyle(
        fontSize: 12,
        color: Theme.of(context).colorScheme.primary,
        fontWeight: FontWeight.w600,
      ),
    ),
  );
}

class CopyMintsScreen extends ConsumerStatefulWidget {
  const CopyMintsScreen({super.key});
  @override
  ConsumerState<CopyMintsScreen> createState() => _CopyMintsState();
}

class _CopyDetails extends StatefulWidget {
  final Map<String, dynamic> event;
  const _CopyDetails({super.key, required this.event});
  @override
  State<_CopyDetails> createState() => _CopyDetailsState();
}

class _CopyDetailsState extends State<_CopyDetails> {
  bool _open = false;
  @override
  Widget build(BuildContext context) {
    final o = widget.event['observation'] as Map;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextButton(
          onPressed: () => setState(() => _open = !_open),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'Transaction details',
                  style: TextStyle(fontSize: 13),
                ),
              ),
              const CopyGlyph('more', size: 18),
            ],
          ),
        ),
        if (_open) ...[
          const Text('Collection contract'),
          SelectableText('${o['contract']}'),
          const SizedBox(height: 9),
          const Text('Followed wallet mint'),
          SelectableText('${o['source_hash']}'),
          if (widget.event['transaction_hash'] != null) ...[
            const SizedBox(height: 9),
            const Text('Your mint'),
            SelectableText('${widget.event['transaction_hash']}'),
          ],
        ],
      ],
    );
  }
}

class _CopyMintsState extends ConsumerState<CopyMintsScreen> {
  Map<String, dynamic>? _data, _activity;
  List<Map<String, dynamic>> _checks = [];
  final _search = TextEditingController();
  Timer? _timer;
  String? _error, _filter;
  bool _busy = false, _loading = true;
  int _tab = 0;
  int _generation = 0;
  List<Map<String, dynamic>> get _watches =>
      (_data?['watches'] as List? ?? []).cast<Map<String, dynamic>>();
  bool get _active => _watches.any(
    (w) => (w['rules'] as List).any((r) => r['status'] == 'active'),
  );
  bool get _hasApproved => _watches.any(
    (w) => (w['rules'] as List).any(
      (r) => ['active', 'paused'].contains(r['status']),
    ),
  );

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 25), (_) {
      if (!_busy && (ModalRoute.of(context)?.isCurrent ?? false)) {
        _load(silent: true);
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    final generation = ++_generation;
    try {
      final api = ref.read(apiServiceProvider);
      final data = await api.fetchCopyMints();
      if (!mounted || generation != _generation) return;
      final watches = (data['watches'] as List).cast<Map>();
      if (_filter != null && !watches.any((w) => w['id'] == _filter)) {
        _filter = null;
      }
      setState(() {
        _data = data;
        _loading = false;
        _error = null;
      });
      final activity = await api.fetchCopyActivity(watchId: _filter);
      if (mounted && generation == _generation) {
        setState(() => _activity = activity);
      }
      try {
        final checks = await api.fetchCopyCheckResults();
        if (mounted && generation == _generation) {
          setState(() => _checks = (checks['results'] as List? ?? []).cast<Map<String, dynamic>>());
        }
      } catch (_) {
        // Keep the existing activity when check-only results cannot refresh.
      }
    } catch (e) {
      if (mounted && generation == _generation) {
        setState(() {
          _error = '$e';
          _loading = false;
        });
      }
    }
  }

  Future<void> _act(
    Future<void> Function() action, {
    bool refresh = true,
  }) async {
    if (_busy) return;
    _generation++;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
      if (refresh) await _load();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _follow([Map<String, dynamic>? wallet]) async {
    final address = TextEditingController(text: wallet?['address']);
    final name = TextEditingController(text: wallet?['label']);
    final networks = (_data?['networks'] as List? ?? [])
        .cast<Map<String, dynamic>>();
    final chains =
        (wallet?['chains'] as List? ??
                networks.map((n) => n['chain_id']).toList())
            .cast<int>()
            .toSet();
    String? error;
    bool saving = false;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, update) => Padding(
          padding: EdgeInsets.fromLTRB(
            24,
            24,
            24,
            MediaQuery.viewInsetsOf(context).bottom + 24,
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  wallet == null
                      ? 'Follow another wallet'
                      : 'Edit name and networks',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 8),
                const Text(
                  'Monitor public NFT mints. Adding a wallet does not enable spending.',
                ),
                const SizedBox(height: 20),
                TextField(
                  controller: address,
                  enabled: !saving && wallet == null,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Wallet address',
                    hintText: '0x…',
                  ),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: name,
                  enabled: !saving,
                  maxLength: 80,
                  decoration: const InputDecoration(
                    labelText: 'Name this wallet',
                    hintText: 'Your own label',
                  ),
                ),
                const Text('Networks to monitor'),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: networks
                      .map(
                        (n) => FilterChip(
                          deleteIcon: const SizedBox.shrink(),
                          label: Text('${n['name']}'),
                          selected: chains.contains(n['chain_id']),
                          onSelected: saving
                              ? null
                              : (selected) => update(() {
                                  if (selected) {
                                    chains.add(n['chain_id'] as int);
                                  } else {
                                    chains.remove(n['chain_id']);
                                  }
                                }),
                        ),
                      )
                      .toList(),
                ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: saving
                      ? null
                      : () async {
                          if (!RegExp(
                                r'^0x[0-9a-fA-F]{40}$',
                              ).hasMatch(address.text.trim()) ||
                              name.text.trim().isEmpty ||
                              chains.isEmpty) {
                            update(
                              () => error =
                                  'Enter a wallet address, a name and at least one network.',
                            );
                            return;
                          }
                          update(() {
                            saving = true;
                            error = null;
                          });
                          try {
                            await ref
                                .read(apiServiceProvider)
                                .followCopyWallet({
                                  'address': address.text.trim(),
                                  'label': name.text.trim(),
                                  'chains': chains.toList(),
                                });
                            if (sheetContext.mounted) {
                              Navigator.pop(sheetContext);
                            }
                            _search.clear();
                            _filter = null;
                            await _load();
                          } catch (e) {
                            if (sheetContext.mounted) {
                              update(() {
                                saving = false;
                                error = '$e';
                              });
                            }
                          }
                        },
                  child: Text(
                    saving
                        ? 'Saving…'
                        : wallet == null
                        ? 'Follow wallet'
                        : 'Save changes',
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    // Let the dismissed sheet finish its exit animation before disposing fields.
    await Future<void>.delayed(const Duration(milliseconds: 300));
    address.dispose();
    name.dispose();
  }

  Future<void> _remove(Map<String, dynamic> watch) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Stop following ${watch['label']}?'),
        content: const Text(
          'Unsigned copies will stop. Signed transactions remain tracked, and all records stay in History.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep wallet'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (ok == true) {
      await _act(
        () => ref.read(apiServiceProvider).removeCopyWallet('${watch['id']}'),
      );
    }
  }

  Future<void> _setup(Map<String, dynamic> watch) async {
    await Navigator.push(
      context,
      MaterialPageRoute<void>(builder: (_) => CopySettingsScreen(watch: watch)),
    );
    await _load();
  }

  Widget _watch(Map<String, dynamic> watch) {
    final rules = (watch['rules'] as List).cast<Map<String, dynamic>>();
    final active = rules.any((r) => r['status'] == 'active');
    final cursors = (watch['cursors'] as Map).values.cast<Map>();
    final unavailable = cursors.any((c) => c['status'] == 'unavailable');
    final checked =
        cursors
            .map((c) => '${c['checked_at'] ?? ''}')
            .where((s) => s.isNotEmpty)
            .toList()
          ..sort();
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _Avatar('${watch['label']}'),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${watch['label']}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    InkWell(
                      onTap: () => Clipboard.setData(
                        ClipboardData(text: '${watch['address']}'),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 5),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(_short('${watch['address']}')),
                            const SizedBox(width: 8),
                            const CopyGlyph('copy', size: 15),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                tooltip: 'Wallet options',
                icon: const CopyGlyph('more'),
                onSelected: (value) {
                  if (value == 'stop-checks') {
                    _act(() => ref.read(apiServiceProvider).stopCopyChecks('${watch['id']}'));
                  }
                  if (value == 'edit') _follow(watch);
                  if (value == 'remove') _remove(watch);
                  if (value == 'pause') {
                    _act(
                      () => ref
                          .read(apiServiceProvider)
                          .pauseCopying(active, watchId: '${watch['id']}'),
                    );
                  }
                },
                itemBuilder: (_) => [
                  if (watch['check_only'] == true)
                    const PopupMenuItem(value: 'stop-checks', child: Text('Stop check-only')) ,
                  const PopupMenuItem(
                    value: 'edit',
                    child: Text('Edit name / networks'),
                  ),
                  if (rules.any(
                    (r) => ['active', 'paused'].contains(r['status']),
                  ))
                    PopupMenuItem(
                      value: 'pause',
                      child: Text(active ? 'Pause copying' : 'Resume copying'),
                    ),
                  const PopupMenuItem(
                    value: 'remove',
                    child: Text('Remove wallet'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              for (final chain in watch['chains'] as List)
                _Chip(_network(chain)),
              _Chip(watch['check_only'] == true ? 'Check-only · no spending' : active ? 'Copying on' : 'Watching only'),
            ],
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Recent public mints',
                      style: TextStyle(fontSize: 12),
                    ),
                    Text(
                      '${watch['recent_mints']}',
                      style: const TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              FilledButton(
                onPressed: _busy ? null : () => _setup(watch),
                child: Text(watch['check_only'] == true ? 'Manage checks' : active ? 'Copying active · Manage' : rules.any((r) => r['status'] == 'paused') ? 'Copying paused · Manage' : 'Set up copy'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            unavailable
                ? 'Network check delayed. Last saved activity is preserved.'
                : checked.isEmpty
                ? 'Scanning recent blocks…'
                : 'Checked ${_date(checked.first)} · last 7 days, scanned blocks',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          TextButton(
            onPressed: () {
              setState(() {
                _tab = 1;
                _filter = '${watch['id']}';
              });
              _load();
            },
            child: const Text('View activity'),
          ),
        ],
      ),
    );
  }

  Widget _following() {
    final search = _search.text.trim().toLowerCase();
    final watches = _watches
        .where(
          (w) => '${w['label']} ${w['address']}'.toLowerCase().contains(search),
        )
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const AutomationControl(),
        Text(
          'Copy minting',
          style: Theme.of(
            context,
          ).textTheme.headlineLarge?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 7),
        const Text('Follow wallets. Mint on your terms.'),
        const SizedBox(height: 22),
        _Panel(
          highlighted: true,
          child: Row(
            children: [
              const CopyGlyph('wallets', size: 32),
              const SizedBox(width: 15),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${_watches.length} wallet${_watches.length == 1 ? '' : 's'} followed',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 16,
                      ),
                    ),
                    Text(
                      _active
                          ? 'Automatic copying active'
                          : 'Auto-copy paused / not enabled',
                    ),
                  ],
                ),
              ),
              if (_hasApproved)
                IconButton(
                  tooltip: _active
                      ? 'Pause all copying'
                      : 'Resume approved copying',
                  onPressed: _busy
                      ? null
                      : () => _act(
                          () => ref
                              .read(apiServiceProvider)
                              .pauseCopying(_active),
                        ),
                  icon: CopyGlyph(_active ? 'pause' : 'play'),
                ),
            ],
          ),
        ),
        TextField(
          controller: _search,
          onChanged: (_) => setState(() {}),
          decoration: const InputDecoration(
            hintText: 'Search followed wallets',
            prefixIcon: Padding(
              padding: EdgeInsets.all(14),
              child: CopyGlyph('search', size: 20),
            ),
          ),
        ),
        const SizedBox(height: 22),
        Row(
          children: [
            const Expanded(
              child: Text(
                'Followed wallets',
                style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
              ),
            ),
            Text('${watches.length} wallets'),
          ],
        ),
        const SizedBox(height: 14),
        if (_watches.isEmpty)
          const _Panel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                CopyGlyph('wallets', size: 36),
                SizedBox(height: 16),
                Text(
                  'Find your next mint through wallets you follow.',
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
                SizedBox(height: 8),
                Text(
                  'Add an address and give it a name. Review recent public mints, then choose a receiving wallet and limits to enable copying.',
                ),
              ],
            ),
          ),
        if (_watches.isNotEmpty && watches.isEmpty)
          const Padding(
            padding: EdgeInsets.all(20),
            child: Text('No followed wallets match this search.'),
          ),
        for (final watch in watches)
          KeyedSubtree(
            key: ValueKey('copy-watch-${watch['id']}'),
            child: _watch(watch),
          ),
        FilledButton.icon(
          onPressed: _busy || _data?['enabled'] != true
              ? null
              : () => _follow(),
          icon: const Text('+', style: TextStyle(fontSize: 24)),
          label: Text(
            _watches.isEmpty ? 'Follow wallet' : 'Follow another wallet',
          ),
        ),
        const SizedBox(height: 18),
        const Text(
          'Public mints and opted-in whitelist mints on Ethereum, Base and Robinhood. Unsupported mint methods, transfers and airdrops are skipped.',
          style: TextStyle(fontSize: 12),
        ),
      ],
    );
  }

  Future<void> _copy(Map<String, dynamic> event) async {
    await _act(() async {
      final data = await ref
          .read(apiServiceProvider)
          .copyMintContext('${event['id']}');
      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute<void>(
          builder: (_) => AutomaticReviewScreen(
            drop: DropModel.fromJson(data['drop'] as Map<String, dynamic>),
            copyEventId: '${event['id']}',
          ),
        ),
      );
    });
  }

  Widget _event(Map<String, dynamic> event) {
    final o = event['observation'] as Map<String, dynamic>;
    final status = '${event['status']}';
    final label =
        {
          'confirmed': 'Mint confirmed',
          'submitted': 'Submitted',
          'uncertain': 'Tracking transaction',
          'armed': 'Queued',
          'prepared': 'Signed',
          'detected': 'Public mint detected',
          'skipped': 'Skipped',
          'disarmed': 'Stopped',
        }[status] ??
        status;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Avatar('${o['name']}'),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${o['name']}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 17,
                      ),
                    ),
                    const SizedBox(height: 7),
                    Wrap(
                      spacing: 7,
                      runSpacing: 7,
                      children: [_Chip(label), _Chip('${o['chain']}'),
                        _Chip(o['mint_kind'] == 'allowlist' || o['mint_kind'] == 'signed' ? 'Whitelist' : 'Public')],
                    ),
                    const SizedBox(height: 9),
                    Text('Followed ${event['wallet_label']}'),
                    Text(
                      event['quantity'] == null
                          ? '${o['source_quantity']} NFT(s) minted by followed wallet'
                          : '${event['quantity']} NFT(s) copied',
                    ),
                    Text(
                      event['actual_cost_wei'] == null
                          ? 'Source price ${copyEth(o['price_wei'])} ETH / NFT'
                          : '${copyEth(event['actual_cost_wei'])} ETH spent',
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            _date(event['observed_at']),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (event['progress'] is Map<String, dynamic>) ...[
            MintProgress(progress: event['progress'] as Map<String, dynamic>),
            const SizedBox(height: 8),
          ],
          if (event['note'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                '${event['note']}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          const SizedBox(height: 8),
          _CopyDetails(key: ValueKey(event['id']), event: event),
          if (event['retryable'] == true)
            OutlinedButton(
              onPressed: _busy ? null : () => _act(() => ref.read(apiServiceProvider).retryCopyMint('${event['id']}')),
              child: const Text('Retry'),
            )
          else if (event['task_id'] == null && (o['mint_kind'] == 'allowlist' || o['mint_kind'] == 'signed'))
            OutlinedButton(
              onPressed: _busy || !_watches.any((w) => w['id'] == event['watch_id'])
                  ? null : () => _setup(_watches.firstWhere((w) => w['id'] == event['watch_id'])),
              child: const Text('Whitelist settings'),
            )
          else if (event['task_id'] == null)
            OutlinedButton(
              onPressed: _busy ? null : () => _copy(event),
              child: const Text('Review & copy this mint'),
            ),
        ],
      ),
    );
  }

  Widget _activities() {
    final events = (_activity?['events'] as List? ?? [])
        .cast<Map<String, dynamic>>();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Copy activity',
          style: Theme.of(
            context,
          ).textTheme.headlineLarge?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 7),
        const Text('Public mints and updates for your copied wallets.'),
        const SizedBox(height: 22),
        Row(
          children: [
            Expanded(
              child: _Panel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${_activity?['copied_mints'] ?? 0}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 25,
                      ),
                    ),
                    const Text('copied mints'),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _Panel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      copyEth(_activity?['spent_wei'] ?? '0'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 20,
                      ),
                    ),
                    const Text('ETH spent · all fees'),
                  ],
                ),
              ),
            ),
          ],
        ),
        DropdownButtonFormField<String>(
          icon: const CopyGlyph('down'),
          key: ValueKey(_filter),
          initialValue: _filter,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Activity for'),
          items: [
            const DropdownMenuItem<String>(
              value: null,
              child: Text(
                'All followed wallets',
                overflow: TextOverflow.ellipsis,
              ),
            ),
            for (final w in _watches)
              DropdownMenuItem(
                value: '${w['id']}',
                child: Text('${w['label']}', overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: (value) {
            setState(() {
              _filter = value;
              _activity = null;
            });
            _load();
          },
        ),
        const SizedBox(height: 20),
        if (events.isEmpty)
          const _Panel(
            child: Padding(
              padding: EdgeInsets.symmetric(vertical: 18),
              child: Text(
                  'No supported mints detected yet. New activity appears after network confirmation.',
              ),
            ),
          ),
        if (_checks.any((c) => _filter == null || c['watch_id'] == _filter)) ...[
          const Text('Check-only results', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          for (final check in _checks.where((c) => _filter == null || c['watch_id'] == _filter))
            _Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${(check['observation'] as Map)['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(check['status'] == 'would_copy' ? 'Would copy' : check['status'] == 'would_skip' ? 'Would skip' : 'Not verified'),
              Text('${check['note']}'),
              const Text('No transaction sent.'),
            ])),
        ],
        ...events.map(_event),
        if (_activity?['next_offset'] != null)
          OutlinedButton(
            onPressed: _busy
                ? null
                : () => _act(() async {
                    final next = await ref
                        .read(apiServiceProvider)
                        .fetchCopyActivity(
                          watchId: _filter,
                          offset: _activity!['next_offset'] as int,
                        );
                    if (mounted) {
                      setState(() {
                        _activity = {
                          ...next,
                          'events': [
                            ...events,
                            ...(next['events'] as List).where(
                              (e) => !events.any((old) => old['id'] == e['id']),
                            ),
                          ],
                        };
                      });
                    }
                  }, refresh: false),
            child: const Text('Load more activity'),
          ),
        if (_active)
          OutlinedButton.icon(
            onPressed: _busy
                ? null
                : () => _act(
                    () => ref.read(apiServiceProvider).pauseCopying(true),
                  ),
            icon: const CopyGlyph('pause'),
            label: const Text('Pause copying'),
          ),
        TextButton(
          onPressed: () => Navigator.push(
            context,
            MaterialPageRoute<void>(builder: (_) => const HistoryScreen()),
          ),
          child: const Text('Open full History'),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      actions: [
        IconButton(
          tooltip: 'Follow another wallet',
          icon: const CopyGlyph('add'),
          onPressed: _busy || _data == null ? null : () => _follow(),
        ),
        Padding(
          padding: const EdgeInsets.only(right: 18),
          child: Center(
            child: _Chip(_active ? 'Copying on' : 'Copying paused'),
          ),
        ),
      ],
    ),
    body: RefreshIndicator(
      onRefresh: _load,
      child: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(20, 14, 20, 28),
              children: [
                if (_error != null)
                  _Panel(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_error!),
                        TextButton(
                          onPressed: _load,
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  ),
                if (_data?['enabled'] == false)
                  const _Panel(
                    child: Text(
                      'Copy mints is awaiting server activation. Your existing mint plans continue normally.',
                    ),
                  ),
                if (_tab == 0) _following() else _activities(),
              ],
            ),
    ),
    bottomNavigationBar: SafeArea(
      top: false,
      child: Container(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(color: Theme.of(context).dividerColor),
          ),
        ),
        child: Row(
          children: [
            for (final (index, name, glyph) in [
              (0, 'Following', 'copy'),
              (1, 'Activity', 'activity'),
            ])
              Expanded(
                child: TextButton(
                  onPressed: () {
                    setState(() {
                      _tab = index;
                      if (index == 1) _filter = null;
                    });
                    if (index == 1) _load();
                  },
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        CopyGlyph(glyph),
                        const SizedBox(height: 5),
                        Text(
                          name,
                          style: TextStyle(
                            fontWeight: _tab == index
                                ? FontWeight.w700
                                : FontWeight.w400,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    ),
  );
}

class CopySettingsScreen extends ConsumerStatefulWidget {
  final Map<String, dynamic> watch;
  const CopySettingsScreen({super.key, required this.watch});
  @override
  ConsumerState<CopySettingsScreen> createState() => _CopySettingsState();
}

class _CopySettingsState extends ConsumerState<CopySettingsScreen> {
  final _form = GlobalKey<FormState>();
  final _quantity = TextEditingController(text: '1'),
      _price = TextEditingController(),
      _gas = TextEditingController(),
      _budget = TextEditingController();
  late Future<List<Map<String, dynamic>>> _policies;
  Map<String, dynamic>? _policy, _pending;
  DateTime? _expiry;
  bool _free = false, _consent = false, _busy = false;
  bool _includePresales = true, _checkOnly = false;
  String _quantityChoice = 'one';
  int _days = 7;
  String? _error;

  @override
  void initState() {
    super.initState();
    _checkOnly = widget.watch['check_only'] == true;
    _policies = _loadPolicies();
  }

  Future<List<Map<String, dynamic>>> _loadPolicies() async {
    final all = await ref.read(apiServiceProvider).fetchAutomaticPolicies();
    final wallets = <String, Map<String, dynamic>>{};
    try {
      for (final wallet in await ref.read(apiServiceProvider).fetchWallets()) {
        if ('${wallet['address']}'.toLowerCase() != '${widget.watch['address']}'.toLowerCase()) {
          wallets['${wallet['id']}'] = {
            'id': wallet['id'], 'account': wallet['address'], 'label': wallet['label'] ?? 'Wallet',
            'policies': <Map<String, dynamic>>[],
          };
        }
      }
    } catch (_) {
      // Owner-scoped policy metadata still identifies approved receiving wallets.
    }
    for (final policy in all) {
      if (policy['status'] != 'enabled' || '${policy['account']}'.toLowerCase() == '${widget.watch['address']}'.toLowerCase()
          || !((policy['scope'] as Map)['mint_kinds'] as List).contains('public')) {
        continue;
      }
      final wallet = wallets.putIfAbsent('${policy['wallet_id']}', () => {
        'id': policy['wallet_id'], 'account': policy['account'], 'label': 'Wallet',
        'policies': <Map<String, dynamic>>[],
      });
      final policies = wallet['policies'] as List<Map<String, dynamic>>;
      final index = policies.indexWhere((p) => p['chain_id'] == policy['chain_id']);
      if (index < 0) {
        policies.add(policy);
      } else if (DateTime.parse('${policy['expires_at']}').isAfter(DateTime.parse('${policies[index]['expires_at']}'))) {
        policies[index] = policy;
      }
    }
    return wallets.values.toList();
  }

  @override
  void dispose() {
    for (final field in [_quantity, _price, _gas, _budget]) {
      field.dispose();
    }
    super.dispose();
  }

  bool get _needsSigningApproval => !_checkOnly && (_policy == null || (_policy!['policies'] as List).isEmpty || (_policy!['policies'] as List).any((p) => !{'public','allowlist','signed'}.every((kind) => ((p['scope'] as Map)['mint_kinds'] as List).contains(kind))));

  Future<void> _setupWallet() async {
    final selected = _policy;
    await Navigator.push(context,MaterialPageRoute(builder: (_) => WalletSetupScreen(walletId:selected?['id'] as String?,address:selected?['account'] as String?)));
    if (!mounted) return;
    final future = _loadPolicies();
    setState(() { _policies = future; _policy = null; _consent = false; });
    final wallets = await future;
    if (!mounted || selected == null) return;
    final match = wallets.where((wallet) => wallet['id'] == selected['id']).firstOrNull;
    if (match != null) setState(() { _policy = match; _setExpiry(); });
  }

  void _setExpiry() {
    final policies = _policy!['policies'] as List<Map<String, dynamic>>;
    if (_checkOnly || policies.isEmpty) {
      _expiry = DateTime.now().toUtc().add(Duration(days: _days));
      return;
    }
    final policyExpiry = policies.map((p) => DateTime.parse('${p['expires_at']}').toUtc())
        .reduce((a, b) => a.isBefore(b) ? a : b);
    final expiry = DateTime.now().toUtc().add(Duration(days: _days));
    _expiry = expiry.isBefore(policyExpiry) ? expiry : policyExpiry;
  }

  String? _amount(String? text) =>
      text == null || !RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(text.trim())
      ? 'Enter an exact ETH amount (up to 18 decimals).'
      : null;
  String _uuid() {
    final random = Random.secure();
    final bytes = List.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final h = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
  }

  Future<void> _enable() async {
    if (_busy ||
        _policy == null ||
        !_consent ||
        !_form.currentState!.validate()) {
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    _pending ??= {
      'request_id': _uuid(),
      if (_checkOnly) 'wallet_id': _policy!['id'],
      if (!_checkOnly) 'grant_ids': [for (final p in _policy!['policies'] as List<Map<String, dynamic>>) p['id']],
      'quantity': _free || _quantityChoice == 'max' ? 100 : int.parse(_quantity.text.trim()),
      'quantity_mode': _free ? 'max_free' : _quantityChoice == 'max' ? 'max_available' : 'fixed',
      'price_cap_eth': _price.text.trim(),
      'fee_cap_eth': _gas.text.trim(),
      'budget_eth': _budget.text.trim(),
      'free_only': _free,
      'include_presales': _includePresales,
      'expires_at': _expiry!.toIso8601String(),
      if (!_checkOnly) 'consent': true,
    };
    try {
      if (_checkOnly) {
        await ref.read(apiServiceProvider).startCopyChecks('${widget.watch['id']}', _pending!);
        if (mounted) Navigator.pop(context);
        return;
      }
      final result = await ref
          .read(apiServiceProvider)
          .approveWalletCopyRules('${widget.watch['id']}', _pending!);
      if (mounted) {
        if (result['status'] == 'active') {
          Navigator.pop(context);
        } else {
          setState(
            () => _error =
                'This approval is ${result['status']}. Open a new review to enable copying.',
          );
        }
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final locked = _busy || _pending != null;
    return Scaffold(
      appBar: AppBar(title: const Text('Copy settings')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _policies,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Padding(
              padding: const EdgeInsets.all(24),
              child: Text('${snapshot.error}'),
            );
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final policies = snapshot.data!;
          return Form(
            key: _form,
            child: ListView(
              key: const ValueKey('copy-settings-scroll'),
              padding: const EdgeInsets.all(20),
              children: [
                _Panel(
                  child: Row(
                    children: [
                      _Avatar('${widget.watch['label']}'),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${widget.watch['label']}',
                              style: const TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(height: 5),
                            Text(_short('${widget.watch['address']}')),
                            const SizedBox(height: 9),
                            Wrap(
                              spacing: 6,
                              runSpacing: 6,
                              children: [
                                for (final c in widget.watch['chains'] as List)
                                  _Chip(_network(c)),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  _checkOnly ? 'Choose check-only limits' : 'Choose your limits',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 7),
                const SizedBox(height: 18),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero, title: const Text('Check-only mode'),
                  subtitle: const Text('Preview new mints without signing or spending.'), value: _checkOnly,
                  onChanged: locked ? null : (value) => setState(() {
                    _checkOnly = value; _policy = null; _consent = false;
                  }),
                ),
                if (policies.isEmpty)
                  Column(children:[const _Panel(child:Text('Add a receiving wallet to continue.')),OutlinedButton(onPressed:locked ? null : _setupWallet,child:const Text('Set up wallet'))]),
                if (policies.isNotEmpty) ...[
                  DropdownButtonFormField<String>(
                    icon: const CopyGlyph('down'),
                    decoration: const InputDecoration(
                      labelText: 'Receiving wallet',
                    ),
                    isExpanded: true,
                    items: policies
                        .map(
                          (p) => DropdownMenuItem(
                            value: '${p['id']}',
                            child: Text(
                              '${p['label']} · ${_short('${p['account']}')}',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: locked
                        ? null
                        : (id) => setState(() {
                            _policy = policies.firstWhere((p) => p['id'] == id);
                            _includePresales = true;
                            _consent = false;
                            _setExpiry();
                          }),
                    validator: (_) =>
                        _policy == null ? 'Choose a receiving wallet.' : null,
                  ),
                  if (_policy != null) ...[
                    const SizedBox(height: 12),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      for (final chain in [1, 4663, 8453])
                        _Chip(((_policy!['policies'] as List).any((p) => p['chain_id'] == chain))
                            ? _network(chain) : '${_network(chain)} · ${_checkOnly ? 'Check only' : 'Not approved'}'),
                    ]),
                    const SizedBox(height: 8),
                    if (_needsSigningApproval) ...[
                      const Text('This wallet needs approval for public and eligible whitelist signing.'),
                      OutlinedButton(onPressed:locked ? null : _setupWallet,child:const Text('Set up wallet')),
                    ],
                    Text(_checkOnly ? 'Results are checks only. No transaction will be sent.' : 'Copies on the mint’s network. Add ETH there for gas.',
                        style: TextStyle(fontSize: 12)),
                  ],
                  const SizedBox(height: 18),
                  const Text('Which mints should Mintly copy?',style:TextStyle(fontWeight:FontWeight.w700)),
                  const SizedBox(height:8),
                  Wrap(spacing:8,runSpacing:8,children:[
                    for (final choice in [(true,'Free mints only'),(false,'Public / whitelist mints')])
                      OutlinedButton(onPressed:locked ? null : () => setState(() {
                        _free = choice.$1; _consent = false;
                        if (_free) _price.text = '0';
                      }),style:OutlinedButton.styleFrom(backgroundColor:_free == choice.$1 ? Theme.of(context).colorScheme.primary.withValues(alpha:.12) : null),child:Text(choice.$2)),
                  ]),
                  const Text('Public and eligible whitelist stages. Network fees still apply.',style:TextStyle(fontSize:12)),
                  const SizedBox(height:14),
                  if (_free) const _Panel(child:Text('Free mints use the maximum available for your wallet, within your limits (up to 100 NFTs).'))
                  else _Panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
                    const Text('NFT quantity'),
                    Wrap(spacing:8,runSpacing:8,children:[
                      for (final choice in [('one','1 NFT'),('max','Max mint'),('custom','Custom')])
                        OutlinedButton(onPressed:locked ? null : () => setState(() {
                          _quantityChoice = choice.$1; _consent = false;
                          if (_quantityChoice == 'one') _quantity.text = '1';
                        }),style:OutlinedButton.styleFrom(backgroundColor:_quantityChoice == choice.$1 ? Theme.of(context).colorScheme.primary.withValues(alpha:.12) : null),child:Text(choice.$2)),
                    ]),
                    if (_quantityChoice == 'custom') TextFormField(controller:_quantity,enabled:!locked,
                      keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Custom NFT quantity'),
                      validator:(value) => (int.tryParse(value ?? '') ?? 0) < 1 || (int.tryParse(value ?? '') ?? 101) > 100 ? 'Choose 1 to 100 NFTs' : null),
                    if (_quantityChoice == 'max') const Text('Remaining wallet allowance and collection supply, within your spending limits. Up to 100 NFTs.'),
                  ])),
                  _Panel(
                    child: Column(
                      children: [
                        TextFormField(
                          controller: _price,
                          enabled: !locked && !_free,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          validator: _amount,
                          decoration: const InputDecoration(
                            labelText: 'Max mint price per NFT',
                            suffixText: 'ETH',
                          ),
                        ),
                        const SizedBox(height: 15),
                        TextFormField(
                          controller: _gas,
                          enabled: !locked,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          validator: _amount,
                          decoration: const InputDecoration(
                            labelText: 'Gas spending limit',
                            suffixText: 'ETH',
                            helperText: 'Maximum fee for one copied mint',
                          ),
                        ),
                        const SizedBox(height: 15),
                        TextFormField(
                          controller: _budget,
                          enabled: !locked,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          validator: _amount,
                          decoration: const InputDecoration(
                            labelText: 'Total copy budget',
                            suffixText: 'ETH',
                            helperText: 'Shared across networks · includes mint prices and gas',
                          ),
                        ),
                        DropdownButtonFormField<int>(
                          icon: const CopyGlyph('down'),
                          initialValue: _days,
                          decoration: const InputDecoration(
                            labelText: 'Copy permission duration',
                          ),
                          items: [
                            for (final d in [1, 3, 7, 14, 30])
                              DropdownMenuItem(
                                value: d,
                                child: Text('Up to $d day${d == 1 ? '' : 's'}'),
                              ),
                          ],
                          onChanged: locked
                              ? null
                              : (d) => setState(() {
                                  _days = d!;
                                  if (_policy != null) _setExpiry();
                                }),
                        ),
                        if (_expiry != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 12),
                            child: Text(
                              'Ends ${_date(_expiry!.toIso8601String())} · within your wallet policy',
                            ),
                          ),
                      ],
                    ),
                  ),
                  _Panel(
                    highlighted: true,
                    child: Text(
                      _checkOnly ? 'Check-only sends no new transactions. Already signed transactions from earlier copying may still finish.' : 'Network fees apply. Mints outside your limits are skipped. Already signed transactions may still finish after pausing or unlinking.'
                      '${(_policy?['policies'] as List? ?? []).any((p) => p['chain_id'] == 8453) ? ' Base fees can change until inclusion.' : ''}',
                    ),
                  ),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _consent,
                    onChanged: locked
                        ? null
                        : (v) => setState(() => _consent = v == true),
                    title: Text(
                      _checkOnly
                          ? 'Start check-only monitoring with these limits. No spending approval is given.'
                          : _free
                          ? 'Approve maximum free public and eligible whitelist minting (up to 100 NFTs), including gas within these limits.'
                          : 'Approve public and eligible whitelist copying${_quantityChoice == 'max' ? ' at the maximum available quantity (up to 100 NFTs)' : ' at my selected quantity'}, including gas within these limits.',
                    ),
                  ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        _error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  FilledButton(
                    onPressed: _busy || !_consent || _policy == null || _needsSigningApproval
                        ? null
                        : _enable,
                    child: Text(
                      _busy
                          ? (_checkOnly ? 'Starting checks…' : 'Confirming copy permission…')
                          : _pending != null
                          ? 'Retry saved approval'
                          : _checkOnly ? 'Start check-only' : 'Enable copy minting',
                    ),
                  ),
                ],
              ],
            ),
          );
        },
      ),
    );
  }
}
