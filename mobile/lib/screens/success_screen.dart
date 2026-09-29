import 'package:flutter/material.dart';
import '../theme/colors.dart';
import '../models/task_model.dart';
import 'main_shell.dart';

class SuccessScreen extends StatelessWidget {
  final MintTaskModel task;

  const SuccessScreen({super.key, required this.task});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bg = MintlyColors.getBg(isDark);
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

    return Scaffold(
      backgroundColor: bg,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
          children: [
            const SizedBox(height: 16),
            // Big Checkmark
            Center(
              child: Container(
                width: 68,
                height: 68,
                decoration: BoxDecoration(
                  color: soft,
                  shape: BoxShape.circle,
                ),
                child: Center(
                  child: Icon(Icons.check, size: 36, color: green),
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Header Texts
            Center(
              child: Column(
                children: [
                  Text(
                    'TASK SAVED',
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.6,
                      color: muted,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'You’re ready.',
                    style: TextStyle(
                      fontSize: 28,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -0.8,
                      color: ink,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Your demo mint is queued for ${task.timeWatLabel}.',
                    style: TextStyle(fontSize: 14, color: muted),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 28),

            // Drop Card
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: panel,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: line, width: 1),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Container(
                        width: 48,
                        height: 48,
                        decoration: BoxDecoration(
                          color: soft,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Center(
                          child: Icon(Icons.filter_vintage_outlined, size: 24, color: green),
                        ),
                      ),
                      const SizedBox(width: 14),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            task.dropName,
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: ink),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${task.quantity} NFTs · ${task.stageName}',
                            style: TextStyle(fontSize: 12, color: muted),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Container(height: 1, color: line),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Maximum spend', style: TextStyle(fontSize: 12, color: muted)),
                      Text(
                        '${task.totalCapEth} ETH',
                        style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ink),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Notice
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
                'In the finished app, the server handles armed tasks even when the app is closed. This preview sends nothing.',
                style: TextStyle(fontSize: 12, color: ink, height: 1.4),
              ),
            ),
            const SizedBox(height: 32),

            // Action Buttons
            ElevatedButton(
              onPressed: () {
                Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const MainShell()),
                  (route) => false,
                );
              },
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text('View mint queue'),
                  SizedBox(width: 8),
                  Icon(Icons.arrow_forward, size: 16),
                ],
              ),
            ),
            const SizedBox(height: 10),

            OutlinedButton(
              onPressed: () {
                Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const MainShell()),
                  (route) => false,
                );
              },
              child: const Text('Discover more drops'),
            ),
          ],
        ),
      ),
    );
  }
}
