import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import '../services/external_url.dart';
import '../services/wat_time.dart';

class OpenSeaAccessScreen extends ConsumerStatefulWidget {
  final String walletId;
  const OpenSeaAccessScreen({super.key,required this.walletId});
  @override
  ConsumerState<OpenSeaAccessScreen> createState()=>_AccessState();
}
class _AccessState extends ConsumerState<OpenSeaAccessScreen> {
  Map<String,dynamic>? _data;
  bool _consent=false,_busy=false;
  String? _error;
  @override
  void initState(){super.initState();_load();}
  Future<void> _load() async {
    try { final result=await ref.read(apiServiceProvider).fetchOpenSeaAccess(widget.walletId);
      if(mounted) setState((){_data=result;_error=null;});
    } catch(error){if(mounted) setState(()=>_error='$error');}
  }
  Future<void> _change(bool enabled) async {
    if(_busy || (enabled && !_consent)) return;
    setState((){_busy=true;_error=null;});
    try { final result=await ref.read(apiServiceProvider).setOpenSeaAccess(widget.walletId,enabled);
      if(mounted) setState((){_data=result;_consent=false;});
    } catch(error){if(mounted) setState(()=>_error='$error');}
    finally {if(mounted) setState(()=>_busy=false);}
  }
  @override
  Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('OpenSea eligibility')),
    body:ListView(padding:const EdgeInsets.all(20),children:[
      Text('Check your eligible mint phases',style:Theme.of(context).textTheme.headlineSmall),
      const SizedBox(height:12),
      const Text('Mintly signs in to OpenSea with this imported wallet to read its stage eligibility, prices and limits. No private key is sent to OpenSea. Signing in costs no gas and does not approve a mint.'),
      const SizedBox(height:16),
      if(_data==null && _error==null) const LinearProgressIndicator(),
      if(_data!=null) ...[
        Text('Access: ${_data!['status']}',key:const Key('opensea-access-status')),
        if(_data!['expires_at']!=null) Text('Permission ends ${WatTime.label(DateTime.parse('${_data!['expires_at']}'))}'),
        if(_data!['available']!=true) const Text('This address has no signing access. Set up an imported signing wallet first.'),
        if(_data!['available']==true) ...[
          if(_data!['enabled']!=true || _data!['status']!='active') ...[
            CheckboxListTile(contentPadding:EdgeInsets.zero,value:_consent,onChanged:_busy?null:(value)=>setState(()=>_consent=value==true),
              title:const Text('Allow read-only eligibility access'),
              subtitle:const Text('I authorize Mintly to sign the OpenSea login message and renew read-only access within this permission period. I accept OpenSea’s Terms of Service and Privacy Policy.')),
            Wrap(children:[
              TextButton(onPressed:()=>openExternalUrl(context,Uri.parse('https://opensea.io/tos')),child:const Text('OpenSea terms')),
              TextButton(onPressed:()=>openExternalUrl(context,Uri.parse('https://opensea.io/privacy')),child:const Text('Privacy policy')),
            ]),
            FilledButton(onPressed:_busy || !_consent?null:()=>_change(true),child:Text(_busy?'Connecting…':_data!['status']=='disabled'?'Enable eligibility checks':'Reconnect eligibility checks')),
          ],
          if(_data!['enabled']==true || _data!['status']=='revocation_pending')
            OutlinedButton(onPressed:_busy?null:()=>_change(false),child:Text(_busy?'Disconnecting…':'Disconnect eligibility access')),
        ],
      ],
      if(_error!=null) ...[Text(_error!,style:TextStyle(color:Theme.of(context).colorScheme.error)),
        TextButton(onPressed:_busy?null:_load,child:const Text('Refresh access status'))],
      const SizedBox(height:16),
      const Text('Your Mintly account and mint spending approvals remain separate. This connection only reads eligibility for this wallet.'),
    ]));
}
