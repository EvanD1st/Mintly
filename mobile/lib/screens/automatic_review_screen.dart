import '../widgets/mintly_notice.dart';
import '../theme/compatible_icons.dart';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/drop_model.dart';
import '../models/mint_plan_model.dart';
import '../state/app_state.dart';
import '../services/wat_time.dart';
import 'wallet_setup_screen.dart';

class AutomaticReviewScreen extends ConsumerStatefulWidget {
  final DropModel drop;
  final MintPlanModel? plan;
  final String? copyEventId;
  final String initialMintKind;
  const AutomaticReviewScreen({
    super.key,
    required this.drop,
    this.plan,
    this.copyEventId,
    this.initialMintKind = 'public',
  });
  @override
  ConsumerState<AutomaticReviewScreen> createState() => _AutomaticReviewState();
}

class _AutomaticReviewState extends ConsumerState<AutomaticReviewScreen> {
  late Future<List<Map<String, dynamic>>> _policies;
  late MintStageModel _stage;
  Map<String, dynamic>? _policy;
  final _quantity = TextEditingController(text: '1');
  final _price = TextEditingController();
  final _gas = TextEditingController();
  final _total = TextEditingController();
  final _expiry = TextEditingController();
  late DateTime _mintAt;
  bool _consent = false, _busy = false, _advanced = false;
  Map<String, dynamic>? _review, _request;
  String? _error;

  @override
  void initState() {
    super.initState();
    _stage = widget.drop.stages.firstWhere((stage) => stage.endTimeUtc?.isAfter(DateTime.now().toUtc()) == true, orElse: () => widget.drop.stages.first);
    _quantity.text = '${widget.plan?.quantity ?? 1}';
    _setStage();
    if (widget.plan?.estimatedNetworkFeeEth != null) {
      final amount = widget.plan!.estimatedNetworkFeeEth!.split('.');
      final wei =
          BigInt.parse(amount.first) * BigInt.from(10).pow(18) +
          BigInt.parse((amount.length > 1 ? amount[1] : '').padRight(18, '0'));
      // Review a finite gas ceiling with room for changes after the displayed estimate.
      _gas.text = _eth(
        (wei * BigInt.from(125) + BigInt.from(99)) ~/ BigInt.from(100),
      );
    }
    _policies = _loadPolicies();
  }

  Future<List<Map<String, dynamic>>> _loadPolicies() async {
    final all = await ref.read(apiServiceProvider).fetchAutomaticPolicies();
    final policies = all
        .where(
          (p) =>
              p['status'] == 'enabled' &&
              p['chain_id'] == widget.drop.chainId &&
              (widget.plan == null || p['wallet_id'] == widget.plan!.walletId),
        )
        .toList();
    if (mounted && widget.plan != null && policies.length == 1) {
      setState(() => _policy = policies.single);
      final expiry = DateTime.tryParse('${_policy!['expires_at']}');
      final stageEnd = _stage.endTimeUtc;
      if (expiry != null && stageEnd != null && expiry.isBefore(stageEnd)) {
        _expiry.text = expiry.toUtc().toIso8601String();
      }
    }
    return policies;
  }

  void _setStage() {
    _price.text = _stage.priceEthStr;
    _expiry.text = _stage.endTimeUtc?.toUtc().toIso8601String() ?? '';
    _review = null;
    _request = null;
    _consent = false;
    _mintAt = WatTime.defaultForStage(_stage.startTimeUtc,DateTime.now().toUtc());
  }

