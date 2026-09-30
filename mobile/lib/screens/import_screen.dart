import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';

class ImportScreen extends ConsumerStatefulWidget {
  const ImportScreen({super.key});

  @override
  ConsumerState<ImportScreen> createState() => _ImportScreenState();
}

class _ImportScreenState extends ConsumerState<ImportScreen> {
  final TextEditingController _textController = TextEditingController();

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);

    return Scaffold(
      backgroundColor: bg,
      appBar: AppBar(
        leadingWidth: 100,
        leading: TextButton.icon(
          onPressed: () => Navigator.of(context).pop(),
          icon: Icon(Icons.arrow_back, size: 16, color: muted),
          label: Text('All drops', style: TextStyle(color: muted, fontSize: 13)),
          style: TextButton.styleFrom(padding: EdgeInsets.zero),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        children: [
          Text(
            'BRING YOUR OWN LIST',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.6,
              color: muted,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Import a drop.',
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
            'Paste a mint link or the full daily list.',
            style: TextStyle(fontSize: 13, color: muted),
          ),
          const SizedBox(height: 20),

          Text(
            'Mint link or post text',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: ink),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _textController,
            maxLines: 7,
            style: TextStyle(fontSize: 14, color: ink),
            decoration: const InputDecoration(
              hintText: 'Paste a mint link or the full daily list here…',
            ),
          ),
          const SizedBox(height: 14),

          Text(
            'A post link may need an active X connection. Paste the full text when monitoring is unavailable.',
            style: TextStyle(fontSize: 11, color: muted, height: 1.4),
          ),
          const SizedBox(height: 24),

          ElevatedButton(
            onPressed: () async {
              final text = _textController.text.trim();
              if (text.isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Paste a mint link or list first.'),
                    duration: Duration(seconds: 2),
                  ),
                );
                return;
              }

              try {
                final imported = await notifier.importList(text);
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(imported ? 'Import complete.' : 'Connect to your server in Wallet before importing.'),
                  ));
                  if (imported) Navigator.of(context).pop();
                }
              } catch (error) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$error')));
                }
              }
            },
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text('Preview imported drops'),
                SizedBox(width: 8),
                Icon(Icons.arrow_forward, size: 16),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
