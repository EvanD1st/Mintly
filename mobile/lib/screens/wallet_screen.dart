import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../services/push_service.dart';
import 'admin_screen.dart';
import 'import_screen.dart';

class WalletScreen extends ConsumerStatefulWidget {
  const WalletScreen({super.key});
  @override
  ConsumerState<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends ConsumerState<WalletScreen> {
  late Future<List<Map<String, dynamic>>> _wallets;

  @override
  void initState() {
    super.initState();
    _wallets = ref.read(apiServiceProvider).fetchWallets();
  }

  void _refresh() => setState(() => _wallets = ref.read(apiServiceProvider).fetchWallets());

  Future<void> _pair() async {
    try {
      final api = ref.read(apiServiceProvider);
      final pairing = await api.startWalletPairing();
      if (!mounted) return;
      final id = pairing['pairing_id'] as String;
      bool polling = false;
      final timer = Timer.periodic(const Duration(seconds: 3), (_) async {
        if (polling || !mounted) return;
        polling = true;
        try {
          final result = await api.walletPairingStatus(id);
          if (!mounted) return;
          if (result['status'] == 'linked') {
            Navigator.of(context, rootNavigator: true).pop();
            _refresh();
            await ref.read(mintlyProvider.notifier).loadInitialData();
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('MetaMask address linked.')));
            }
          } else if (result['status'] == 'expired') {
            Navigator.of(context, rootNavigator: true).pop();
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Pairing code expired. Try again.')));
            }
          }
        } catch (_) {
          // The next poll may succeed after a brief network interruption.
        } finally { polling = false; }
      });
      await showDialog<void>(context: context, builder: (context) => AlertDialog(
        title: const Text('Connect MetaMask on your PC'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Open this address in the browser where MetaMask is installed:'),
            const SizedBox(height: 8),
            SelectableText(pairing['connect_url'] as String),
            const SizedBox(height: 18),
            const Text('Enter this one-time code there:'),
            const SizedBox(height: 8),
            SelectableText(pairing['code'] as String,
              style: const TextStyle(fontSize: 21, fontFamily: 'monospace', fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            const Text('Expires in 5 minutes. Sign only the readable linking message. Never enter a recovery phrase.'),
          ]),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
      ));
      timer.cancel();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  Future<void> _unlink(Map<String, dynamic> wallet) async {
    final confirmed = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
      title: const Text('Unlink wallet?'),
      content: const Text('This removes the public address from your account. Your MetaMask wallet and funds are unaffected.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Unlink')),
      ],
    ));
    if (confirmed != true) return;
    try {
      await ref.read(apiServiceProvider).unlinkWallet(wallet['id'] as String);
      _refresh();
      await ref.read(mintlyProvider.notifier).loadInitialData();
    } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiServiceProvider);
    final state = ref.watch(mintlyProvider);
    final ink = Theme.of(context).colorScheme.onSurface;
    final muted = ink.withValues(alpha: 0.65);
    return ListView(padding: const EdgeInsets.fromLTRB(20, 12, 20, 32), children: [
      Text('Wallet & account', style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: ink)),
      const SizedBox(height: 4),
      Text('Signed in as ${api.username}', style: TextStyle(color: muted)),
      const SizedBox(height: 20),
      Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('MetaMask wallets', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: ink)),
          const SizedBox(height: 8),
          const Text('Link an address with a message signature on your PC. Mintly never receives a seed phrase or private key.'),
          FutureBuilder<List<Map<String, dynamic>>>(future: _wallets, builder: (context, snapshot) {
            if (!snapshot.hasData) {
              if (snapshot.hasError) return Text('${snapshot.error}');
              return const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator()));
            }
            if (snapshot.data!.isEmpty) {
              return const Padding(padding: EdgeInsets.symmetric(vertical: 12),
                child: Text('No wallet linked yet.'));
            }
            return Column(children: [for (final wallet in snapshot.data!) ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.account_balance_wallet_outlined),
              title: Text(wallet['label'] as String? ?? 'MetaMask'),
              subtitle: SelectableText(wallet['address'] as String),
              trailing: IconButton(onPressed: () => _unlink(wallet), icon: const Icon(Icons.link_off),
                tooltip: 'Unlink wallet'),
            )]);
          }),
          FilledButton.icon(onPressed: _pair, icon: const Icon(Icons.link),
            label: const Text('Connect MetaMask')),
        ],
      ))),
      const SizedBox(height: 14),
      Card(child: ListTile(leading: const Icon(Icons.public), title: const Text('Live source'),
        subtitle: Text(state.sourceStatusText))),
      const SizedBox(height: 14),
      Card(child: Padding(padding: const EdgeInsets.all(12), child: Column(children: [
        ValueListenableBuilder<PushPreferences>(valueListenable: PushService.instance.preferences,
          builder: (context, prefs, _) => SwitchListTile(
            title: const Text('New drop notifications'), value: prefs.dailyList,
            onChanged: (value) async {
              try { await PushService.instance.setPreferences(dailyList: value); }
              catch (error) { if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error'))); }
            },
          )),
        ValueListenableBuilder<PushPreferences>(valueListenable: PushService.instance.preferences,
          builder: (context, prefs, _) => SwitchListTile(
            title: const Text('Mint status notifications'), value: prefs.mintStatus,
            onChanged: (value) async {
              try { await PushService.instance.setPreferences(mintStatus: value); }
              catch (error) { if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error'))); }
            },
          )),
      ]))),
      if (api.isAdmin) ...[
        const SizedBox(height: 14),
        OutlinedButton.icon(onPressed: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => const AdminScreen())),
          icon: const Icon(Icons.admin_panel_settings_outlined), label: const Text('Manage accounts')),
        OutlinedButton.icon(onPressed: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => const ImportScreen())),
          icon: const Icon(Icons.add_link), label: const Text('Import a mint link')),
      ],
      const SizedBox(height: 18),
      OutlinedButton.icon(onPressed: () async {
        final notifier = ref.read(mintlyProvider.notifier);
        try { await PushService.instance.disconnect(); } catch (_) {}
        await api.logout();
        await notifier.loadInitialData();
      }, icon: const Icon(Icons.logout), label: const Text('Sign out')),
    ]);
  }
}
