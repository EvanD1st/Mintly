import 'package:flutter/material.dart';

String shortAddress(String value) => value.length > 16
    ? '${value.substring(0, 6)}…${value.substring(value.length - 4)}'
    : value;

String statusLabel(String status) =>
    const {
      'ready_for_approval': 'Needs approval',
      'scheduled': 'Needs approval',
      'unverified': 'Needs review',
      'armed': 'Armed',
      'preparing': 'Preparing',
      'prepared': 'Signed',
      'submitted': 'Pending',
      'confirmed': 'Confirmed',
      'uncertain': 'Tracking transaction',
      'failed': 'Failed',
      'skipped': 'Skipped',
      'disarmed': 'Disarmed',
      'expired': 'Expired',
    }[status] ??
    status.replaceAll('_', ' ');

class ScreenHeading extends StatelessWidget {
  final String title, subtitle;
  final Widget? action;
  const ScreenHeading(this.title, this.subtitle, {super.key, this.action});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 22),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                title,
                style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                  fontWeight: FontWeight.w700,
                  letterSpacing: -1,
                ),
              ),
            ),
            ?action,
          ],
        ),
        const SizedBox(height: 6),
        Text(
          subtitle,
          style: TextStyle(
            color: Theme.of(
              context,
            ).colorScheme.onSurface.withValues(alpha: .65),
            height: 1.4,
          ),
        ),
      ],
    ),
  );
}

class StatusBadge extends StatelessWidget {
  final String status;
  const StatusBadge(this.status, {super.key});
  @override
  Widget build(BuildContext context) {
    final color = ['failed', 'reverted'].contains(status)
        ? const Color(0xFFFFAAA3)
        : ['confirmed', 'armed', 'active'].contains(status)
        ? Theme.of(context).colorScheme.primary
        : const Color(0xFFE9CC83);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: .3)),
      ),
      child: Text(
        statusLabel(status),
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class DetailRow extends StatelessWidget {
  final String label, value;
  final bool emphasis;
  const DetailRow(this.label, this.value, {super.key, this.emphasis = false});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 9),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(
            label,
            style: TextStyle(
              color: Theme.of(
                context,
              ).colorScheme.onSurface.withValues(alpha: .65),
            ),
          ),
        ),
        const SizedBox(width: 16),
        Flexible(
          flex: 2,
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: TextStyle(
              fontWeight: emphasis ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
        ),
      ],
    ),
  );
}
