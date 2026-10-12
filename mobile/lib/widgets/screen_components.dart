import 'package:flutter/material.dart';

/// Keeps disclosure controls independent of an installer's icon-font subset.
class DisclosureSection extends StatefulWidget {
  final Widget title;
  final Widget? subtitle;
  final EdgeInsetsGeometry? tilePadding;
  final List<Widget> children;
  const DisclosureSection({
    super.key,
    required this.title,
    this.subtitle,
    this.tilePadding,
    required this.children,
  });
  @override
  State<DisclosureSection> createState() => _DisclosureSectionState();
}

class _DisclosureSectionState extends State<DisclosureSection> {
  bool _expanded = false;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Semantics(
        button: true,
        expanded: _expanded,
        child: ListTile(
          contentPadding: widget.tilePadding,
          title: widget.title,
          subtitle: widget.subtitle,
          onTap: () => setState(() => _expanded = !_expanded),
          trailing: CustomPaint(
            size: const Size.square(24),
            painter: _DisclosurePainter(
              _expanded,
              Theme.of(context).colorScheme.primary,
            ),
          ),
        ),
      ),
      AnimatedSize(
        duration: const Duration(milliseconds: 180),
        alignment: Alignment.topCenter,
        child: _expanded
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: widget.children,
              )
            : const SizedBox.shrink(),
      ),
    ],
  );
}

class _DisclosurePainter extends CustomPainter {
  final bool expanded;
  final Color color;
  _DisclosurePainter(this.expanded, this.color);
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(
      Path()
        ..moveTo(6, expanded ? 14 : 8)
        ..lineTo(12, expanded ? 8 : 14)
        ..lineTo(18, expanded ? 14 : 8),
      paint,
    );
  }

  @override
  bool shouldRepaint(_DisclosurePainter old) =>
      old.expanded != expanded || old.color != color;
}

String shortAddress(String value) => value.length > 16
    ? '${value.substring(0, 6)}…${value.substring(value.length - 4)}'
    : value;

String statusLabel(String status) =>
    const {
      'ready_for_approval': 'Needs approval',
      'scheduled': 'Needs approval',
      'unverified': 'Needs review',
      'armed': 'Armed',
      'active': 'Active',
      'preparing': 'Preparing',
      'prepared': 'Signed',
      'submitted': 'Pending',
      'confirmed': 'Confirmed',
      'uncertain': 'Tracking transaction',
      'failed': 'Failed',
      'skipped': 'Skipped',
      'disarmed': 'Disarmed',
      'expired': 'Expired',
      'check_only': 'Check-only',
      'watching': 'Watching',
      'paused': 'Paused',
    }[status] ??
    status.replaceAll('_', ' ');

class ScreenHeading extends StatelessWidget {
  final String title, subtitle;
  final Widget? action;
  const ScreenHeading(this.title, this.subtitle, {super.key, this.action});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
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
                  fontSize: 26,
                  letterSpacing: -.6,
                ),
              ),
            ),
            ?action,
          ],
        ),
        const SizedBox(height: 4),
        Text(
          subtitle,
          style: TextStyle(
            color: Theme.of(
              context,
            ).colorScheme.onSurface.withValues(alpha: .65),
            fontSize: 13,
            height: 1.3,
          ),
        ),
      ],
    ),
  );
}

class StatusBadge extends StatelessWidget {
  final String status;
  final bool compact;
  const StatusBadge(this.status, {super.key, this.compact = false});
  @override
  Widget build(BuildContext context) {
    final color = ['failed', 'reverted'].contains(status)
        ? const Color(0xFFFFAAA3)
        : ['confirmed', 'armed', 'active'].contains(status)
        ? Theme.of(context).colorScheme.primary
        : const Color(0xFFE9CC83);
    final filled = [
      'armed',
      'active',
      'ready_for_approval',
      'scheduled',
    ].contains(status);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 10,
        vertical: compact ? 3 : 5,
      ),
      decoration: BoxDecoration(
        color: filled ? color : color.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: .3)),
      ),
      child: Text(
        statusLabel(status),
        style: TextStyle(
          color: filled ? const Color(0xFF102013) : color,
          fontSize: compact ? 10 : 12,
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
    padding: const EdgeInsets.symmetric(vertical: 6),
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
              fontSize: 12,
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
              fontSize: 12,
            ),
          ),
        ),
      ],
    ),
  );
}

