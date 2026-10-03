import 'dart:math';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/drop_model.dart';
import '../state/app_state.dart';

class AutomaticReviewScreen extends ConsumerStatefulWidget {
  final DropModel drop;
  const AutomaticReviewScreen({super.key, required this.drop});
  @override
  ConsumerState<AutomaticReviewScreen> createState() => _AutomaticReviewState();
}

class _AutomaticReviewState extends ConsumerState<AutomaticReviewScreen> {
  late Future<List<Map<String, dynamic>>> _policies;
  late MintStageModel _stage;
  Map<String, dynamic>? _policy;
  final _quantity = TextEditingController(text: '1');
  final _price = TextEditingController();
  final _gas = TextEditingController(text: '0.001');
  final _total = TextEditingController();
  final _expiry = TextEditingController();
  final _stageIndex = TextEditingController();
  String _kind = 'public';
  bool _conditional = false, _consent = false, _busy = false;
  Map<String, dynamic>? _review, _request;
  String? _error;

  @override
  void initState() {
    super.initState();
    _stage = widget.drop.stages.first;
    _setStage();
    _policies = ref.read(apiServiceProvider).fetchAutomaticPolicies();
  }

  void _setStage() {
    _price.text = _stage.priceEthStr;
    _expiry.text = _stage.endTimeUtc?.toUtc().toIso8601String() ?? '';
    _review = null;
    _request = null;
    _consent = false;
  }

  @override
  void dispose() {
    for (final c in [_quantity, _price, _gas, _total, _expiry, _stageIndex]) {
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
      final expiry = DateTime.parse(_expiry.text).toUtc();
      final request = <String, dynamic>{
        'wallet_id': _policy!['wallet_id'],
        'grant_id': _policy!['id'],
        'drop_id': widget.drop.id,
        'stage_id': _stage.id,
        'quantity': int.parse(_quantity.text),
        'price_cap_eth': _price.text,
        'fee_cap_eth': _gas.text,
        if (_total.text.isNotEmpty) 'total_cap_eth': _total.text,
        'expires_at': expiry.toIso8601String(),
        'mint_kind': _kind,
        'conditional_eligibility': _conditional,
        if (_conditional && _kind != 'public')
          'onchain_stage_index': int.parse(_stageIndex.text),
      };
      final review = await ref
          .read(apiServiceProvider)
          .previewAutomaticTask(request);
      if (mounted) {
        setState(() {
          _review = review;
          _request = {
            ...request,
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
      if (mounted) setState(() => _error = '$error');
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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            task.status == 'armed'
                ? 'Automatic mint armed. The server executes while the app is closed.'
                : 'Saved task status: ${task.status}',
          ),
        ),
      );
      Navigator.pop(context);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
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
            'Custodial execution uses your imported wallet address. The isolated server signer holds its key. Limits are enforced by Mintly, not by an on-chain MetaMask permission.',
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
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: 16),
                    child: Text(
                      'Import a wallet for this network from Wallets → Set up automatic minting, then return to review this mint.',
                    ),
                  );
                }
                return DropdownButtonFormField<String>(
                  icon: const RotatedBox(
                    quarterTurns: 1,
                    child: Icon(Icons.chevron_right),
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
            DropdownButtonFormField<String>(
              icon: const RotatedBox(
                quarterTurns: 1,
                child: Icon(Icons.chevron_right),
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
            DropdownButtonFormField<String>(
              icon: const RotatedBox(
                quarterTurns: 1,
                child: Icon(Icons.chevron_right),
              ),
              initialValue: _kind,
              decoration: const InputDecoration(labelText: 'Mint method'),
              items: const [
                DropdownMenuItem(value: 'public', child: Text('Public')),
                DropdownMenuItem(
                  value: 'allowlist',
                  child: Text('Merkle allowlist'),
                ),
                DropdownMenuItem(
                  value: 'signed',
                  child: Text('Signed presale'),
                ),
              ],
              onChanged: _busy
                  ? null
                  : (value) => setState(() => _kind = value!),
            ),
            for (final field in [
              (_quantity, 'Quantity'),
              (_price, 'Price ceiling per NFT (ETH)'),
              (_gas, 'Gas budget (ETH)'),
              (_total, 'Total ceiling (ETH; blank = price × quantity + gas)'),
              (_expiry, 'Submission expiry (ISO date/time with Z or offset)'),
            ])
              TextField(
                controller: field.$1,
                enabled: !_busy,
                decoration: InputDecoration(labelText: field.$2),
              ),
            CheckboxListTile(
              value: _conditional,
              onChanged: _busy
                  ? null
                  : (v) => setState(() => _conditional = v!),
              title: const Text('Allow a conditional presale attempt'),
              subtitle: const Text(
                'Wallet eligibility may depend on provider data available only at opening. Invalid proofs never proceed to signing.',
              ),
            ),
            if (_conditional && _kind != 'public')
              TextField(
                controller: _stageIndex,
                enabled: !_busy,
                decoration: const InputDecoration(
                  labelText: 'Verified on-chain presale stage index',
                  helperText:
                      'Use the collection’s published stage index. Do not guess.',
                ),
              ),
            FilledButton(
              onPressed: _busy ? null : _preview,
              child: const Text('Review limits'),
            ),
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
                      'Stage: ${snapshot['stage_name']} · ${snapshot['mint_kind']}',
                    ),
                    if (snapshot['onchain_stage_index'] != null)
                      Text(
                        'Verified stage index: ${snapshot['onchain_stage_index']}',
                      ),
                    Text('Quantity: ${snapshot['quantity']}'),
                    Text(
                      'Price ceiling: ${_eth(snapshot['price_cap_wei'])} ETH',
                    ),
                    Text('Gas budget: ${_eth(snapshot['fee_cap_wei'])} ETH'),
                    Text(
                      'Total ceiling: ${_eth(snapshot['total_cap_wei'])} ETH',
                    ),
                    Text(
                      'Expiry: ${DateTime.fromMillisecondsSinceEpoch((snapshot['expiry'] as int) * 1000, isUtc: true)}',
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
              child: Text(_busy ? 'Saving…' : 'Arm automatic mint'),
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
