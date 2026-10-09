import '../widgets/mintly_notice.dart';
import '../widgets/wallet_readiness_panel.dart';
import '../services/wat_time.dart';
import 'account_settings_screen.dart';
import '../theme/compatible_icons.dart';
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
  late Future<Map<String, dynamic>> _readiness;

  @override
  void initState() {
    super.initState();
    _wallets = ref.read(apiServiceProvider).fetchWallets();
    _policies = ref.read(apiServiceProvider).fetchAutomaticPolicies();
    _readiness = ref.read(apiServiceProvider).fetchWalletReadiness().catchError((_) => <String, dynamic>{'unavailable': true});
  }

  void _refresh() => setState(() {
    _wallets = ref.read(apiServiceProvider).fetchWallets();
    _policies = ref.read(apiServiceProvider).fetchAutomaticPolicies();
    _readiness = ref.read(apiServiceProvider).fetchWalletReadiness().catchError((_) => <String, dynamic>{'unavailable': true});
  });

  final Set<String> _unlinking = {};

  Future<bool> _unlink(Map<String, dynamic> wallet) async {
    final id = wallet['id'] as String;
    if (_unlinking.contains(id)) return false;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Unlink wallet?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_short(wallet['address'] as String)),
            const SizedBox(height: 12),
            const Text(
              'This disables copying and automatic minting for this wallet. Transactions already signed may still finish. Your history is retained.',
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Okay'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return false;
    setState(() => _unlinking.add(id));
    try {
      await ref.read(apiServiceProvider).unlinkWallet(wallet['id'] as String);
      _refresh();
      await ref.read(mintlyProvider.notifier).loadInitialData();
      return true;
    } catch (error) {
      if (mounted) {
        MintlyNotice.show(context, SnackBar(content: Text('$error')));
      }
      return false;
    } finally {
      if (mounted) setState(() => _unlinking.remove(id));
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

  Future<void> _import([Map<String, dynamic>? wallet]) async {
    final imported = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (_) => CustodyImportScreen(
          walletId: wallet?['id'] as String?,
          address: wallet?['address'] as String?,
        ),
      ),
    );
    if (imported == true && mounted) {
      _refresh();
      MintlyNotice.show(context,
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
                          'Expires: ${DateTime.tryParse('${policy['expires_at']}') == null ? policy['expires_at'] : WatTime.label(DateTime.parse('${policy['expires_at']}'))}',
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
                  final unlinked = await _unlink(wallet);
                  if (unlinked && pageContext.mounted) {
                    Navigator.pop(pageContext);
                  }
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
            onPressed: () async {
              await Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const AccountSettingsScreen()),
              );
              if (mounted) _refresh();
            },
            child: const Text('Settings'),
          ),
        ],
      ),
      const SizedBox(height: 20),
      FutureBuilder<List<Map<String, dynamic>>>(
        future: _wallets,
        builder: (context, wallets) {
          if (wallets.hasError) {
            return const Text('Could not load wallets. Refresh to retry.');
          }
          if (!wallets.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          if (wallets.data!.isEmpty) {
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Text('Add your first wallet.'),
            );
          }
          return FutureBuilder<List<Map<String, dynamic>>>(
            future: _policies,
            builder: (context, policies) => Column(
              children: [
                for (final wallet in wallets.data!)
                  Card(
                    key: ValueKey('wallet-${wallet['id']}'),
                    child: Column(children: [ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 10,
                      ),
                      leading: const Icon(
                        Icons.account_balance_wallet_outlined,
                      ),
                      title: Text(
                        wallet['label'] as String? ?? 'Wallet',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(_short(wallet['address'] as String)),
                      onTap: () => _details(
                        wallet,
                        (policies.data ?? [])
                            .where((p) => p['wallet_id'] == wallet['id'])
                            .toList(),
                      ),
                      trailing: TextButton(
                        key: ValueKey('unlink-${wallet['id']}'),
                        onPressed: _unlinking.contains(wallet['id'])
                            ? null
                            : () => _unlink(wallet),
                        child: Text(
                          _unlinking.contains(wallet['id'])
                              ? 'Unlinking…'
                              : 'Unlink',
                        ),
                      ),
                    ), WalletReadinessPanel(walletId: wallet['id'] as String, readiness: _readiness)]),
                  ),
              ],
            ),
          );
        },
      ),
      const SizedBox(height: 20),
      FilledButton.icon(
        onPressed: () => _import(),
        icon: const Icon(MintlyIcons.addLink),
        label: const Text('Add wallet'),
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
