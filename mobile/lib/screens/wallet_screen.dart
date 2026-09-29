import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';
import 'import_screen.dart';

class WalletScreen extends ConsumerWidget {
  const WalletScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      children: [
        Text(
          'JENNY’S SPACE',
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.6,
            color: muted,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'Wallet & preferences',
          style: TextStyle(
            fontSize: 28,
            fontWeight: FontWeight.w700,
            letterSpacing: -1.0,
            color: ink,
            height: 1.15,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'Choose how you discover and prepare.',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        const SizedBox(height: 18),

        OutlinedButton.icon(
          icon: const Icon(Icons.cloud_outlined),
          label: Text(ref.read(apiServiceProvider).isLiveBackendConnected
              ? 'Disconnect server · use offline demo' : 'Connect to Mintly server'),
          onPressed: () async {
            final api = ref.read(apiServiceProvider);
            if (api.isLiveBackendConnected) {
              api.disconnectBackend();
              await notifier.loadInitialData();
              return;
            }
            final token = await showDialog<String>(
              context: context,
              builder: (_) => const _ServerTokenDialog(),
            );
            if (token == null) return;
            try {
              await api.connectBackend(token);
              await notifier.loadInitialData();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text('Connected for this session. Minting remains in demo mode.'),
                ));
              }
            } catch (error) {
              api.disconnectBackend();
              await notifier.loadInitialData();
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
              }
            }
          },
        ),
        const SizedBox(height: 12),

        // Wallet Card
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: panel,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: line, width: 1),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    "Jenny’s wallet",
                    style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: ink),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: soft,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      'Demo',
                      style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: green),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                'Sample wallet · no account connected',
                style: TextStyle(fontSize: 12, color: muted),
              ),
              const SizedBox(height: 12),
              Container(height: 1, color: line),
              const SizedBox(height: 12),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Mint signing', style: TextStyle(fontSize: 12, color: muted)),
                  Text(
                    'Preview only',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: muted),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),

        // Discovery Preferences Panel
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: panel,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: line, width: 1),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Discovery',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: ink),
              ),
              const SizedBox(height: 12),
              // Switch 1: Monitor @lakzonevn
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Monitor @lakzonevn', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: ink)),
                      const SizedBox(height: 2),
                      Text(
                        state.isMonitoring ? 'Last checked 17:02' : 'Monitoring paused',
                        style: TextStyle(fontSize: 11, color: muted),
                      ),
                    ],
                  ),
                  Switch(
                    value: state.isMonitoring,
                    activeThumbColor: green,
                    onChanged: (val) {
                      notifier.toggleMonitoring();
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text(val ? 'Demo monitoring enabled.' : 'Demo monitoring paused.'),
                          duration: const Duration(seconds: 2),
                        ),
                      );
                    },
                  ),
                ],
              ),
              const SizedBox(height: 8),
              // Switch 2: Daily list notifications
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Daily list notifications', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: ink)),
                  Switch(value: true, activeThumbColor: green, onChanged: (v) {}),
                ],
              ),
              const SizedBox(height: 8),
              // Switch 3: Mint status notifications
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('Mint status notifications', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: ink)),
                  Switch(value: true, activeThumbColor: green, onChanged: (v) {}),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),

        // Time Zone Panel
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: panel,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: line, width: 1),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Time zone', style: TextStyle(fontSize: 13, color: ink)),
              Text('WAT · Lagos', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: ink)),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // Manual Import Button
        OutlinedButton(
          onPressed: () {
            Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const ImportScreen()),
            );
          },
          child: const Text('Import a mint list manually'),
        ),
        const SizedBox(height: 12),

        Text(
          'Automatic discovery can pause if the X connection needs attention. Manual import stays available.',
          style: TextStyle(fontSize: 11, color: muted, height: 1.4),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _ServerTokenDialog extends StatefulWidget {
  const _ServerTokenDialog();
  @override
  State<_ServerTokenDialog> createState() => _ServerTokenDialogState();
}

class _ServerTokenDialogState extends State<_ServerTokenDialog> {
  final _token = TextEditingController();
  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Connect to Mintly'),
    content: TextField(
      controller: _token,
      obscureText: true,
      autocorrect: false,
      enableSuggestions: false,
      decoration: const InputDecoration(
        labelText: 'Server access token',
        helperText: 'Kept only for this app session.',
      ),
    ),
    actions: [
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
      TextButton(onPressed: () => Navigator.pop(context, _token.text), child: const Text('Connect')),
    ],
  );
}
