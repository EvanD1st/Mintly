import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';

class SourceScreen extends ConsumerWidget {
  const SourceScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(apiServiceProvider);
    if (!api.isAdmin) {
      return Scaffold(
        appBar: AppBar(title: const Text('Live source')),
        body: const Center(child: Text('Admin access required.')),
      );
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Live source')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: api.fetchSourceStatus(),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(
              child: Text('Source status unavailable: ${snapshot.error}'),
            );
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final source = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                '@lakzonevn on X',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 10),
              Card(
                child: Column(
                  children: [
                    ListTile(
                      title: const Text('Status'),
                      subtitle: Text('${source['status']}'),
                    ),
                    ListTile(
                      title: const Text('Last update'),
                      subtitle: Text('${source['summary_text']}'),
                    ),
                    ListTile(
                      title: const Text('Drops cached'),
                      subtitle: Text('${source['drops_count']}'),
                    ),
                    if (source['last_error'] != null)
                      ListTile(
                        title: const Text('Source error'),
                        subtitle: Text('${source['last_error']}'),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                'This feed contains real source records. Wallet-specific eligibility is not verified by this feed. '
                'Confirm every mint on the official page and in MetaMask.',
              ),
            ],
          );
        },
      ),
    );
  }
}
