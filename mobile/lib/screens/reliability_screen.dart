import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';

final reliabilityProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, (String, int)>((ref, key) async {
      final api = ref.read(apiServiceProvider);
      if (!api.isAdmin || key != (api.userId, api.sessionRevision)) {
        throw StateError('Administrator access required.');
      }
  Timer? timer;
  void scheduleRefresh() {
    timer?.cancel();
    timer = Timer(const Duration(minutes: 1), ref.invalidateSelf);
  }
  scheduleRefresh();
  ref.onCancel(() => timer?.cancel());
  ref.onResume(scheduleRefresh);
  ref.onDispose(() => timer?.cancel());
      final result = await api.fetchReliability();
      if (!api.isAdmin || key != (api.userId, api.sessionRevision)) {
        throw StateError('Account changed. Open the report again.');
      }
      return result;
    });

class ReliabilityNotice extends ConsumerWidget {
  const ReliabilityNotice({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiServiceProvider);
    if (!api.isAdmin) return const SizedBox.shrink();
    final data = ref.watch(
      reliabilityProvider((api.userId, api.sessionRevision)),
    );
    final value = data.asData?.value;
    final reviewNeeded = (value?['failures_needing_review'] as num? ?? 0) > 0 ||
        (value?['eligible_closed_without_task'] as num? ?? 0) > 0 ||
        (value?['unarmed_reasons'] as Map? ?? {}).entries.any((e) =>
            e.key != 'budget_wait' && e.key != 'daily_budget_wait' && (e.value as num) > 0);
    final count =
        ((value?['incidents'] as List?)?.length ?? 0) +
        (((value?['auto_arm_waiting'] as Map?)?['signing_approval_unavailable']
                        as num? ??
                    0) >
                0
            ? 1
            : 0);
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(
        count > 0
            ? '$count reliability warning${count == 1 ? '' : 's'}'
            : reviewNeeded ? 'Mint reliability needs review' : 'Mint reliability',
      ),
      subtitle: Text(
        data.hasError
            ? 'Report could not refresh. Tap to retry.'
            : count > 0
            ? 'Recurring failures need review.'
            : 'Attempts, timing and recurring failures.',
      ),
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const ReliabilityScreen()),
      ),
    );
  }
}

