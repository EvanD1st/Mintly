import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/mint_plan_model.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';
import '../services/api_service.dart';
import '../services/wat_time.dart';
import '../widgets/mintly_notice.dart';
import '../widgets/automation_control.dart';
import 'automatic_review_screen.dart';
import 'history_screen.dart';

class SavedPlanScreen extends ConsumerStatefulWidget {
  final MintPlanModel plan;
  const SavedPlanScreen({super.key, required this.plan});
  @override
  ConsumerState<SavedPlanScreen> createState() => _SavedPlanState();
}

class _SavedPlanState extends ConsumerState<SavedPlanScreen> {
  bool _busy = false;
  String? _taskStatus;
  Future<void> _continue() async {
    setState(() => _busy = true);
    try {
      final data = await ref.read(apiServiceProvider).automaticPlanContext(widget.plan.id);
      if (!mounted) return;
      final drop = DropModel.fromJson(data['drop'] as Map<String,dynamic>);
      if (drop.stages.isEmpty) throw const ApiException('Verified stage details are not available yet. Refresh this plan later.');
      final status = await Navigator.push<String>(context, MaterialPageRoute(builder: (_) => AutomaticReviewScreen(
        drop:drop,plan:MintPlanModel.fromJson(data['plan'] as Map<String,dynamic>))));
      if (mounted && status != null) setState(() => _taskStatus = status);
    } catch (error) {
      if (mounted) MintlyNotice.show(context, SnackBar(content:Text('$error')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
  @override
  Widget build(BuildContext context) => Scaffold(appBar:AppBar(title:const Text('Saved mint plan')),
    body:ListView(padding:const EdgeInsets.all(20),children:[
      Text(widget.plan.collectionName,style:Theme.of(context).textTheme.headlineSmall),
      Text('${widget.plan.quantity} NFT(s) · ${widget.plan.chain}'),
      if (widget.plan.startsAt != null) Text('Opens ${WatTime.label(widget.plan.startsAt!)}'),
      Text(_taskStatus == null ? widget.plan.statusNote : 'Automatic mint: $_taskStatus. Follow its progress in Activity.'),
      const SizedBox(height:16),
      if (_taskStatus == null) FilledButton(onPressed:_busy ? null : _continue,child:Text(_busy ? 'Checking plan…' : 'Continue to automatic mint')),
      if (_taskStatus != null) OutlinedButton(onPressed:() => Navigator.push(context,MaterialPageRoute(builder:(_) => const HistoryScreen())),child:const Text('View activity')),
      const SizedBox(height:16),const AutomationControl(),
    ]));
}
