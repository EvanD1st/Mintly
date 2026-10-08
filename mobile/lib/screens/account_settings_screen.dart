import '../widgets/mintly_notice.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/push_service.dart';
import '../state/app_state.dart';
import '../theme/compatible_icons.dart';
import 'admin_screen.dart';
import 'copy_mints_screen.dart';
import 'history_screen.dart';
import 'source_screen.dart';

class AccountSettingsScreen extends ConsumerStatefulWidget {
  const AccountSettingsScreen({super.key});
  @override
  ConsumerState<AccountSettingsScreen> createState() => _AccountSettingsState();
}

class _AccountSettingsState extends ConsumerState<AccountSettingsScreen> {
  bool _signingOut = false;

  Future<void> _signOut() async {
    if (_signingOut) return;
    setState(() => _signingOut = true);
    final api = ref.read(apiServiceProvider);
    try {
      await PushService.instance.disconnect();
    } catch (_) {
      // Local push state is cleared even when unregistering is unavailable.
    }
    try {
      await api.logout();
    } catch (_) {
      // logout clears local authentication in its finally block.
    }
    if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
  }

  Widget _section(String label, List<Widget> children) => Padding(
    padding: const EdgeInsets.only(top: 24),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 8),
          child: Text(
            label,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.primary,
            ),
          ),
        ),
        Card(
          margin: EdgeInsets.zero,
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0)
                  Divider(
                    height: 1,
                    indent: 16,
                    endIndent: 16,
                    color: Theme.of(
                      context,
                    ).colorScheme.outline.withValues(alpha: .55),
                  ),
                children[i],
              ],
            ],
          ),
        ),
      ],
    ),
  );

  Widget _link(String title, String subtitle, Widget icon, Widget page) =>
      ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        leading: icon,
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(subtitle),
        trailing: const Icon(MintlyIcons.chevronRight, size: 20),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute<void>(builder: (_) => page),
        ),
      );

  Widget _notification(bool daily) => ValueListenableBuilder<PushPreferences>(
    valueListenable: PushService.instance.preferences,
    builder: (context, prefs, _) => SwitchListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      title: Text(
        daily ? 'New drop notifications' : 'Mint status notifications',
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
      subtitle: Text(
        daily
            ? 'Updates when new drops are available.'
            : 'Submission and results for your mints.',
      ),
      value: daily ? prefs.dailyList : prefs.mintStatus,
      onChanged: (value) async {
        try {
          await PushService.instance.setPreferences(
            dailyList: daily ? value : null,
            mintStatus: daily ? null : value,
          );
        } catch (_) {
          if (context.mounted) {
            MintlyNotice.show(context, 
              const SnackBar(
                content: Text(
                  'Could not update notifications. Allow notifications and retry.',
                ),
              ),
            );
          }
        }
      },
    ),
  );

  @override
  Widget build(BuildContext context) {
    final api = ref.watch(apiServiceProvider);
    final colors = Theme.of(context).colorScheme;
    final username = api.username;
    return Scaffold(
      appBar: AppBar(title: const Text('Account settings')),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: colors.primary.withValues(alpha: .08),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 25,
                    backgroundColor: colors.primary,
                    foregroundColor: colors.onPrimary,
                    child: Text(
                      username.isEmpty
                          ? '?'
                          : username.substring(0, 1).toUpperCase(),
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          username,
                          style: Theme.of(context).textTheme.titleLarge
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          api.isAdmin
                              ? 'Administrator account'
                              : 'Personal account',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            _section('Your activity', [
              _link(
                'History',
                'Plans, mint results and removed items.',
                const Icon(Icons.history),
                const HistoryScreen(),
              ),
              _link(
                'Copy mints',
                'Follow wallets and manage your copying.',
                const CopyGlyph('copy'),
                const CopyMintsScreen(),
              ),
            ]),
            _section('Notifications', [
              _notification(true),
              _notification(false),
            ]),
            if (api.isAdmin)
              _section('Administration', [
                _link(
                  'Live source',
                  'Feed health and session diagnostics.',
                  const Icon(MintlyIcons.public),
                  const SourceScreen(),
                ),
                _link(
                  'Manage accounts',
                  'Create and manage user access.',
                  const Icon(MintlyIcons.adminPanelSettings),
                  const AdminScreen(),
                ),
              ]),
            _section('About the app', [
              ListTile(
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 6,
                ),
                title: const Text('Open source licenses'),
                subtitle: const Text('Libraries that power the app.'),
                trailing: const Icon(MintlyIcons.chevronRight, size: 20),
                onTap: () => showLicensePage(
                  context: context,
                  applicationName: 'Mintly',
                ),
              ),
            ]),
            const SizedBox(height: 28),
            OutlinedButton.icon(
              onPressed: _signingOut ? null : _signOut,
              icon: const Icon(MintlyIcons.logout),
              label: Text(_signingOut ? 'Signing out…' : 'Sign out'),
            ),
          ],
        ),
      ),
    );
  }
}