class ReliabilityScreen extends ConsumerWidget {
  const ReliabilityScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(mintlyProvider);
    final api = ref.watch(apiServiceProvider);
    if (!api.isAdmin) {
      return const Scaffold(
        body: Center(child: Text('Administrator access required.')),
      );
    }
    final key = (api.userId, api.sessionRevision);
    final report = ref.watch(reliabilityProvider(key));
    return Scaffold(
      appBar: AppBar(title: const Text('Mint reliability')),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(reliabilityProvider(key));
          try {
            await ref.read(reliabilityProvider(key).future);
          } catch (_) {
            /* Shown below. */
          }
        },
        child: ListView(
          padding: const EdgeInsets.all(20),
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            const Text(
              'Last 24 hours',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            const Text(
              'Updates every minute. Pull down to refresh. Times use WAT.',
            ),
            const SizedBox(height: 16),
            ...report.when(
              loading: () => [const LinearProgressIndicator()],
              error: (_, _) => [
                const Text('Could not load reliability. Pull down to retry.'),
              ],
              data: (data) => _report(data),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _report(Map<String, dynamic> data) {
    final incidents = data['incidents'] as List? ?? [];
    final outcomes = data['outcomes'] as Map? ?? {};
    final modes = data['modes'] as Map? ?? {};
    return [
      _fact(
        'Verified Auto-Arming opportunities',
        data['eligible_auto_arm_collections'] ?? 0,
      ),
      _fact(
        'Opportunities with an armed task',
        data['eligible_with_task'] ?? 0,
      ),
      _fact('Eligible but no task found', data['eligible_without_task'] ?? 0),
      _fact(
        'Closed without a task (review)',
        data['eligible_closed_without_task'] ?? 0,
      ),
      _fact('Failures needing review', data['failures_needing_review'] ?? 0),
      if (data['observation_started_at'] == null)
        const Text(
          'No verified opportunities have been recorded yet. Older opportunities are not included.',
        )
      else
        Text(
          'Opportunity measurement started ${_wat('${data['observation_started_at']}')}. Earlier opportunities are not included.',
        ),
      const SizedBox(height: 20),
      const Text(
        'Warnings',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
      ),
      if (incidents.isEmpty)
        const Text('No recent recurring failure threshold has been reached.'),
      for (final incident in incidents)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Text(
              '${incident['reason_text'] ?? _label('${incident['reason_code']}')} · chain ${incident['chain_id']}\n'
              '${incident['affected_tasks']} task(s), ${incident['affected_opportunities'] ?? 0} unarmed opportunity(s) · last seen ${_wat('${incident['last_seen']}')}\n'
              '${(incident['examples'] as List? ?? []).map((e) => '${e['username']} · ${e['collection']}').join('\n')}',
            ),
          ),
        ),
      const SizedBox(height: 20),
      const Text(
        'Outcomes',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
      ),
      if (outcomes.isEmpty) const Text('No mint tasks opened in this window.'),
      for (final entry in outcomes.entries)
        _fact(_label('${entry.key}'), entry.value),
      ExpansionTile(
        title: const Text('Recent outcomes needing review'),
        children: [
          for (final failure in data['recent_failures'] as List? ?? [])
            ListTile(
              title: Text('${failure['username']} · ${failure['collection']}'),
              subtitle: Text('${failure['reason_text'] ?? failure['outcome']}'),
            ),
        ],
      ),
      const SizedBox(height: 20),
      const Text(
        'Auto-Arming waits',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
      ),
      for (final entry in (data['auto_arm_waiting'] as Map? ?? {}).entries)
        _fact(_label('${entry.key}'), entry.value),
      const Text(
        'Current eligibility checks',
        style: TextStyle(fontWeight: FontWeight.w600),
      ),
      for (final entry in (data['eligibility_checks'] as Map? ?? {}).entries)
        _fact(_label('${entry.key}'), entry.value),
      for (final entry in (data['unarmed_reasons'] as Map? ?? {}).entries)
        _fact('Unarmed: ${_label('${entry.key}')}', entry.value),
      const SizedBox(height: 20),
      const Text(
        'Submission timing',
        style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
      ),
      for (final entry in modes.entries) ...[
        Text(
          _label('${entry.key}'),
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        _fact(
          'Tasks / submitted / confirmed',
          '${entry.value['tasks']} / ${entry.value['submitted']} / ${entry.value['confirmed']}',
        ),
        _timing(
          entry.value['opening_to_submission'] ??
              entry.value['activity_to_submission'],
          '${entry.key}' == 'copy',
        ),
        const SizedBox(height: 12),
      ],
      const SizedBox(height: 16),
      for (final note in data['notes'] as List? ?? [])
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Text('$note'),
        ),
    ];
  }

  Widget _timing(dynamic value, bool copy) {
    final data = value as Map? ?? {};
    return Text(
      '${copy ? 'Activity detected' : 'Opening'} to submission: '
      '${data['samples'] ?? 0} samples\nMedian ${data['p50_seconds'] ?? '—'}s · 95th percentile ${data['p95_seconds'] ?? '—'}s',
    );
  }

  Widget _fact(String label, dynamic value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(
      children: [
        Expanded(child: Text(label)),
        const SizedBox(width: 12),
        Text('$value'),
      ],
    ),
  );
  String _label(String value) => value.replaceAll('_', ' ');
  String _wat(String value) {
    final date = DateTime.tryParse(
      value,
    )?.toUtc().add(const Duration(hours: 1));
    if (date == null) return 'unknown time';
    return '${date.day}/${date.month} ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')} WAT';
  }
}
