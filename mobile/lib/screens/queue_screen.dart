import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/colors.dart';
import '../state/app_state.dart';

class QueueScreen extends ConsumerWidget {
  const QueueScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(mintlyProvider);
    final notifier = ref.read(mintlyProvider.notifier);

    final isDark = Theme.of(context).brightness == Brightness.dark;
    final ink = MintlyColors.getInk(isDark);
    final muted = MintlyColors.getMuted(isDark);
    final green = MintlyColors.getGreen(isDark);
    final line = MintlyColors.getLine(isDark);
    final panel = MintlyColors.getPanel(isDark);
    final soft = MintlyColors.getSoft(isDark);

    final hasTasks = state.queue.isNotEmpty;

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      children: [
        Text(
          'PREPARED AHEAD',
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.6,
            color: muted,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          'Mint queue',
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
          hasTasks
              ? 'Your scheduled mints, in one place.'
              : 'Your next mint starts with a plan.',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        const SizedBox(height: 20),

        if (!hasTasks) ...[
          const SizedBox(height: 40),
          Center(
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: soft,
                shape: BoxShape.circle,
              ),
              child: Center(
                child: Icon(Icons.timer_outlined, size: 32, color: green),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Center(
            child: Text(
              'No mints armed yet',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: ink),
            ),
          ),
          const SizedBox(height: 8),
          Center(
            child: Text(
              'Choose a drop, set your budget,\nand review its mint task.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: muted, height: 1.4),
            ),
          ),
        ] else ...[
          ...state.queue.map((task) {
            return Container(
              margin: const EdgeInsets.only(bottom: 14),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: panel,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: line, width: 1),
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: soft,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          '${task.status == 'armed' ? 'Armed' : task.status} · demo',
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: green,
                          ),
                        ),
                      ),
                      Text(
                        task.timeWatLabel,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: ink,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
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
                            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: ink),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            '${task.quantity} NFTs · ${task.chain}',
                            style: TextStyle(fontSize: 12, color: muted),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Container(height: 1, color: line),
                  const SizedBox(height: 10),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Total cap', style: TextStyle(fontSize: 12, color: muted)),
                      Text(
                        '${task.totalCapEth} ETH',
                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: ink),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: () {
                      notifier.disarmTask(task.id);
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('Task disarmed. No transaction was sent.'),
                          duration: Duration(seconds: 2),
                        ),
                      );
                    },
                    child: const Text('Disarm task'),
                  ),
                ],
              ),
            );
          }),
          const SizedBox(height: 8),
          Center(
            child: Text(
              'All times WAT · Scheduled tasks shown are simulated.',
              style: TextStyle(fontSize: 11, color: muted),
            ),
          ),
        ],
        const SizedBox(height: 24),
      ],
    );
  }
}
