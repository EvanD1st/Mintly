import '../theme/compatible_icons.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';

class AdminScreen extends ConsumerStatefulWidget {
  const AdminScreen({super.key});
  @override
  ConsumerState<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends ConsumerState<AdminScreen> {
  late Future<List<Map<String, dynamic>>> _users;
  @override
  void initState() { super.initState(); _users = ref.read(apiServiceProvider).listUsers(); }
  void _refresh() => setState(() => _users = ref.read(apiServiceProvider).listUsers());

  Future<String?> _prompt(String title, {String? username}) async {
    final input = TextEditingController();
    final password = TextEditingController();
    final result = await showDialog<(String, String)>(context: context, builder: (context) => AlertDialog(
      title: Text(title),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        if (username == null) TextField(controller: input, autocorrect: false,
          decoration: const InputDecoration(labelText: 'New username')),
        TextField(controller: password, obscureText: true, autocorrect: false,
          enableSuggestions: false, decoration: const InputDecoration(labelText: 'Your admin password')),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(context, (input.text.trim(), password.text)),
          child: const Text('Confirm')),
      ],
    ));
    input.dispose(); password.dispose();
    if (result == null) return null;
    return '${result.$1}\n${result.$2}';
  }

  Future<void> _showTemporaryPassword(Map<String, dynamic> response) async {
    final user = response['user'] as Map<String, dynamic>;
    final temporary = response['temporary_password'] as String;
    await showDialog<void>(context: context, builder: (context) => AlertDialog(
      title: Text('Password for ${user['username']}'),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Shown only once. Share it privately; the user must change it at first sign-in.'),
        const SizedBox(height: 14),
        SelectableText(temporary, style: const TextStyle(fontFamily: 'monospace', fontSize: 18)),
      ]),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Done'))],
    ));
  }

  Future<void> _create() async {
    final values = await _prompt('Create account');
    if (values == null) return;
    final split = values.split('\n');
    try {
      final response = await ref.read(apiServiceProvider).createUser(split[0], split[1]);
      if (mounted) await _showTemporaryPassword(response);
      if (mounted) _refresh();
    } catch (error) { _showError(error); }
  }

  Future<void> _reset(Map<String, dynamic> user) async {
    final values = await _prompt('Reset ${user['username']} password', username: user['username'] as String);
    if (values == null) return;
    try {
      final response = await ref.read(apiServiceProvider).resetUserPassword(user['id'] as String, values.split('\n').last);
      if (mounted) await _showTemporaryPassword(response);
      if (mounted) _refresh();
    } catch (error) { _showError(error); }
  }

  Future<void> _delete(Map<String, dynamic> user) async {
    final values = await _prompt('Delete ${user['username']} account?', username: user['username'] as String);
    if (values == null) return;
    try {
      await ref.read(apiServiceProvider).deleteUser(user['id'] as String, values.split('\n').last);
      if (mounted) _refresh();
    } catch (error) { _showError(error); }
  }

  void _showError(Object error) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Accounts')),
    floatingActionButton: FloatingActionButton.extended(onPressed: _create,
      icon: const Icon(MintlyIcons.personAdd), label: const Text('Create account')),
    body: FutureBuilder<List<Map<String, dynamic>>>(future: _users, builder: (context, snapshot) {
      if (!snapshot.hasData) {
        if (snapshot.hasError) return Center(child: Text('${snapshot.error}'));
        return const Center(child: CircularProgressIndicator());
      }
      return ListView(children: [
        const ListTile(title: Text('Admin-created accounts'),
          subtitle: Text('Reset revokes sessions. Delete removes access and retains transaction history for audit.')),
        for (final user in snapshot.data!) ListTile(
          title: Text(user['username'] as String),
          subtitle: Text(user['role'] == 'admin' ? 'Admin' :
            user['must_change_password'] == true ? 'Temporary password active' : 'Member'),
          trailing: user['role'] == 'admin' ? null : PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert),
            onSelected: (action) => action == 'reset' ? _reset(user) : _delete(user),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'reset', child: Text('Reset password')),
              PopupMenuItem(value: 'delete', child: Text('Delete account')),
            ],
          ),
        ),
      ]);
    }),
  );
}
