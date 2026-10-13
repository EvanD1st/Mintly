import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../services/push_service.dart';

/// Covers every route while preserving an in-flight same-account wallet handoff.
class AccountUnlockScreen extends ConsumerStatefulWidget {
  const AccountUnlockScreen({super.key});
  @override
  ConsumerState<AccountUnlockScreen> createState() => _AccountUnlockState();
}

class _AccountUnlockState extends ConsumerState<AccountUnlockScreen> {
  bool _busy = false;
  @override
  Widget build(BuildContext context) => PopScope(
    canPop: false,
    child: Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.lock_outline, size: 48),
                const SizedBox(height: 16),
                Text(
                  'Unlock account',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const Text(
                  'Use fingerprint or your phone PIN to reopen your account.',
                ),
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy
                      ? null
                      : () async {
                          setState(() => _busy = true);
                          try {
                            await ref
                                .read(apiServiceProvider)
                                .unlockForReopen();
                          } finally {
                            if (mounted) setState(() => _busy = false);
                          }
                        },
                  child: Text(_busy ? 'Unlocking…' : 'Unlock'),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () async {
                          final api = ref.read(apiServiceProvider);
                          try {
                            await PushService.instance.disconnect();
                          } catch (_) {}
                          try {
                            await api.logout();
                          } catch (_) {
                            api.disconnectBackend();
                          }
                        },
                  child: const Text('Log out'),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