class AppPanel extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  const AppPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(12),
  });
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    decoration: BoxDecoration(
      gradient: const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xFF192A20), Color(0xFF142019)],
      ),
      borderRadius: BorderRadius.circular(15),
      border: Border.all(color: const Color(0xFF33483A)),
    ),
    child: Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(15),
      child: Padding(padding: padding, child: child),
    ),
  );
}

class NetworkBadge extends StatelessWidget {
  final String network;
  const NetworkBadge(this.network, {super.key});
  @override
  Widget build(BuildContext context) {
    final name = network.replaceAll(' Chain', '');
    final color = name.toLowerCase() == 'base'
        ? const Color(0xFF345C7E)
        : const Color(0xFF33483A);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .6),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(name, style: const TextStyle(fontSize: 10, height: 1.1)),
    );
  }
}

class CollectionHeader extends StatelessWidget {
  final String name, network, status;
  final Widget artwork;
  const CollectionHeader({
    super.key,
    required this.name,
    required this.artwork,
    this.network = '',
    this.status = '',
  });
  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      artwork,
      const SizedBox(width: 10),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              name,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                height: 1.15,
              ),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 5,
              runSpacing: 4,
              children: [
                if (network.isNotEmpty) NetworkBadge(network),
                if (status.isNotEmpty) StatusBadge(status, compact: true),
              ],
            ),
          ],
        ),
      ),
    ],
  );
}

class CompactFact {
  final String label, value, icon;
  const CompactFact(this.label, this.value, this.icon);
}

class FactGrid extends StatelessWidget {
  final List<CompactFact> facts;
  const FactGrid(this.facts, {super.key});
  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      border: Border.all(color: Theme.of(context).dividerColor),
      borderRadius: BorderRadius.circular(9),
    ),
    child: Column(
      children: [
        for (var i = 0; i < facts.length; i += 2) ...[
          if (i > 0) Divider(height: 1, color: Theme.of(context).dividerColor),
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(child: _cell(context, facts[i])),
                if (i + 1 < facts.length) ...[
                  VerticalDivider(
                    width: 1,
                    color: Theme.of(context).dividerColor,
                  ),
                  Expanded(child: _cell(context, facts[i + 1])),
                ],
              ],
            ),
          ),
        ],
      ],
    ),
  );
  Widget _cell(BuildContext context, CompactFact fact) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
    child: Wrap(
      spacing: 8,
      runSpacing: 3,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppGlyph(fact.icon, size: 14),
            const SizedBox(width: 5),
            Flexible(
              child: Text(
                fact.label,
                style: TextStyle(
                  fontSize: 10,
                  color: Theme.of(
                    context,
                  ).colorScheme.onSurface.withValues(alpha: .65),
                ),
              ),
            ),
          ],
        ),
        Text(
          fact.value,
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w500,
            height: 1.15,
          ),
        ),
      ],
    ),
  );
}

/// Drawn symbols keep the refined interface compatible with installed OTA fonts.
class AppGlyph extends StatelessWidget {
  final String kind;
  final double size;
  final Color? color;
  const AppGlyph(this.kind, {super.key, this.size = 20, this.color});
  @override
  Widget build(BuildContext context) => CustomPaint(
    size: Size.square(size),
    painter: _AppGlyphPainter(
      kind,
      color ?? Theme.of(context).colorScheme.onSurface.withValues(alpha: .7),
    ),
  );
}

