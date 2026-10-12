import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'mintly_notice.dart';
import 'screen_components.dart';

class DailyBudgetControl extends ConsumerStatefulWidget {
  const DailyBudgetControl({super.key});
  @override
  ConsumerState<DailyBudgetControl> createState() => _DailyBudgetControlState();
}

class _DailyBudgetControlState extends ConsumerState<DailyBudgetControl> {
  final _amount = TextEditingController();
  late Future<Map<String, dynamic>> _data;
  bool _enabled = false, _busy = false;
  String _currency = 'ETH';
  int _generation = 0;

  String _eth(dynamic value) {
    final wei = BigInt.tryParse('$value') ?? BigInt.zero;
    final scale = BigInt.from(10).pow(18);
    final fraction = (wei % scale)
        .toString()
        .padLeft(18, '0')
        .replaceFirst(RegExp(r'0+$'), '');
    return '${wei ~/ scale}${fraction.isEmpty ? '' : '.$fraction'}';
  }

  @override
  void initState() {
    super.initState();
    _data = _load();
  }

  Future<Map<String, dynamic>> _load() async {
    final generation = ++_generation;
    final data = await ref
        .read(apiServiceProvider)
        .fetchDailyLimit(currency: _currency);
    if (mounted && generation == _generation) {
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
    if (_enabled &&
        (!RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(value) ||
            (double.tryParse(value) ?? 0) <= 0)) {
      MintlyNotice.show(
        context,
        SnackBar(content: Text('Enter a positive $_currency amount.')),
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          _enabled
              ? 'Set daily spending limit?'
              : 'Turn off daily spending limit?',
        ),
        content: Text(
          _enabled
              ? 'This covers $_currency mint prices and gas for both bots and all wallets on networks using $_currency. Other currencies have separate limits. The day resets at midnight WAT. Pending transactions keep counting. Already signed transactions may still finish.'
              : 'Your existing mint and copy limits still apply. Turning this off does not reset spending records.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    try {
      final result = await ref
          .read(apiServiceProvider)
          .setDailyLimit(_enabled ? value : null, currency: _currency);
      if (mounted) {
        setState(() {
          _data = Future.value(result);
        });
        MintlyNotice.show(
          context,
          const SnackBar(content: Text('Daily spending limit saved.')),
        );
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _data = _load();
        });
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
        return ListTile(
          title: const Text('Daily limit unavailable'),
          trailing: TextButton(
            onPressed: () => setState(() {
              _data = _load();
            }),
            child: const Text('Retry'),
          ),
        );
      }
      final data = snapshot.connectionState == ConnectionState.done
          ? snapshot.data
          : null;
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (data != null && (data['currencies'] as List? ?? []).length > 1)
              DropdownButtonFormField<String>(
                initialValue: _currency,
                isExpanded: true,
                icon: const RotatedBox(quarterTurns: 1, child: AppGlyph('arrow', size: 18)),
                decoration: const InputDecoration(
                  labelText: 'Daily limit currency',
                ),
                items: [
                  for (final c in data['currencies'] as List)
                    DropdownMenuItem(value: '$c', child: Text('$c')),
                ],
                onChanged: _busy
                    ? null
                    : (value) => setState(() {
                        _currency = value!;
                        _enabled = false;
                        _amount.clear();
                        _data = _load();
                      }),
              ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Daily spending limit'),
              subtitle: Text('Both bots · all wallets · $_currency networks'),
              value: _enabled,
              onChanged: _busy || data == null
                  ? null
                  : (value) => setState(() => _enabled = value),
            ),
            if (_enabled)
              TextField(
                key: const ValueKey('daily-limit-input'),
                controller: _amount,
                enabled: !_busy,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(
                  labelText: '$_currency per WAT day',
                ),
              ),
            if (data != null && data['limit_wei'] != null) ...[
              const SizedBox(height: 10),
              Text('Spent: ${_eth(data['spent_wei'])} $_currency'),
              Text('Pending maximum: ${_eth(data['reserved_wei'])} $_currency'),
              Text(
                data['remaining_wei'] == null
                    ? 'Remaining budget needs verification.'
                    : 'Available today: ${_eth(data['remaining_wei'])} $_currency',
              ),
            ],
            if (data?['status'] == 'registering')
              const Text(
                'Confirmation pending. Retry Save; new signing is blocked.',
              ),
            TextButton(
              key: const ValueKey('save-daily-limit'),
              onPressed: _busy || data == null ? null : _save,
              child: Text(_busy ? 'Saving…' : 'Save daily limit'),
            ),
          ],
        ),
      );
    },
  );
}
