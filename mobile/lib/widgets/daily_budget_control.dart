import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'mintly_notice.dart';

class DailyBudgetControl extends ConsumerStatefulWidget {
  const DailyBudgetControl({super.key});
  @override
  ConsumerState<DailyBudgetControl> createState() => _DailyBudgetControlState();
}

class _DailyBudgetControlState extends ConsumerState<DailyBudgetControl> {
  final _amount = TextEditingController();
  late Future<Map<String, dynamic>> _data;
  bool _enabled = false, _busy = false;

  String _eth(dynamic value) {
    final wei = BigInt.tryParse('$value') ?? BigInt.zero;
    final scale = BigInt.from(10).pow(18);
    final fraction = (wei % scale).toString().padLeft(18, '0').replaceFirst(RegExp(r'0+$'), '');
    return '${wei ~/ scale}${fraction.isEmpty ? '' : '.$fraction'}';
  }

  @override
  void initState() {
    super.initState();
    _data = _load();
  }

  Future<Map<String, dynamic>> _load() async {
    final data = await ref.read(apiServiceProvider).fetchDailyLimit();
    if (mounted) {
      _enabled = data['limit_wei'] != null;
      _amount.text = _enabled ? _eth(data['limit_wei']) : '';
    }
    return data;
  }

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final value = _amount.text.trim();
    if (_enabled && (!RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(value) || (double.tryParse(value) ?? 0) <= 0)) {
      MintlyNotice.show(context, const SnackBar(content: Text('Enter a positive ETH amount.')));
      return;
    }
    final confirmed = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: Text(_enabled ? 'Set daily spending limit?' : 'Turn off daily spending limit?'),
      content: Text(_enabled
        ? 'This covers mint prices and gas for both bots, all wallets and all networks. The day resets at midnight WAT. Pending transactions keep counting. Already signed transactions may still finish.'
        : 'Your existing mint and copy limits still apply. Turning this off does not reset spending records.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
      ],
    ));
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    try {
      final result = await ref.read(apiServiceProvider).setDailyLimit(_enabled ? value : null);
      if (mounted) {
        setState(() => _data = Future.value(result));
        MintlyNotice.show(context, const SnackBar(content: Text('Daily spending limit saved.')));
      }
    } catch (error) {
      if (mounted) {
        setState(() => _data = _load());
        MintlyNotice.show(context, SnackBar(content: Text('$error')));
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
    future: _data,
    builder: (context, snapshot) {
      if (snapshot.hasError) {
        return ListTile(title: const Text('Daily limit unavailable'), trailing: TextButton(
          onPressed: () => setState(() => _data = _load()), child: const Text('Retry')));
      }
      final data = snapshot.data;
      return Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Daily spending limit'),
            subtitle: const Text('Both bots · all wallets · all networks'), value: _enabled,
            onChanged: _busy || data == null ? null : (value) => setState(() => _enabled = value)),
          if (_enabled) TextField(key: const ValueKey('daily-limit-input'), controller: _amount,
            enabled: !_busy, keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'ETH per WAT day')),
          if (data != null && data['limit_wei'] != null) ...[
            const SizedBox(height: 10),
            Text('Spent: ${_eth(data['spent_wei'])} ETH'),
            Text('Pending maximum: ${_eth(data['reserved_wei'])} ETH'),
            Text(data['remaining_wei'] == null ? 'Remaining budget needs verification.' : 'Available today: ${_eth(data['remaining_wei'])} ETH'),
          ],
          if (data?['status'] == 'registering') const Text('Confirmation pending. Retry Save; new signing is blocked.'),
          TextButton(key: const ValueKey('save-daily-limit'), onPressed: _busy || data == null ? null : _save,
            child: Text(_busy ? 'Saving…' : 'Save daily limit')),
        ],
      ));
    },
  );
}