  Future<void> _pickMintTime() async {
    if (_busy) return;
    final now = DateTime.now().toUtc();
    DateTime? end = DateTime.tryParse(_expiry.text)?.toUtc() ?? _stage.endTimeUtc?.toUtc();
    for (final limit in [_stage.endTimeUtc?.toUtc(), DateTime.tryParse('${_policy?['expires_at']}')?.toUtc()]) {
      if (limit != null && (end == null || limit.isBefore(end))) end = limit;
    }
    if (end == null || !end.isAfter(now)) {
      setState(() => _error = 'This mint or wallet approval has ended.');
      return;
    }
    final deadline = end;
    final selected = WatTime.wall(_mintAt.isBefore(now) ? now : (_mintAt.isAfter(end) ? end : _mintAt));
    final label = WatTime.label(selected.subtract(const Duration(hours:1))).split(' ');
    final date = TextEditingController(text:label[0]);
    final time = TextEditingController(text:label[1]);
    final form = GlobalKey<FormState>();
    final picked = await showDialog<DateTime>(context:context,builder:(context) => AlertDialog(
      title:const Text('Mint time (WAT)'),
      content:Form(key:form,child:Column(mainAxisSize:MainAxisSize.min,children:[
        TextFormField(key:const Key('mint-date-input'),controller:date,keyboardType:TextInputType.datetime,
          decoration:const InputDecoration(labelText:'Date (DD/MM/YYYY)'),
          validator:(_) => WatTime.parseWall(date.text,time.text) == null ? 'Enter a valid date and time' : null),
        const SizedBox(height:12),
        TextFormField(key:const Key('mint-time-input'),controller:time,keyboardType:TextInputType.datetime,
          decoration:const InputDecoration(labelText:'Time (24-hour HH:MM)',helperText:'WAT · UTC+1; seconds are optional'),
          validator:(_) {
            final value = WatTime.parseWall(date.text,time.text);
            if (value == null) return 'Use HH:MM, for example 12:05';
            if (!value.isAfter(DateTime.now().toUtc())) return 'Choose a future WAT time';
            if (value.isBefore(_stage.startTimeUtc.toUtc())) return 'Stage opens ${WatTime.label(_stage.startTimeUtc)}';
            if (!value.isBefore(deadline)) return 'Choose a time before ${WatTime.label(deadline)}';
            return null;
          }),
      ])),
      actions:[TextButton(onPressed:() => Navigator.pop(context),child:const Text('Cancel')),
        FilledButton(onPressed:() {
          if (form.currentState!.validate()) Navigator.pop(context,WatTime.parseWall(date.text,time.text));
        },child:const Text('Save time'))],
    ));
    // Allow the dialog's closing animation to finish before disposing its input controllers.
    await Future<void>.delayed(const Duration(milliseconds:250));
    date.dispose();
    time.dispose();
    if (picked == null || !mounted) return;
    setState(() {
      _mintAt = picked;
      _review = null;
      _request = null;
      _consent = false;
      _error = null;
    });
  }

  @override
  void dispose() {
    for (final c in [_quantity, _price, _gas, _total, _expiry]) {
      c.dispose();
    }
    super.dispose();
  }

