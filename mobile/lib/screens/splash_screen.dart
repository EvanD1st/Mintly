import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/colors.dart';
import 'auth_gate.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _loaderAnimation;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1400),
    );

    _loaderAnimation = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(parent: _controller, curve: const Cubic(0.2, 0.7, 0.4, 1.0)),
    );

    _controller.forward();

    // Smooth transition into the main shell once initialization finishes
    _timer = Timer(const Duration(milliseconds: 1800), () {
      if (mounted) {
        Navigator.of(context).pushReplacement(
          PageRouteBuilder(
            pageBuilder: (context, anim1, anim2) => const AuthGate(),
            transitionsBuilder: (context, anim1, anim2, child) => FadeTransition(
              opacity: anim1,
              child: child,
            ),
            transitionDuration: const Duration(milliseconds: 400),
          ),
        );
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);

    return Scaffold(
      backgroundColor: bg,
      body: SafeArea(
        child: Stack(
          alignment: Alignment.center,
          children: [
            // Orbital background circles matching reference
            Positioned(
              top: MediaQuery.of(context).size.height * 0.25,
              child: CustomPaint(
                size: const Size(600, 600),
                painter: _OrbitRingsPainter(lineColor: line),
              ),
            ),
            // Splash Content
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  // Kicker
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Container(
                        width: 5,
                        height: 5,
                        decoration: BoxDecoration(color: green, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        'A LITTLE AHEAD',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 3,
                          color: muted,
                        ),
                      ),
                    ],
                  ),

                  // Center Logo, Wordmark, Tagline & Loader
                  Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      // Orbit Logo Mark
                      Stack(
                        clipBehavior: Clip.none,
                        alignment: Alignment.center,
                        children: [
                          Transform.rotate(
                            angle: -7 * math.pi / 180,
                            child: Container(
                              width: 96,
                              height: 96,
                              decoration: BoxDecoration(
                                color: green,
                                borderRadius: BorderRadius.circular(28),
                                boxShadow: [
                                  BoxShadow(
                                    color: green.withValues(alpha: 0.25),
                                    blurRadius: 36,
                                    offset: const Offset(0, 10),
                                  ),
                                ],
                              ),
                              child: Center(
                                child: Transform.rotate(
                                  angle: 7 * math.pi / 180,
                                  child: const Icon(
                                    Icons.adjust,
                                    size: 52,
                                    color: Colors.white,
                                  ),
                                ),
                              ),
                            ),
                          ),
                          // Sparkle
                          Positioned(
                            top: -6,
                            right: -10,
                            child: Icon(Icons.star, size: 22, color: green),
                          ),
                          // Dot
                          Positioned(
                            bottom: 6,
                            left: -8,
                            child: Container(
                              width: 7,
                              height: 7,
                              decoration: BoxDecoration(
                                color: green.withValues(alpha: 0.6),
                                shape: BoxShape.circle,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 22),

                      // Wordmark: mintly.
                      RichText(
                        text: TextSpan(
                          style: TextStyle(
                            fontSize: 54,
                            fontWeight: FontWeight.w800,
                            letterSpacing: -3.0,
                            color: ink,
                            fontFamily: 'Roboto',
                          ),
                          children: [
                            const TextSpan(text: 'mintly'),
                            TextSpan(
                              text: '.',
                              style: TextStyle(color: green),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 12),

                      // Tagline
                      Text(
                        'Your next mint.\nAlready planned.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 15,
                          height: 1.5,
                          letterSpacing: -0.2,
                          color: muted,
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                      const SizedBox(height: 36),

                      // Animated Loader Bar
                      Container(
                        width: 112,
                        height: 3,
                        decoration: BoxDecoration(
                          color: MintlyColors.getSoft(isDark),
                          borderRadius: BorderRadius.circular(3),
                        ),
                        child: AnimatedBuilder(
                          animation: _loaderAnimation,
                          builder: (context, child) {
                            return FractionallySizedBox(
                              alignment: Alignment.centerLeft,
                              widthFactor: _loaderAnimation.value,
                              child: Container(
                                decoration: BoxDecoration(
                                  color: green,
                                  borderRadius: BorderRadius.circular(3),
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                      const SizedBox(height: 12),

                      Text(
                        'Opening Mintly…',
                        style: TextStyle(
                          fontSize: 11,
                          color: muted,
                          letterSpacing: 0.2,
                        ),
                      ),
                    ],
                  ),

                  // Footer
                  Column(
                    children: [
                      Text(
                        'DISCOVER · PREPARE · MINT',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 2,
                          color: muted,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Made for your next opportunity.',
                        style: TextStyle(
                          fontSize: 11,
                          color: muted.withValues(alpha: 0.8),
                          letterSpacing: 0.2,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OrbitRingsPainter extends CustomPainter {
  final Color lineColor;
  _OrbitRingsPainter({required this.lineColor});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = lineColor.withValues(alpha: 0.55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    final center = Offset(size.width / 2, size.height / 2);
    // Outer ring
    canvas.drawCircle(center, 280, paint..color = lineColor.withValues(alpha: 0.3));
    // Middle ring
    canvas.drawCircle(center, 210, paint..color = lineColor.withValues(alpha: 0.5));
    // Inner ring
    canvas.drawCircle(center, 140, paint..color = lineColor.withValues(alpha: 0.35));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
