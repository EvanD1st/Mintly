import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'package:intl/intl.dart';

class SourceScreen extends ConsumerWidget {
  const SourceScreen({super.key});
  String _wat(dynamic value) {
    final time = DateTime.tryParse('$value');
    return time == null
        ? 'Not yet connected'
        : '${DateFormat('d MMM HH:mm').format(time.toUtc().add(const Duration(hours: 1)))} WAT';
  }

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
                'Mint sources on X',
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
              for (final post in (source['pending_posts'] as List? ?? []))
                ListTile(
                  title: Text('Saved list from @${post['author']}'),
                  subtitle: Text('${post['note']}'),
                  trailing: TextButton(
                    child: const Text('Retry'),
                    onPressed: () async {
                      try {
                        await api.retrySourcePost('${post['id']}');
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text(
                                'Saved list queued for processing.',
                              ),
                            ),
                          );
                        }
                      } catch (error) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(
                            context,
                          ).showSnackBar(SnackBar(content: Text('$error')));
                        }
                      }
                    },
                  ),
                ),
              for (final entry in (source['sources'] as List? ?? []))
                Card(
                  child: ListTile(
                    title: Text('@${entry['name']}'),
                    subtitle: Text(
                      '${entry['status']}\nLast successful check: ${_wat(entry['last_sync_at'])}'
                      '${entry['last_error'] == null ? '' : '\n${entry['last_error']}'}',
                    ),
                  ),
                ),
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
