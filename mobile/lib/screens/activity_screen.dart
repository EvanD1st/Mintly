import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';

class ActivityScreen extends ConsumerWidget {
  const ActivityScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final soft = MintlyColors.getSoft(isDark);

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      children: [
        Text(
          'YOUR MINT JOURNAL',
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.6,
            color: muted,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'Activity',
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
          'From discovery to confirmation.',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        const SizedBox(height: 18),

        // Activity Items
        ...state.activities.map((ev) {
          IconData icon = Icons.notifications_none;
          if (ev.iconName == 'shield-check') {
            icon = Icons.verified_user_outlined;
          } else if (ev.iconName == 'download') {
            icon = Icons.download_outlined;
          } else if (ev.iconName == 'timer') {
            icon = Icons.timer_outlined;
          } else if (ev.iconName == 'circle-pause') {
            icon = Icons.pause_circle_outline;
          }

          return Container(
            padding: const EdgeInsets.symmetric(vertical: 14),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: line, width: 1)),
            ),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: soft,
                    shape: BoxShape.circle,
                  ),
                  child: Center(
                    child: Icon(icon, size: 18, color: green),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        ev.label,
                        style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: ink),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        ev.detail,
                        style: TextStyle(fontSize: 12, color: muted),
                      ),
                    ],
                  ),
                ),
                Text(
                  ev.formattedTime,
                  style: TextStyle(fontSize: 11, color: muted),
                ),
              ],
            ),
          );
        }),

        const SizedBox(height: 20),

        // Notice Banner
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: soft,
            borderRadius: const BorderRadius.only(
              topRight: Radius.circular(10),
              bottomRight: Radius.circular(10),
            ),
            border: Border(left: BorderSide(color: green, width: 3)),
          ),
          child: Text(
            'Transactions will show submitted, confirmed, or failed here, with the actual fee and a transaction link.',
            style: TextStyle(fontSize: 12, color: ink, height: 1.4),
          ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }
}