  String _key() => List.generate(
    16,
    (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();

  Future<void> _preview() async {
    if (_busy || _policy == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (!_mintAt.isAfter(DateTime.now().toUtc())) throw const FormatException('Choose a future mint time in WAT.');
      final quantity = int.tryParse(_quantity.text.trim());
      if (quantity == null || quantity < 1 || quantity > 100) throw const FormatException('Choose 1 to 100 NFTs.');
      if (!RegExp(r'^\d+(\.\d{1,18})?$').hasMatch(_total.text.trim())) throw const FormatException('Enter your maximum total spend, including gas.');
      final request = <String, dynamic>{
        if (widget.plan != null) 'plan_id': widget.plan!.id,
        if (widget.copyEventId != null) 'copy_event_id': widget.copyEventId,
        'wallet_id': _policy!['wallet_id'], 'grant_id': _policy!['id'],
        'drop_id': widget.drop.id, 'stage_id': _stage.id, 'quantity': quantity,
        'maximum_total_eth': _total.text.trim(), 'scheduled_for_utc': _mintAt.toIso8601String(),
        if (_advanced && _gas.text.trim().isNotEmpty) 'gas_limit_eth': _gas.text.trim(),
      };
      final review = await ref.read(apiServiceProvider).previewGuidedMint(request);
      if (mounted) {
        setState(() {
          _review = review;
          _request = {
            ...(review['request'] as Map<String,dynamic>),
            'review_hash': review['review_hash'],
            'onchain_stage_index':
                (review['snapshot']
                    as Map<String, dynamic>)['onchain_stage_index'],
            'idempotency_key': _key(),
            'user_consent_confirmed': true,
          };
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = error is FormatException ? error.message : '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _arm() async {
    if (_busy || !_consent || _request == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      // Keep the same request/key after a timeout. Retry cannot create a second mint.
      final task = await ref
          .read(apiServiceProvider)
          .armAutomaticTask(_request!);
      await ref.read(mintlyProvider.notifier).loadInitialData();
      if (!mounted) return;
      MintlyNotice.show(context,
        SnackBar(
          content: Text(
            task.status == 'armed'
                ? 'Automatic mint armed. The server executes while the app is closed.'
                : 'Saved task status: ${task.status}',
          ),
        ),
      );
      Navigator.pop(context, task.status);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _setupWallet() async {
    await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => WalletSetupScreen(
      initialChain: widget.drop.chainId, walletId: widget.plan?.walletId, address: widget.plan?.walletAddress)));
    if (!mounted) return;
    setState(() { _policy = null; _policies = _loadPolicies(); _error = null; });
  }

  String _eth(dynamic wei) {
    final n = BigInt.parse('$wei');
    final scale = BigInt.from(10).pow(18);
    return '${n ~/ scale}.${(n % scale).toString().padLeft(18, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = _review?['snapshot'] as Map<String, dynamic>?;
    return Scaffold(
      appBar: AppBar(title: const Text('Review automatic mint')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            widget.drop.name,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 12),
          const Text(
            'Choose your wallet, NFT quantity, WAT mint time and maximum total spend. Mintly verifies the exact stage and signing approval before you confirm.',
          ),
          if (snapshot == null) ...[
            FutureBuilder<List<Map<String, dynamic>>>(
              future: _policies,
              builder: (context, result) {
                if (result.hasError) return Text('${result.error}');
                if (!result.hasData) return const LinearProgressIndicator();
                final policies = result.data!
                    .where(
                      (p) =>
                          p['status'] == 'enabled' &&
                          p['chain_id'] == widget.drop.chainId,
                    )
                    .toList();
                if (policies.isEmpty) {
                  return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
                    const Text('This network needs an automatic signing approval for your wallet.'),
                    OutlinedButton(onPressed:_busy ? null : _setupWallet,child:const Text('Set up wallet')),
                  ]);
                }
                return DropdownButtonFormField<String>(
                  icon: const RotatedBox(
                    quarterTurns: 1,
                    child: Icon(MintlyIcons.chevronRight),
                  ),
                  initialValue: _policy?['id'] as String?,
                  decoration: const InputDecoration(
                    labelText: 'Minting wallet',
                  ),
                  isExpanded: true,
                  items: policies
                      .map(
                        (p) => DropdownMenuItem(
                          value: p['id'] as String,
                          child: Text(
                            '${p['account']}',
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: _busy
                      ? null
                      : (id) => setState(
                          () => _policy = policies.firstWhere(
                            (p) => p['id'] == id,
                          ),
                        ),
                );
              },
            ),
            Text(_stage.stageName,style:Theme.of(context).textTheme.bodySmall),
            Card(child:ListTile(
              title:const Text('Mint time (WAT)'),
              subtitle:Text(WatTime.label(_mintAt),key:const Key('automatic-mint-time')),
              trailing:TextButton(onPressed:_busy ? null : _pickMintTime,child:const Text('Change time')),
            )),
            if (_stage.startTimeUtc.toUtc().isAfter(DateTime.now().toUtc()))
              TextButton(onPressed:_busy ? null : () => setState(() {
                _mintAt = WatTime.defaultForStage(_stage.startTimeUtc,DateTime.now().toUtc());
                _consent = false;
              }),child:const Text('Use stage opening time')),
            const Text('Time is always WAT. Confirmation can be later than the selected time.',style:TextStyle(fontSize:12)),
            TextField(controller:_quantity,enabled:!_busy,keyboardType:TextInputType.number,
              decoration:const InputDecoration(labelText:'NFT quantity')),
            TextField(controller:_total,enabled:!_busy,keyboardType:const TextInputType.numberWithOptions(decimal:true),
              decoration:const InputDecoration(labelText:'Maximum total spend (ETH)',helperText:'Includes NFT price and all network fees')),
            TextButton(onPressed:_busy ? null : () => setState(() => _advanced = !_advanced),child:Text(_advanced ? 'Hide Advanced' : 'Advanced')),
            if (_advanced) ...[
            DropdownButtonFormField<String>(
              icon: const RotatedBox(
                quarterTurns: 1,
                child: Icon(MintlyIcons.chevronRight),
              ),
              initialValue: _stage.id,
              decoration: const InputDecoration(labelText: 'Exact stage'),
              items: widget.drop.stages
                  .map(
                    (s) =>
                        DropdownMenuItem(value: s.id, child: Text(s.stageName)),
                  )
                  .toList(),
              onChanged: _busy
                  ? null
                  : (id) => setState(() {
                      _stage = widget.drop.stages.firstWhere((s) => s.id == id);
                      _setStage();
                    }),
            ),
              TextField(controller:_gas,enabled:!_busy,keyboardType:const TextInputType.numberWithOptions(decimal:true),
                decoration:const InputDecoration(labelText:'Gas spending limit (ETH, optional)',helperText:'Blank uses the total remaining after NFT cost')),
            ],
            if (_policy == null) const Text('Choose an approved wallet to continue.'),
            FilledButton(onPressed:_busy || _policy == null ? null : _preview,
              child:Text(_busy ? 'Checking mint details…' : 'Review limits')),
          ] else ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Chain: ${snapshot['chain']} (${snapshot['chain_id']})',
                    ),
                    SelectableText('Contract: ${snapshot['contract']}'),
                    SelectableText(
                      'Executing address / recipient: ${snapshot['account']}',
                    ),
                    Text(
                      'Stage: ${snapshot['stage_name']} · ${snapshot['mint_kind'] == 'public' ? 'Public mint' : 'Eligible whitelist mint'}',
                    ),
                    if (_advanced && snapshot['onchain_stage_index'] != null)
                      Text(
                        'Verified stage index: ${snapshot['onchain_stage_index']}',
                      ),
                    Text('Quantity: ${snapshot['quantity']}'),
                    Text('NFT cost: ${_eth(BigInt.parse('${snapshot['price_wei']}') * BigInt.from(snapshot['quantity'] as int))} ETH'),
                    Text('Mint time: ${WatTime.label(snapshot['execute_at'] == null ? _mintAt
                        : DateTime.fromMillisecondsSinceEpoch((snapshot['execute_at'] as int)*1000,isUtc:true))}'),
                    Text(
                      'Price ceiling: ${_eth(snapshot['price_cap_wei'])} ETH',
                    ),
                    Text('Gas budget: ${_eth(snapshot['fee_cap_wei'])} ETH'),
                    Text(
                      'Total ceiling: ${_eth(snapshot['total_cap_wei'])} ETH',
                    ),
                    Text(
                      'Approval ends: ${WatTime.label(DateTime.fromMillisecondsSinceEpoch((snapshot['expiry'] as int) * 1000, isUtc: true))}',
                    ),
                    Text('Eligibility: ${_review!['eligibility']}'),
                  ],
                ),
              ),
            ),
            CheckboxListTile(
              value: _consent,
              onChanged: _busy ? null : (v) => setState(() => _consent = v!),
              title: const Text(
                'I authorize this exact automatic mint and its displayed limits.',
              ),
            ),
            FilledButton(
              onPressed: _busy || !_consent ? null : _arm,
              child: Text(_busy ? 'Saving…' : 'Set automatic'),
            ),
            TextButton(
              onPressed: _busy
                  ? null
                  : () => setState(() {
                      _review = null;
                      _request = null;
                      _consent = false;
                    }),
              child: const Text('Change limits'),
            ),
          ],
          if (_error != null)
            Padding(padding: const EdgeInsets.all(12), child: Text(_error!)),
        ],
      ),
    );
  }
}
