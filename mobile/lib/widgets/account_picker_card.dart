import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../theme/compatible_icons.dart';
import 'mintly_notice.dart';

class AccountPickerCard extends ConsumerStatefulWidget {
  const AccountPickerCard({super.key});
  @override
  ConsumerState<AccountPickerCard> createState() => _AccountPickerCardState();
}

class _AccountPickerCardState extends ConsumerState<AccountPickerCard> {
  bool _expanded = false;
  bool _busy = false;

  Future<void> _change(String? account) async {
    if (_busy) return;
    setState(() => _busy = true);
    final api = ref.read(apiServiceProvider);
    final notifier = ref.read(mintlyProvider.notifier);
    try {
      if (account == null) {
        await api.beginAddAccount();
      } else if (await api.switchSavedAccount(account)) {
        await notifier.loadInitialData();
      } else {
        return; // Cancelled phone authentication leaves the current account open.
      }
      if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
    } catch (error) {
      MintlyNotice.showGlobal(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiServiceProvider);
    final colors = Theme.of(context).colorScheme;
    return Card(
      margin: EdgeInsets.zero,
      clipBehavior: Clip.antiAlias,
      color: colors.primary.withValues(alpha: .08),
      child: Column(
        children: [
          ListTile(
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 20,
              vertical: 12,
            ),
            leading: CircleAvatar(
              radius: 25,
              backgroundColor: colors.primary,
              foregroundColor: colors.onPrimary,
              child: Text(
                api.username.isEmpty
                    ? '?'
                    : api.username.substring(0, 1).toUpperCase(),
              ),
            ),
            title: Text(
              api.username,
              style: Theme.of(
                context,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
            ),
            subtitle: Text(
              api.isAdmin ? 'Administrator account' : 'Personal account',
            ),
            trailing: api.protectedAccountsAvailable
                ? AnimatedRotation(
                    turns: _expanded ? .25 : 0,
                    duration: const Duration(milliseconds: 200),
                    child: const Icon(MintlyIcons.chevronRight),
                  )
                : null,
            onTap: api.protectedAccountsAvailable && !_busy
                ? () => setState(() => _expanded = !_expanded)
                : null,
          ),
          AnimatedSize(
            duration: const Duration(milliseconds: 220),
            alignment: Alignment.topCenter,
            curve: Curves.easeInOut,
            child: !_expanded
                ? const SizedBox(width: double.infinity)
                : Column(
                    children: [
                      const Divider(height: 1, indent: 20, endIndent: 20),
                      for (final account in api.savedAccounts)
                        ListTile(
                          leading: const Icon(MintlyIcons.verifiedUser),
                          title: Text('${account['username']}'),
                          subtitle: Text(
                            account['user_id'] == api.userId
                                ? 'Current account'
                                : 'Tap to switch account',
                          ),
                          onTap: _busy || account['user_id'] == api.userId
                              ? null
                              : () => _change(account['user_id'] as String),
                          trailing: IconButton(
                            tooltip: 'Remove saved account',
                            icon: const Icon(Icons.close),
                            onPressed: _busy
                                ? null
                                : () async {
                                    setState(() => _busy = true);
                                    try {
                                      await api.removeSavedAccount(
                                        account['user_id'] as String,
                                      );
                                      if (context.mounted &&
                                          !api.isLiveBackendConnected) {
                                        Navigator.of(
                                          context,
                                        ).popUntil((route) => route.isFirst);
                                      }
                                    } catch (error) {
                                      MintlyNotice.showGlobal(
                                        SnackBar(content: Text('$error')),
                                      );
                                    } finally {
                                      if (mounted) {
                                        setState(() => _busy = false);
                                      }
                                    }
                                  },
                          ),
                        ),
                      ListTile(
                        leading: const Icon(MintlyIcons.personAdd),
                        title: const Text('Add account'),
                        onTap: _busy ? null : () => _change(null),
                      ),
                      if (_busy) const LinearProgressIndicator(),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}
