import 'package:flutter/material.dart';

// Drawn to work with the icon fonts in every installed OTA release.
class PhraseVisibilityIcon extends StatelessWidget {
  final bool visible;
  const PhraseVisibilityIcon({super.key, required this.visible});
  @override
  Widget build(BuildContext context) => CustomPaint(
    size: const Size(24, 24),
    painter: _EyePainter(visible, Theme.of(context).colorScheme.onSurface),
  );
}

class _EyePainter extends CustomPainter {
  final bool visible;
  final Color color;
  _EyePainter(this.visible, this.color);
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.7
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(
      Path()
        ..moveTo(2, 12)
        ..quadraticBezierTo(12, 1, 22, 12)
        ..quadraticBezierTo(12, 23, 2, 12)
        ..close(),
      paint,
    );
    canvas.drawCircle(const Offset(12, 12), 3, paint);
    if (!visible)
      canvas.drawLine(const Offset(3, 3), const Offset(21, 21), paint);
  }

  @override
  bool shouldRepaint(_EyePainter oldDelegate) =>
      oldDelegate.visible != visible || oldDelegate.color != color;
}
