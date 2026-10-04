import '../theme/compatible_icons.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../services/push_service.dart';
import 'main_shell.dart';

class AuthGate extends ConsumerWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiServiceProvider);
    if (!api.isLiveBackendConnected) return const _LoginScreen();
    if (api.mustChangePassword) return const _ChangePasswordScreen();
    return const MainShell();
  }
}

class _LoginScreen extends ConsumerStatefulWidget {
  const _LoginScreen();
  @override
  ConsumerState<_LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<_LoginScreen> {
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() { _username.dispose(); _password.dispose(); super.dispose(); }

  Future<void> _login() async {
    if (_busy) return;
    setState(() { _busy = true; _error = null; });
    try {
      final api = ref.read(apiServiceProvider);
      final notifier = ref.read(mintlyProvider.notifier);
      await api.login(_username.text, _password.text);
      _password.clear();
      if (!api.mustChangePassword) {
        await notifier.loadInitialData();
        try { await PushService.instance.connect(api); } catch (error) {
          debugPrint('Push registration failed: $error');
        }
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(child: Center(child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 420), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(MintlyIcons.lockOutline, size: 48),
          const SizedBox(height: 18),
          Text('Sign in', style: Theme.of(context).textTheme.headlineMedium, textAlign: TextAlign.center),
          const SizedBox(height: 8),
          const Text('Your Mintly admin creates your account. Use your own username and password.', textAlign: TextAlign.center),
          const SizedBox(height: 24),
          TextField(controller: _username, textInputAction: TextInputAction.next,
            autocorrect: false, decoration: const InputDecoration(labelText: 'Username')),
          const SizedBox(height: 12),
          TextField(controller: _password, obscureText: true, autocorrect: false,
            enableSuggestions: false, onSubmitted: (_) => _login(),
            decoration: const InputDecoration(labelText: 'Password')),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 20),
          FilledButton(onPressed: _busy ? null : _login,
            child: Text(_busy ? 'Signing in…' : 'Sign in')),
        ],
      )),
    ))),
  );
}

class _ChangePasswordScreen extends ConsumerStatefulWidget {
  const _ChangePasswordScreen();
  @override
  ConsumerState<_ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends ConsumerState<_ChangePasswordScreen> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  bool _busy = false;
  String? _error;
  @override
  void dispose() { _current.dispose(); _next.dispose(); super.dispose(); }

  Future<void> _change() async {
    if (_busy) return;
    setState(() { _busy = true; _error = null; });
    try {
      await ref.read(apiServiceProvider).changePassword(_current.text, _next.text);
      _current.clear(); _next.clear();
      PushService.instance.messengerKey.currentState?.showSnackBar(
        const SnackBar(content: Text('Password changed. Sign in with your new password.')));
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(child: Center(child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 420), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Set your password', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 8),
          const Text('Replace the temporary password before using Mintly. Use at least 12 characters.'),
          const SizedBox(height: 20),
          TextField(controller: _current, obscureText: true, autocorrect: false,
            enableSuggestions: false, decoration: const InputDecoration(labelText: 'Temporary password')),
          const SizedBox(height: 12),
          TextField(controller: _next, obscureText: true, autocorrect: false,
            enableSuggestions: false, decoration: const InputDecoration(labelText: 'New password')),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 20),
          FilledButton(onPressed: _busy ? null : _change,
            child: Text(_busy ? 'Saving…' : 'Change password')),
        ],
      )),
    ))),
  );
}
