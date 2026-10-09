import 'package:flutter/material.dart';

class MintProgress extends StatelessWidget {
  final Map<String, dynamic> progress;
  const MintProgress({super.key, required this.progress});

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final steps = progress['steps'] as List? ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('${progress['label'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final step in steps) Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
            decoration: BoxDecoration(
              color: step['state'] == 'complete' || step['state'] == 'current'
                  ? colors.primary.withValues(alpha: .12) : colors.surfaceContainerLow,
              borderRadius: BorderRadius.circular(8),
              border: step['state'] == 'current' ? Border.all(color: colors.primary) : null,
            ),
            child: Text('${step['label']}', style: TextStyle(fontSize: 11,
              color: step['state'] == 'stopped' ? colors.error : colors.onSurface)),
          ),
        ]),
      ],
    );
  }
}
