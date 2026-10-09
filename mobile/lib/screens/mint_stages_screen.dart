import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/mint_plan_model.dart';
import '../state/app_state.dart';
import '../services/wat_time.dart';
import 'opensea_access_screen.dart';

class MintStagesScreen extends ConsumerStatefulWidget {
  final MintPlanModel plan;
  const MintStagesScreen({super.key,required this.plan});
  @override
  ConsumerState<MintStagesScreen> createState()=>_StagesState();
}
class _StagesState extends ConsumerState<MintStagesScreen> {
  Map<String,dynamic>? _data;
  String? _selected,_error;
  bool _busy=false;
  late final TextEditingController _quantity;
  @override
  void initState(){super.initState();_quantity=TextEditingController(text:'${widget.plan.quantity}');_load();}
  @override
  void dispose(){_quantity.dispose();super.dispose();}
  Future<void> _load() async {
    setState((){_busy=true;_error=null;});
    try {final data=await ref.read(apiServiceProvider).fetchMintStages(widget.plan.id);
      if(mounted) setState((){_data=data;_selected=(data['stages'] as List).where((s)=>s['selected']==true).firstOrNull?['id'] as String?;});
    } catch(error){if(mounted) setState(()=>_error='$error');}
    finally {if(mounted) setState(()=>_busy=false);}
  }
  Future<void> _access() async {
    if(widget.plan.walletId==null) return;
    await Navigator.push(context,MaterialPageRoute(builder:(_)=>OpenSeaAccessScreen(walletId:widget.plan.walletId!)));
    if(mounted) await _load();
  }
  Future<void> _save() async {
    final quantity=int.tryParse(_quantity.text);
    if(quantity==null || quantity<1 || quantity>100){setState(()=>_error='Choose 1 to 100 NFTs.');return;}
    if(_selected==null || _busy) return;
    setState((){_busy=true;_error=null;});
    try {final plan=await ref.read(apiServiceProvider).selectMintStage(widget.plan.id,_selected!,quantity);
      if(mounted) Navigator.pop(context,plan);
    } catch(error){if(mounted) setState(()=>_error='$error');}
    finally {if(mounted) setState(()=>_busy=false);}
  }
  String _price(dynamic value){
    final n=BigInt.tryParse('$value');if(n==null) return 'Price not verified';
    final scale=BigInt.from(10).pow(18);return '${n~/scale}.${(n%scale).toString().padLeft(18,'0')} ETH';
  }
  @override
  Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('Choose mint phase')),
    body:ListView(padding:const EdgeInsets.all(20),children:[
      Text(widget.plan.collectionName,style:Theme.of(context).textTheme.headlineSmall),
      const Text('Choose the phase and quantity you want. Mintly will not switch phases automatically.'),
      if(_busy) const LinearProgressIndicator(),
      if(_data?['note']!=null) Text('${_data!['note']}'),
      if(widget.plan.walletId!=null) OutlinedButton(onPressed:_busy?null:_access,child:const Text('Manage eligibility access')),
      for(final raw in (_data?['stages'] as List? ?? [])) ...[
        Card(child:Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
          Text('${raw['name']}',style:Theme.of(context).textTheme.titleMedium),
          Text('${{'eligible':'Eligible','not_eligible':'Not eligible','unverified':'Not yet verified'}[raw['eligibility']]} · ${raw['timing']}'),
          Text('Opens ${WatTime.label(DateTime.parse('${raw['starts_at']}'))}'),
          Text(_price(raw['price_wei'])),
          Text(raw['remaining']==null?'Your remaining allowance: not verified':'Available for your wallet: ${raw['remaining']} NFTs'),
          Text('Stage default allocation: ${raw['default_limit']} NFTs',style:Theme.of(context).textTheme.bodySmall),
          OutlinedButton(onPressed:_busy || raw['timing']=='ended' || raw['eligibility']=='not_eligible'?null:()=>setState(()=>_selected='${raw['id']}'),
            child:Text(_selected==raw['id']?'Selected phase':'Choose this phase')),
        ]))),
      ],
      TextField(controller:_quantity,enabled:!_busy,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'NFT quantity')),
      if(_error!=null) Text(_error!,style:TextStyle(color:Theme.of(context).colorScheme.error)),
      FilledButton(onPressed:_busy || _selected==null?null:_save,child:const Text('Continue with this phase')),
      const Text('Eligibility and remaining supply can change. Exact wallet proofs and spending limits must pass before arming. A GTD label does not guarantee transaction success.'),
    ]));
}
