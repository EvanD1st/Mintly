import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../widgets/mintly_notice.dart';
import '../services/push_service.dart';

class SavedAccountsScreen extends ConsumerStatefulWidget {
  const SavedAccountsScreen({super.key});
  @override
  ConsumerState<SavedAccountsScreen> createState() => _SavedAccountsState();
}

class _SavedAccountsState extends ConsumerState<SavedAccountsScreen> {
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    try {
      await ref.read(apiServiceProvider).loadSavedAccounts();
    } catch (_) {
      if (mounted) {
        setState(
          () => _error =
              'Could not unlock saved accounts. Try again or sign in with your password.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _switch(String account) async {
    final api = ref.read(apiServiceProvider);
    final notifier = ref.read(mintlyProvider.notifier);
    // Dispose old account routes and approval drafts before installing another identity.
    Navigator.of(context).popUntil((route) => route.isFirst);
    try {
      if (await api.switchSavedAccount(account)) {
        await notifier.loadInitialData();
      }
    } catch (error) {
      MintlyNotice.showGlobal(SnackBar(content: Text('$error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiServiceProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Saved accounts')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Mintly accounts on this phone. Your server’s X login is separate.',
          ),
          const SizedBox(height: 12),
          if (_busy) const Center(child: CircularProgressIndicator()),
          if (_error != null) Text(_error!),
          for (final account in api.savedAccounts)
            Card(
              child: ListTile(
                leading: const Icon(Icons.person_outline),
                title: Text('${account['username']}'),
                subtitle: Text(
                  account['user_id'] == api.userId
                      ? 'Current account'
                      : 'Fingerprint or phone PIN required',
                ),
                onTap: _busy
                    ? null
                    : () => _switch(account['user_id'] as String),
                trailing: IconButton(
                  tooltip: 'Remove saved account',
                  onPressed: _busy
                      ? null
                      : () async {
                          setState(() => _busy = true);
                          try {
                            await api.removeSavedAccount(
                              account['user_id'] as String,
                            );
                          } catch (error) {
                            if (mounted) setState(() => _error = '$error');
                          } finally {
                            if (mounted) setState(() => _busy = false);
                          }
                        },
                  icon: const Icon(Icons.close),
                ),
              ),
            ),
          if (!_busy && api.savedAccounts.isEmpty)
            const Text(
              'No unlocked saved accounts. Password login remains available.',
            ),
          TextButton(
            onPressed: _busy ? null : _load,
            child: const Text('Unlock saved accounts'),
          ),
          FilledButton.icon(
            onPressed: _busy
                ? null
                : () async {
                    final api = ref.read(apiServiceProvider);
                    try {
                      await PushService.instance.disconnect();
                    } catch (_) {}
                    api.lockSession();
                    if (context.mounted) {
                      Navigator.of(context).popUntil((route) => route.isFirst);
                    }
                  },
            icon: const Icon(Icons.person_add_outlined),
            label: const Text('Add account'),
          ),
        ],
      ),
    );
  }
}
