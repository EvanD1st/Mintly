import 'package:flutter/material.dart';

// Draw the trash icon so existing installations need no new font asset for OTA.
class DeleteDropIcon extends StatelessWidget {
  const DeleteDropIcon({super.key});
  @override
  Widget build(BuildContext context) => CustomPaint(
    size: const Size(22, 22),
    painter: _DeletePainter(Theme.of(context).colorScheme.onSurface),
  );
}

class _DeletePainter extends CustomPainter {
  final Color color;
  const _DeletePainter(this.color);
  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 24);
    final p = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.7
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(
      Path()
        ..moveTo(4, 6)
        ..lineTo(20, 6)
        ..moveTo(9, 6)
        ..lineTo(9, 3)
        ..lineTo(15, 3)
        ..lineTo(15, 6)
        ..moveTo(6, 6)
        ..lineTo(7, 21)
        ..lineTo(17, 21)
        ..lineTo(18, 6)
        ..moveTo(10, 10)
        ..lineTo(10, 17)
        ..moveTo(14, 10)
        ..lineTo(14, 17),
      p,
    );
  }

  @override
  bool shouldRepaint(_DeletePainter oldDelegate) => oldDelegate.color != color;
}
