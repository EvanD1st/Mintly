import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'mintly_notice.dart';

class AutomationControl extends ConsumerStatefulWidget {
  const AutomationControl({super.key});
  @override
  ConsumerState<AutomationControl> createState() => _AutomationControlState();
}

class _AutomationControlState extends ConsumerState<AutomationControl> {
  late Future<Map<String, dynamic>> _status;
  bool _busy = false;
  @override
  void initState() {
    super.initState();
    _status = ref.read(apiServiceProvider).fetchAutomationStatus();
  }

  Future<void> _change(bool paused) async {
    final confirmed = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: Text(paused ? 'Pause all automation?' : 'Allow automation again?'),
      content: Text(paused
        ? 'This pauses copying and stops scheduled mints for your account. Transactions already signed may still finish. Your history is kept.'
        : 'Paused copy rules and mint plans stay paused. Enable copying or review a plan when you are ready.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(context, true), child: Text(paused ? 'Pause all' : 'Continue')),
      ],
    ));
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    try {
      final status = await ref.read(apiServiceProvider).setAutomationPaused(paused);
      if (mounted) {
        setState(() => _status = Future.value(status));
        MintlyNotice.show(context, SnackBar(content: Text(paused ? 'All automation paused.' : 'Automation available. Review your paused actions.')));
      }
      await ref.read(mintlyProvider.notifier).loadInitialData();
    } catch (error) {
      if (mounted) {
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
    future: _status,
    builder: (context, snapshot) {
      if (snapshot.hasError) return ListTile(
        title: const Text('Automation status unavailable'),
        trailing: TextButton(onPressed: () => setState(() => _status = ref.read(apiServiceProvider).fetchAutomationStatus()), child: const Text('Retry')),
      );
      final paused = snapshot.data?['paused'] == true;
      return ListTile(
        title: Text(paused ? 'All automation paused' : 'Automatic minting & copying', style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(paused ? 'Enable actions separately after resuming.' : 'Stop both bots for your account.'),
        trailing: TextButton(key: const ValueKey('pause-all-automation'),
          onPressed: snapshot.hasData && !_busy ? () => _change(!paused) : null,
          child: Text(_busy ? 'Saving…' : paused ? 'Resume' : 'Pause all')),
      );
    },
  );
}
