import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/drop_model.dart';
import '../models/task_model.dart';
import '../models/activity_model.dart';

class ApiService {
  static String baseUrl = const String.fromEnvironment(
    'MINTLY_API_URL', defaultValue: 'https://mintly.duckdns.org/api');
  final http.Client _client;
  String _ownerToken = '';
  bool get isLiveBackendConnected => _ownerToken.isNotEmpty;

  ApiService({http.Client? client}) : _client = client ?? http.Client();

  // Session-only credential: never embedded in an APK or stored in plain text.
  Future<void> connectBackend(String token) async {
    final uri = Uri.parse(baseUrl);
    if (uri.scheme != 'https') {
      throw Exception('A secure HTTPS server address is required.');
    }
    final candidate = token.trim();
    if (candidate.isEmpty) throw Exception('Enter your server access token.');
    final response = await _client.get(Uri.parse('$baseUrl/wallets'),
      headers: {'Authorization': 'Bearer $candidate'}).timeout(const Duration(seconds: 10));
    _checkResponse(response);
    _ownerToken = candidate;
  }

  void disconnectBackend() { _ownerToken = ''; }
  void dispose() { _client.close(); }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer $_ownerToken',
  };

  void _checkResponse(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(response.statusCode == 401
        ? 'Server access token is invalid.'
        : 'Server request failed (${response.statusCode}). Please refresh before retrying.');
    }
  }

  Future<dynamic> _get(String path) async {
    final response = await _client.get(Uri.parse('$baseUrl$path'), headers: _headers)
      .timeout(const Duration(seconds: 10));
    _checkResponse(response);
    return jsonDecode(response.body);
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final response = await _client.post(Uri.parse('$baseUrl$path'), headers: _headers,
      body: jsonEncode(body)).timeout(const Duration(seconds: 10));
    _checkResponse(response);
    return jsonDecode(response.body);
  }

  // In-memory demo state matching mintly-splash-reference.html
  final List<DropModel> _demoDrops = [
    DropModel(
      id: 'orbit',
      name: 'Orbit Bloom',
      chain: 'Base',
      chainId: 8453,
      contractAddress: '0x1234567890123456789012345678901234567890',
      mintPageUrl: 'https://opensea.io/collection/orbit-bloom',
      siteLabel: 'OpenSea',
      iconName: 'flower-2',
      statusLabel: 'Presale eligible',
      statusKind: 'eligible',
      isSupportedIntegration: true,
      isDemo: true,
      stages: [
        MintStageModel(
          id: 'orbit-wl',
          dropId: 'orbit',
          stageName: 'Allowlist',
          startTimeUtc: DateTime.now().toUtc(),
          priceWei: 200000000000000,
          priceEthStr: '0.0002',
          limitPerWallet: 3,
          eligibilityStatus: 'eligible',
          eligibilityEvidence: 'Allowlist verified for Jenny',
        ),
        MintStageModel(
          id: 'orbit-pub',
          dropId: 'orbit',
          stageName: 'Public',
          startTimeUtc: DateTime.now().toUtc().add(const Duration(hours: 2)),
          priceWei: 400000000000000,
          priceEthStr: '0.0004',
          limitPerWallet: 5,
          eligibilityStatus: 'eligible',
        ),
      ],
    ),
    DropModel(
      id: 'paper',
      name: 'Paper Planets',
      chain: 'Ethereum',
      chainId: 1,
      contractAddress: '0x2345678901234567890123456789012345678901',
      mintPageUrl: 'https://opensea.io/collection/paper-planets',
      siteLabel: 'OpenSea',
      iconName: 'gem',
      statusLabel: 'Public stage',
      statusKind: 'eligible',
      isSupportedIntegration: true,
      isDemo: true,
      stages: [
        MintStageModel(
          id: 'paper-pub',
          dropId: 'paper',
          stageName: 'Public',
          startTimeUtc: DateTime.now().toUtc().add(const Duration(hours: 1)),
          priceWei: 800000000000000,
          priceEthStr: '0.0008',
          limitPerWallet: 5,
          eligibilityStatus: 'eligible',
        ),
      ],
    ),
    DropModel(
      id: 'midnight',
      name: 'Midnight Club',
      chain: 'Base',
      chainId: 8453,
      contractAddress: null,
      mintPageUrl: 'https://midnightclub.xyz/mint',
      siteLabel: 'Project website',
      iconName: 'moon-star',
      statusLabel: 'Manual check',
      statusKind: 'manual',
      isSupportedIntegration: false,
      manualNotice: "This project's eligibility checker isn't supported yet.",
      isDemo: true,
      stages: [
        MintStageModel(
          id: 'midnight-unverified',
          dropId: 'midnight',
          stageName: 'Unverified',
          startTimeUtc: DateTime.now().toUtc().add(const Duration(hours: 2)),
          priceWei: 400000000000000,
          priceEthStr: '0.0004',
          limitPerWallet: 1,
          eligibilityStatus: 'manual_check',
          eligibilityEvidence: 'Independent website',
        ),
      ],
    ),
  ];

  final List<MintTaskModel> _demoTasks = [];
  final List<ActivityModel> _demoActivities = [
    ActivityModel(
      id: '1',
      eventType: 'scan',
      label: 'Eligibility scan complete',
      detail: '2 drops eligible · 1 needs manual review',
      iconName: 'shield-check',
      isDemo: true,
      formattedTime: '17:03',
    ),
    ActivityModel(
      id: '2',
      eventType: 'discovery',
      label: 'Daily list imported',
      detail: 'LAKZONE · 3 sample drops',
      iconName: 'download',
      isDemo: true,
      formattedTime: '17:02',
    ),
  ];

  bool isMonitoring = true;

  Future<List<DropModel>> fetchDrops(String filter) async {
    if (isLiveBackendConnected) {
      final data = await _get('/drops?filter_kind=$filter');
      return (data['drops'] as List).map((d) => DropModel.fromJson(d)).toList();
    }

    // Explicit offline demo mode
    if (filter == 'eligible') {
      return _demoDrops.where((d) => d.statusKind == 'eligible').toList();
    } else if (filter == 'manual') {
      return _demoDrops.where((d) => d.statusKind == 'manual').toList();
    }
    return _demoDrops;
  }

  Future<List<MintTaskModel>> fetchQueue() async {
    if (isLiveBackendConnected) {
      final data = await _get('/tasks/queue');
      return (data['tasks'] as List).map((t) => MintTaskModel.fromJson(t)).toList();
    }
    return _demoTasks;
  }

  Future<MintTaskModel> armTask({
    required DropModel drop,
    required MintStageModel stage,
    required int quantity,
    required String feeCapEth,
  }) async {
    if (isLiveBackendConnected) {
      final data = await _post('/tasks/arm', {
        'wallet_id': 'demo_wallet',
        'drop_id': drop.id,
        'stage_id': stage.id,
        'quantity': quantity,
        'fee_cap_eth': feeCapEth,
        'user_consent_confirmed': true,
        'idempotency_key': 'key_${DateTime.now().microsecondsSinceEpoch}',
      });
      return MintTaskModel.fromJson(data);
    }

    // Demo task arming
    double unitPrice = double.tryParse(stage.priceEthStr) ?? 0.0;
    double fee = double.tryParse(feeCapEth) ?? 0.0001;
    double total = (quantity * unitPrice) + fee;

    final task = MintTaskModel(
      id: 'task_${DateTime.now().millisecondsSinceEpoch}',
      walletId: 'demo_wallet',
      dropId: drop.id,
      stageId: stage.id,
      status: 'armed',
      isDemo: true,
      scheduledForUtc: stage.startTimeUtc,
      quantity: quantity,
      unitPriceEth: stage.priceEthStr,
      feeCapEth: feeCapEth,
      totalCapEth: total.toStringAsFixed(6).replaceAll(RegExp(r'0+$'), '').replaceAll(RegExp(r'\.$'), ''),
      dropName: drop.name,
      chain: drop.chain,
      stageName: stage.stageName,
      timeWatLabel: '${stage.startTimeUtc.hour.toString().padLeft(2, '0')}:00 WAT',
      iconName: drop.iconName,
    );

    _demoTasks.removeWhere((t) => t.dropId == drop.id);
    _demoTasks.insert(0, task);
    _demoActivities.insert(0, ActivityModel(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      eventType: 'task_armed',
      label: 'Demo task armed',
      detail: '${drop.name} · $quantity NFTs',
      iconName: 'timer',
      isDemo: true,
      formattedTime: 'Now',
    ));
    return task;
  }

  Future<void> disarmTask(String taskId) async {
    if (isLiveBackendConnected) {
      await _post('/tasks/$taskId/disarm', {});
      return;
    }

    final idx = _demoTasks.indexWhere((t) => t.id == taskId);
    if (idx != -1) {
      final t = _demoTasks.removeAt(idx);
      _demoActivities.insert(0, ActivityModel(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        eventType: 'task_disarmed',
        label: 'Demo task disarmed',
        detail: t.dropName,
        iconName: 'circle-pause',
        isDemo: true,
        formattedTime: 'Now',
      ));
    }
  }

  Future<List<ActivityModel>> fetchActivity() async {
    if (isLiveBackendConnected) {
      final data = await _get('/activity');
      return (data as List).map((a) => ActivityModel.fromJson(a)).toList();
    }
    return _demoActivities;
  }

  Future<bool> importDrop(String text) async {
    if (!isLiveBackendConnected) return false;
    await _post('/drops/import', {
      'raw_content': text,
      'source_author': 'lakzonevn',
    });
    return true;
  }
}