class _AppGlyphPainter extends CustomPainter {
  final String kind;
  final Color color;
  _AppGlyphPainter(this.kind, this.color);
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    switch (kind) {
      case 'calendar':
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            const Rect.fromLTWH(4, 5, 16, 16),
            const Radius.circular(3),
          ),
          p,
        );
        canvas.drawLine(const Offset(4, 10), const Offset(20, 10), p);
        canvas.drawLine(const Offset(8, 3), const Offset(8, 7), p);
        canvas.drawLine(const Offset(16, 3), const Offset(16, 7), p);
      case 'people':
        canvas.drawCircle(const Offset(9, 7), 3, p);
        canvas.drawPath(
          Path()
            ..moveTo(3, 21)
            ..lineTo(3, 17)
            ..quadraticBezierTo(9, 11, 15, 17)
            ..lineTo(15, 21),
          p,
        );
        canvas.drawPath(
          Path()
            ..moveTo(17, 4)
            ..quadraticBezierTo(24, 7, 17, 10),
          p,
        );
        canvas.drawPath(
          Path()
            ..moveTo(18, 14)
            ..quadraticBezierTo(23, 14, 22, 21),
          p,
        );
      case 'clock':
        canvas.drawCircle(const Offset(12, 12), 8, p);
        canvas.drawPath(
          Path()
            ..moveTo(12, 7)
            ..lineTo(12, 12)
            ..lineTo(16, 14),
          p,
        );
      case 'phase':
        canvas.drawPath(
          Path()
            ..moveTo(4, 11)
            ..lineTo(11, 4)
            ..lineTo(19, 4)
            ..lineTo(20, 12)
            ..lineTo(12, 20)
            ..close(),
          p,
        );
        canvas.drawCircle(const Offset(15, 8), 1, p);
      case 'quantity':
        for (final y in [8.0, 12.0, 16.0]) {
          canvas.drawPath(
            Path()
              ..moveTo(4, y)
              ..lineTo(12, y + 4)
              ..lineTo(20, y),
            p,
          );
        }
        canvas.drawPath(
          Path()
            ..moveTo(4, 8)
            ..lineTo(12, 4)
            ..lineTo(20, 8),
          p,
        );
      case 'gas':
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            const Rect.fromLTWH(5, 4, 11, 16),
            const Radius.circular(2),
          ),
          p,
        );
        canvas.drawRect(const Rect.fromLTWH(7, 6, 7, 5), p);
        canvas.drawPath(
          Path()
            ..moveTo(16, 8)
            ..lineTo(20, 11)
            ..lineTo(20, 18)
            ..lineTo(17, 18),
          p,
        );
      case 'list':
        for (final y in [6.0, 12.0, 18.0]) {
          canvas.drawCircle(Offset(4, y), .6, p);
          canvas.drawLine(Offset(9, y), Offset(21, y), p);
        }
      case 'trend':
        canvas.drawPath(
          Path()
            ..moveTo(3, 18)
            ..lineTo(9, 10)
            ..lineTo(14, 14)
            ..lineTo(21, 5),
          p,
        );
      case 'arrow':
        canvas.drawPath(
          Path()
            ..moveTo(9, 5)
            ..lineTo(16, 12)
            ..lineTo(9, 19),
          p,
        );
      case 'check':
        canvas.drawPath(
          Path()
            ..moveTo(4, 12)
            ..lineTo(9, 17)
            ..lineTo(20, 6),
          p,
        );
      default:
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            const Rect.fromLTWH(3, 6, 18, 14),
            const Radius.circular(3),
          ),
          p,
        );
        canvas.drawLine(const Offset(4, 10), const Offset(20, 10), p);
        canvas.drawCircle(const Offset(17, 15), .7, p);
    }
  }

  @override
  bool shouldRepaint(_AppGlyphPainter old) =>
      old.kind != kind || old.color != color;
}
