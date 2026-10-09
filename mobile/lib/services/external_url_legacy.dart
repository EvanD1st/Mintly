import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

// Older installers have no url_launcher native plugin. The release-specific
// build uses this Dart-only flow instead of invoking an absent method channel.
Future<bool> openExternalUrl(BuildContext context, Uri uri) async {
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Open link'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Copy this link and paste it into your browser.'),
          const SizedBox(height: 12),
          SelectableText(uri.toString()),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('Close'),
        ),
        TextButton(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: uri.toString()));
            if (dialogContext.mounted) Navigator.pop(dialogContext);
          },
          child: const Text('Copy link'),
        ),
      ],
    ),
  );
  return true;
}
