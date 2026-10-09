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
import 'mint_stages_screen.dart';

class SavedPlanScreen extends ConsumerStatefulWidget {
  final MintPlanModel plan;
  const SavedPlanScreen({super.key, required this.plan});
  @override
  ConsumerState<SavedPlanScreen> createState() => _SavedPlanState();
}

class _SavedPlanState extends ConsumerState<SavedPlanScreen> {
  late MintPlanModel _plan;
  @override
  void initState(){super.initState();_plan=widget.plan;}
  bool _busy = false;
  String? _taskStatus;
  Future<void> _continue() async {
    setState(() => _busy = true);
    try {
      final data = await ref.read(apiServiceProvider).automaticPlanContext(_plan.id);
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
      Text(_plan.collectionName,style:Theme.of(context).textTheme.headlineSmall),
      Text('${_plan.quantity} NFT(s) · ${_plan.chain}'),
      if (_plan.startsAt != null) Text('Opens ${WatTime.label(_plan.startsAt!)}'),
      Text(_taskStatus == null ? _plan.statusNote : 'Automatic mint: $_taskStatus. Follow its progress in Activity.'),
      const SizedBox(height:16),
      if (_taskStatus == null) OutlinedButton(onPressed:_busy?null:() async {
        final selected=await Navigator.push<MintPlanModel>(context,MaterialPageRoute(builder:(_)=>MintStagesScreen(plan:_plan)));
        if(mounted && selected!=null) setState(()=>_plan=selected);
      },child:const Text('Choose mint phase')),
      if (_taskStatus == null) FilledButton(onPressed:_busy ? null : _continue,child:Text(_busy ? 'Checking plan…' : 'Continue to automatic mint')),
      if (_taskStatus != null) OutlinedButton(onPressed:() => Navigator.push(context,MaterialPageRoute(builder:(_) => const HistoryScreen())),child:const Text('View activity')),
      const SizedBox(height:16),const AutomationControl(),
    ]));
}
