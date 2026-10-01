import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/drop_model.dart';
import '../models/task_model.dart';
import '../models/activity_model.dart';
import '../models/mint_plan_model.dart';

class ApiException implements Exception {
  final String message;
  const ApiException(this.message);
  @override
  String toString() => message;
}

class ApiService extends ChangeNotifier {
  static String baseUrl = const String.fromEnvironment(
    'MINTLY_API_URL', defaultValue: 'https://mintly.duckdns.org/api');
  final http.Client _client;
  String _sessionToken = '';
  Map<String, dynamic>? _user;
  String sourceStatusText = 'Waiting for live data';
  String checkedWalletLabel = 'No wallet connected';
  String lastCheckedText = 'Wallet-specific eligibility is unverified';

  ApiService({http.Client? client}) : _client = client ?? http.Client();

  bool get isLiveBackendConnected => _sessionToken.isNotEmpty;
  String get username => _user?['username'] as String? ?? '';
  bool get isAdmin => _user?['role'] == 'admin';
  bool get mustChangePassword => _user?['must_change_password'] == true;

  void _requireHttps() {
    if (Uri.parse(baseUrl).scheme != 'https') {
      throw StateError('A secure HTTPS server address is required.');
    }
  }

  Map<String, String> get _headers {
    if (!isLiveBackendConnected) throw StateError('Sign in to Mintly first.');
    return {'Content-Type': 'application/json', 'Authorization': 'Bearer $_sessionToken'};
  }

  dynamic _decode(http.Response response) {
    dynamic data;
    try { data = jsonDecode(response.body); } catch (_) { data = null; }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = data is Map ? data['detail'] : null;
      throw ApiException(detail is String ? detail : 'Server request failed (${response.statusCode}).');
    }
    return data;
  }

  Future<void> login(String username, String password) async {
    _requireHttps();
    final response = await _client.post(Uri.parse('$baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username.trim(), 'password': password}),
    ).timeout(const Duration(seconds: 15));
    final result = _decode(response) as Map<String, dynamic>;
    _sessionToken = result['token'] as String;
    _user = result['user'] as Map<String, dynamic>;
    notifyListeners();
  }

  Future<void> changePassword(String oldPassword, String newPassword) async {
    await _post('/auth/change-password', {
      'current_password': oldPassword, 'new_password': newPassword,
    });
    disconnectBackend();
  }

  Future<void> logout() async {
    try { if (isLiveBackendConnected) await _post('/auth/logout', {}); }
    finally { disconnectBackend(); }
  }

  void disconnectBackend() {
    _sessionToken = '';
    _user = null;
    notifyListeners();
  }

  @override
  void dispose() { _client.close(); super.dispose(); }

  Future<dynamic> _get(String path) async {
    _requireHttps();
    final response = await _client.get(Uri.parse('$baseUrl$path'), headers: _headers)
      .timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body,
      {Duration timeout = const Duration(seconds: 15)}) async {
    _requireHttps();
    final response = await _client.post(Uri.parse('$baseUrl$path'), headers: _headers,
      body: jsonEncode(body)).timeout(timeout);
    return _decode(response);
  }

  Future<dynamic> _delete(String path) async {
    _requireHttps();
    final response = await _client.delete(Uri.parse('$baseUrl$path'), headers: _headers)
      .timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<List<DropModel>> fetchDrops(String filter) async {
    final data = await _get('/drops?filter_kind=$filter') as Map<String, dynamic>;
    sourceStatusText = data['source_status_text'] as String? ?? 'Live source unavailable';
    checkedWalletLabel = data['checked_wallet_label'] as String? ?? 'No wallet connected';
    lastCheckedText = data['last_checked_text'] as String? ?? 'Eligibility unverified';
    return (data['drops'] as List).map((d) => DropModel.fromJson(d)).toList();
  }

  Future<Map<String, dynamic>> fetchSourceStatus() async =>
    (await _get('/source/status')) as Map<String, dynamic>;

  Future<List<MintTaskModel>> fetchQueue() async {
    final data = await _get('/tasks/queue') as Map<String, dynamic>;
    return (data['tasks'] as List).map((t) => MintTaskModel.fromJson(t)).toList();
  }

  Future<MintTaskModel> armTask({required DropModel drop, required MintStageModel stage,
    required int quantity, required String feeCapEth}) async {
    throw UnsupportedError('Unattended minting is unavailable for MetaMask. Confirm each transaction in MetaMask.');
  }

  Future<void> disarmTask(String taskId) async { await _post('/tasks/$taskId/disarm', {}); }

  Future<List<ActivityModel>> fetchActivity() async {
    final data = await _get('/activity') as List;
    return data.map((a) => ActivityModel.fromJson(a)).toList();
  }

  Future<bool> importDrop(String text) async {
    if (!isAdmin) throw StateError('Only an admin can import drops.');
    await _post('/drops/import', {'raw_content': text, 'source_author': username});
    return true;
  }

  Future<List<MintPlanModel>> fetchMintPlans() async {
    final data = await _get('/mint-plans') as List;
    return data.map((item) => MintPlanModel.fromJson(item as Map<String, dynamic>)).toList();
  }

  Future<MintPlanModel> importOpenSeaMint(String url, {int quantity = 1, String? walletId}) async =>
    MintPlanModel.fromJson((await _post('/mint-plans', {'url': url, 'quantity': quantity, if (walletId != null) 'wallet_id': walletId},
      timeout: const Duration(seconds: 60))) as Map<String, dynamic>);

  Future<MintPlanModel> refreshMintPlan(String id) async =>
    MintPlanModel.fromJson((await _post('/mint-plans/$id/refresh', {},
      timeout: const Duration(seconds: 60))) as Map<String, dynamic>);

  Future<void> removeMintPlan(String id) async { await _delete('/mint-plans/$id'); }

  Future<List<Map<String, dynamic>>> fetchWallets() async {
    final data = await _get('/wallets') as List;
    return data.cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> startWalletPairing() async =>
    (await _post('/wallets/pairings', {})) as Map<String, dynamic>;

  Future<Map<String, dynamic>> walletPairingStatus(String id) async =>
    (await _get('/wallets/pairings/$id')) as Map<String, dynamic>;

  Future<void> unlinkWallet(String id) async { await _delete('/wallets/$id'); }

  Future<Map<String, dynamic>?> registerDevice(String token) async =>
    (await _post('/notifications/register', {'token': token, 'platform': 'android'})) as Map<String, dynamic>;

  Future<void> setNotificationPreferences(String token, {
    required bool dailyList, required bool mintStatus,
  }) async {
    await _post('/notifications/preferences', {
      'token': token, 'daily_list': dailyList,
      'mint_status': mintStatus, 'source_health': true,
    });
  }

  Future<void> unregisterDevice(String token) async {
    if (isLiveBackendConnected) await _post('/notifications/unregister', {'token': token, 'platform': 'android'});
  }

  Future<List<Map<String, dynamic>>> listUsers() async {
    final data = await _get('/admin/users') as Map<String, dynamic>;
    return (data['users'] as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> createUser(String username, String adminPassword) async =>
    (await _post('/admin/users', {'username': username, 'admin_password': adminPassword})) as Map<String, dynamic>;

  Future<Map<String, dynamic>> resetUserPassword(String id, String adminPassword) async =>
    (await _post('/admin/users/$id/reset-password', {'admin_password': adminPassword})) as Map<String, dynamic>;

  Future<void> deleteUser(String id, String adminPassword) async {
    await _post('/admin/users/$id/delete', {'admin_password': adminPassword});
  }
}
