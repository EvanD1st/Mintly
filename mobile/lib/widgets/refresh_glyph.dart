import 'dart:math';
import 'package:flutter/material.dart';

/// A drawn refresh symbol avoids adding a glyph to installed OTA fonts.
class RefreshGlyph extends StatelessWidget {
  final double size;
  const RefreshGlyph({super.key, this.size = 24});
  @override
  Widget build(BuildContext context) => CustomPaint(
    size: Size.square(size),
    painter: _RefreshPainter(IconTheme.of(context).color ?? Colors.white),
  );
}

class _RefreshPainter extends CustomPainter {
  final Color color;
  _RefreshPainter(this.color);
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawArc(
      const Rect.fromLTWH(5, 5, 14, 14),
      pi / 4,
      3 * pi / 2,
      false,
      paint,
    );
    canvas.drawPath(
      Path()
        ..moveTo(19, 4)
        ..lineTo(19, 10)
        ..lineTo(13, 10),
      paint,
    );
  }

  @override
  bool shouldRepaint(_RefreshPainter old) => old.color != color;
}
