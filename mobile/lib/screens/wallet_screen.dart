import 'account_settings_screen.dart';
import '../theme/compatible_icons.dart';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'import_screen.dart';
import 'custody_import_screen.dart';

class WalletScreen extends ConsumerStatefulWidget {
  const WalletScreen({super.key});
  @override
  ConsumerState<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends ConsumerState<WalletScreen> {
  late Future<List<Map<String, dynamic>>> _wallets;
  late Future<List<Map<String, dynamic>>> _policies;

  @override
  void initState() {
    super.initState();
    _wallets = ref.read(apiServiceProvider).fetchWallets();
    _policies = ref.read(apiServiceProvider).fetchAutomaticPolicies();
  }

  void _refresh() => setState(() {
    _wallets = ref.read(apiServiceProvider).fetchWallets();
    _policies = ref.read(apiServiceProvider).fetchAutomaticPolicies();
  });

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
                const SnackBar(content: Text('MetaMask address linked.')),
              );
            }
          } else if (result['status'] == 'expired') {
            Navigator.of(context, rootNavigator: true).pop();
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Pairing code expired. Try again.'),
                ),
              );
            }
          }
        } catch (_) {
          // The next poll may succeed after a brief network interruption.
        } finally {
          polling = false;
        }
      });
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Connect MetaMask on your PC'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Open this address in the browser where MetaMask is installed:',
              ),
              const SizedBox(height: 8),
              SelectableText(pairing['connect_url'] as String),
              const SizedBox(height: 18),
              const Text('Enter this one-time code there:'),
              const SizedBox(height: 8),
              SelectableText(
                pairing['code'] as String,
                style: const TextStyle(
                  fontSize: 21,
                  fontFamily: 'monospace',
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 12),
              const Text(
                'Expires in 5 minutes. Sign only the readable linking message. Never enter a recovery phrase.',
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Close'),
            ),
          ],
        ),
      );
      timer.cancel();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  Future<void> _unlink(Map<String, dynamic> wallet) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Unlink wallet?'),
        content: const Text(
          'This removes only the public address. Wallets with custody or transaction history must remain linked. Unlinking cannot erase a server key or cancel signed transactions; disable automatic policies to stop future signing.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Unlink'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(apiServiceProvider).unlinkWallet(wallet['id'] as String);
      _refresh();
      await ref.read(mintlyProvider.notifier).loadInitialData();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  String _short(String address) => address.length > 16
      ? '${address.substring(0, 8)}…${address.substring(address.length - 6)}'
      : address;
  String _eth(dynamic wei) {
    final value = BigInt.tryParse('$wei') ?? BigInt.zero,
        scale = BigInt.from(10).pow(18);
    final fraction = (value % scale)
        .toString()
        .padLeft(18, '0')
        .replaceFirst(RegExp(r'0+$'), '');
    return fraction.isEmpty
        ? '${value ~/ scale}'
        : '${value ~/ scale}.$fraction';
  }

  Future<void> _import(Map<String, dynamic> wallet) async {
    final imported = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (_) => CustodyImportScreen(
          walletId: wallet['id'] as String,
          address: wallet['address'] as String,
        ),
      ),
    );
    if (imported == true && mounted) {
      _refresh();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Wallet imported. Select an NFT to review an automatic mint.',
          ),
        ),
      );
    }
  }

  Future<void> _details(
    Map<String, dynamic> wallet,
    List<Map<String, dynamic>> policies,
  ) async {
    final api = ref.read(apiServiceProvider);
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (pageContext) => Scaffold(
          appBar: AppBar(title: const Text('Wallet details')),
          body: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                wallet['label'] as String? ?? 'MetaMask',
                style: Theme.of(pageContext).textTheme.headlineSmall,
              ),
              const SizedBox(height: 12),
              SelectableText(wallet['address'] as String),
              const SizedBox(height: 24),
              if (policies.isEmpty)
                const Text(
                  'Address linked. Import this wallet to prepare automatic minting.',
                ),
              for (final policy in policies)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('Automatic minting: ${policy['status']}'),
                        Text(
                          'Network: ${{1: 'Ethereum', 8453: 'Base', 4663: 'Robinhood'}[policy['chain_id']] ?? 'Chain ${policy['chain_id']}'}',
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Remaining budget: ${_eth(policy['remaining_wei'])} ETH',
                        ),
                        Text(
                          'Pending mints: ${_eth(policy['reserved_wei'])} ETH reserved',
                        ),
                        Text(
                          'Expires: ${DateTime.tryParse('${policy['expires_at']}')?.toLocal().toString().split('.').first ?? policy['expires_at']}',
                        ),
                        const SizedBox(height: 8),
                        Text(
                          (policy['scope'] as Map?)?['collection_scope'] ==
                                  'reviewed_mints'
                              ? 'Collections are selected from your reviewed mints or approved copy rules.'
                              : 'This setup is limited to the collection chosen during import.',
                        ),
                        if (policy['status'] == 'enabled')
                          TextButton(
                            onPressed: () async {
                              try {
                                await api.disableAutomaticPolicy(
                                  policy['id'] as String,
                                );
                                _refresh();
                                if (pageContext.mounted) {
                                  Navigator.pop(pageContext);
                                }
                              } catch (_) {
                                if (pageContext.mounted) {
                                  ScaffoldMessenger.of(
                                    pageContext,
                                  ).showSnackBar(
                                    const SnackBar(
                                      content: Text(
                                        'Could not disable this setup. Please retry.',
                                      ),
                                    ),
                                  );
                                }
                              }
                            },
                            child: const Text('Disable automatic minting'),
                          ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 20),
              const Text(
                'Mintly stores this account’s encrypted key after import. Disabling stops future signing; it cannot erase the key or cancel signed transactions.',
              ),
              const SizedBox(height: 16),
              OutlinedButton(
                onPressed: () => _import(wallet),
                child: const Text('Add or renew a network policy'),
              ),
              const SizedBox(height: 20),
              OutlinedButton.icon(
                onPressed: () async {
                  await _unlink(wallet);
                  if (pageContext.mounted) Navigator.pop(pageContext);
                },
                icon: const Icon(MintlyIcons.linkOff),
                label: const Text('Unlink address'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              'Wallets',
              style: Theme.of(
                context,
              ).textTheme.headlineLarge?.copyWith(fontWeight: FontWeight.bold),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const AccountSettingsScreen()),
            ),
            child: const Text('Settings'),
          ),
        ],
      ),
      const SizedBox(height: 8),
      const Text('Choose the wallet Mintly will use for your mints.'),
      const SizedBox(height: 24),
      FutureBuilder<List<Map<String, dynamic>>>(
        future: _wallets,
        builder: (context, wallets) {
          if (wallets.hasError) {
            return const Text('Could not load wallets. Tap refresh to retry.');
          }
          if (!wallets.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          if (wallets.data!.isEmpty) {
            return const Card(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text('Connect MetaMask to get started.'),
              ),
            );
          }
          return FutureBuilder<List<Map<String, dynamic>>>(
            future: _policies,
            builder: (context, status) => Column(
              children: [
                for (final wallet in wallets.data!)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.account_balance_wallet_outlined),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Text(
                                  wallet['label'] as String? ?? 'MetaMask',
                                  style: Theme.of(context).textTheme.titleLarge,
                                ),
                              ),
                              if (status.hasData)
                                TextButton(
                                  onPressed: () => _details(
                                    wallet,
                                    status.data!
                                        .where(
                                          (p) => p['wallet_id'] == wallet['id'],
                                        )
                                        .toList(),
                                  ),
                                  child: const Text('Details'),
                                ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Text(_short(wallet['address'] as String)),
                          const SizedBox(height: 20),
                          if (status.hasError)
                            const Text(
                              'Automatic minting status unavailable. Refresh to retry.',
                            )
                          else if (!status.hasData)
                            const LinearProgressIndicator()
                          else if (status.data!.any(
                            (p) =>
                                p['wallet_id'] == wallet['id'] &&
                                p['status'] == 'enabled',
                          )) ...[
                            const Text('Imported · ready for mint review'),
                            const SizedBox(height: 12),
                            Text(
                              'Remaining budget: ${_eth(status.data!.where((p) => p['wallet_id'] == wallet['id'] && p['status'] == 'enabled').fold<BigInt>(BigInt.zero, (sum, p) => sum + (BigInt.tryParse('${p['remaining_wei']}') ?? BigInt.zero)))} ETH',
                            ),
                          ] else ...[
                            const Text(
                              'Connected · automatic minting needs setup',
                            ),
                            const SizedBox(height: 16),
                            FilledButton.icon(
                              onPressed: () => _import(wallet),
                              icon: const Icon(MintlyIcons.lockOutline),
                              label: const Text('Set up automatic minting'),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          );
        },
      ),
      const SizedBox(height: 20),
      OutlinedButton.icon(
        onPressed: _pair,
        icon: const Icon(MintlyIcons.link),
        label: const Text('Connect MetaMask'),
      ),
      const SizedBox(height: 12),
      OutlinedButton.icon(
        onPressed: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const ImportScreen()),
        ),
        icon: const Icon(MintlyIcons.addLink),
        label: const Text('Add an OpenSea mint'),
      ),
      TextButton(onPressed: _refresh, child: const Text('Refresh wallets')),
    ],
  );
}
