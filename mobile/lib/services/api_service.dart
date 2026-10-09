import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/drop_model.dart';
import '../models/task_model.dart';
import '../models/activity_model.dart';
import '../models/mint_plan_model.dart';
import '../widgets/mintly_notice.dart';
import 'session_vault.dart';
import 'dart:async';

class ApiException implements Exception {
  final String message;
  const ApiException(this.message);
  @override
  String toString() => message;
}

class ApiService extends ChangeNotifier {
  static String baseUrl = const String.fromEnvironment(
    'MINTLY_API_URL',
    defaultValue: 'https://mintly.duckdns.org/api',
  );
  final http.Client _client;
  final SessionVault _vault;
  Future<void> _storage = Future<void>.value();
  Future<T> _store<T>(Future<T> Function() action) {
    final next = _storage.then((_) => action());
    _storage = next.then<void>((_) {}, onError: (Object _) {});
    return next;
  }
  String _sessionToken = '';
  Map<String, dynamic>? _user;
  int _sessionRevision = 0;
  String sourceStatusText = 'Waiting for live data';
  String checkedWalletLabel = 'No wallet connected';
  String lastCheckedText = 'Wallet-specific eligibility is unverified';

  bool sessionRemembered = false;
  bool restoringSession = false;
  ApiService({http.Client? client, SessionVault? vault}) : _client = client ?? http.Client(), _vault = vault ?? PlatformSessionVault();

  bool get isLiveBackendConnected => _sessionToken.isNotEmpty;
  String get username => _user?['username'] as String? ?? '';
  String get userId => _user?['id'] as String? ?? '';
  int get sessionRevision => _sessionRevision;
  bool get isAdmin => _user?['role'] == 'admin';
  bool get mustChangePassword => _user?['must_change_password'] == true;

  void _requireHttps() {
    if (Uri.parse(baseUrl).scheme != 'https') {
      throw StateError('A secure HTTPS server address is required.');
    }
  }

  Map<String, String> get _headers {
    if (!isLiveBackendConnected) throw StateError('Sign in to Mintly first.');
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $_sessionToken',
    };
  }

  dynamic _decode(http.Response response) {
    dynamic data;
    try {
      data = jsonDecode(response.body);
    } catch (_) {
      data = null;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = data is Map ? data['detail'] : null;
      throw ApiException(
        detail is String
            ? detail
            : 'Server request failed (${response.statusCode}).',
      );
    }
    return data;
  }

  Future<void> login(String username, String password) async {
    _requireHttps();
    final response = await _client
        .post(
          Uri.parse('$baseUrl/auth/login'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'username': username.trim(), 'password': password}),
        )
        .timeout(const Duration(seconds: 15));
    final result = _decode(response) as Map<String, dynamic>;
    _sessionToken = result['token'] as String;
    _user = result['user'] as Map<String, dynamic>;
    _sessionRevision++;
    MintlyNotice.dismissAll();
    _resetMetadata();
    final expiry = result['expires_at'];
    final revision = _sessionRevision;
    final token = _sessionToken;
    final remembered = expiry is String && await _store(() => _vault.save({'token':token,'expires_at':expiry,'origin':baseUrl}));
    if (expiry is! String) await _store(() => _vault.clear());
    if (revision != _sessionRevision) return;
    sessionRemembered = remembered;
    notifyListeners();
  }

  void _expiredSession() {
    disconnectBackend();
    scheduleMicrotask(() => MintlyNotice.navigatorKey.currentState?.popUntil((route) => route.isFirst));
  }

  Future<bool> restoreSession() async {
    if (isLiveBackendConnected || restoringSession) return isLiveBackendConnected;
    restoringSession = true;
    final revision = _sessionRevision;
    try {
      _requireHttps();
      final saved = await _store(() => _vault.read());
      if (revision != _sessionRevision) return false;
      if (saved == null) return false;
      final expiry = DateTime.tryParse('${saved['expires_at']}');
      if (saved['origin'] != baseUrl || expiry == null || !expiry.toUtc().isAfter(DateTime.now().toUtc()) || saved['token'] is! String) {
        await _store(() => _vault.clear()); return false;
      }
      final response = await _client.get(Uri.parse('$baseUrl/auth/me'), headers:{'Authorization':'Bearer ${saved['token']}'}).timeout(const Duration(seconds:12));
      if (revision != _sessionRevision) return false;
      if (response.statusCode == 401) { await _store(() => _vault.clear()); return false; }
      final user = _decode(response) as Map<String,dynamic>;
      if (user['id'] is! String || user['username'] is! String) { await _store(() => _vault.clear()); return false; }
      _sessionToken = saved['token'] as String; _user = user; _sessionRevision++;
      sessionRemembered = true; _resetMetadata(); notifyListeners();
      return true;
    } catch (_) { return false; }
    finally { restoringSession = false; }
  }

  Future<void> changePassword(String oldPassword, String newPassword) async {
    await _post('/auth/change-password', {
      'current_password': oldPassword,
      'new_password': newPassword,
    });
    disconnectBackend();
  }

  Future<void> logout() async {
    try {
      if (isLiveBackendConnected) await _post('/auth/logout', {});
    } finally {
      disconnectBackend();
    }
  }

  void disconnectBackend() {
    unawaited(_store(() => _vault.clear()));
    sessionRemembered = false;
    _sessionToken = '';
    _user = null;
    _sessionRevision++;
    MintlyNotice.dismissAll();
    _resetMetadata();
    notifyListeners();
  }

  void _resetMetadata() {
    sourceStatusText = 'Waiting for live data';
    checkedWalletLabel = 'No wallet connected';
    lastCheckedText = 'Wallet-specific eligibility is unverified';
  }

  void _checkSession(int revision) {
    if (revision != _sessionRevision || !isLiveBackendConnected) {
      throw const ApiException('Account changed. Please reload this screen.');
    }
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }

  Future<dynamic> _get(String path) async {
    _requireHttps();
    final revision = _sessionRevision;
    final response = await _client
        .get(Uri.parse('$baseUrl$path'), headers: _headers)
        .timeout(const Duration(seconds: 15));
    _checkSession(revision);
    if (response.statusCode == 401) { _expiredSession(); throw const ApiException('Your session ended. Sign in again.'); }
    return _decode(response);
  }

  Future<dynamic> _post(
    String path,
    Map<String, dynamic> body, {
    Duration timeout = const Duration(seconds: 15),
  }) async {
    _requireHttps();
    final revision = _sessionRevision;
    final response = await _client
        .post(
          Uri.parse('$baseUrl$path'),
          headers: _headers,
          body: jsonEncode(body),
        )
        .timeout(timeout);
    _checkSession(revision);
    if (response.statusCode == 401) { _expiredSession(); throw const ApiException('Your session ended. Sign in again.'); }
    return _decode(response);
  }

  Future<dynamic> _delete(String path) async {
    _requireHttps();
    final revision = _sessionRevision;
    final response = await _client
        .delete(Uri.parse('$baseUrl$path'), headers: _headers)
        .timeout(const Duration(seconds: 15));
    _checkSession(revision);
    if (response.statusCode == 401) { _expiredSession(); throw const ApiException('Your session ended. Sign in again.'); }
    return _decode(response);
  }

  Future<List<DropModel>> fetchDrops(String filter) async {
    final data =
        await _get('/drops?filter_kind=$filter') as Map<String, dynamic>;
    sourceStatusText =
        data['source_status_text'] as String? ?? 'Live source unavailable';
    checkedWalletLabel =
        data['checked_wallet_label'] as String? ?? 'No wallet connected';
    lastCheckedText =
        data['last_checked_text'] as String? ?? 'Eligibility unverified';
    return (data['drops'] as List).map((d) => DropModel.fromJson(d)).toList();
  }

  Future<Map<String, dynamic>> fetchSourceStatus() async =>
      (await _get('/source/status')) as Map<String, dynamic>;

  Future<Map<String, dynamic>> fetchWalletReadiness() async =>
      (await _get('/wallets/readiness')) as Map<String, dynamic>;

  Future<void> addWatchWallet(String address, String label) async {
    await _post('/wallets/watch', {'address': address, 'label': label});
  }

  Future<Map<String,dynamic>> previewGuidedMint(Map<String,dynamic> request) async =>
      (await _post('/tasks/guided-preview',request,timeout:const Duration(seconds:30))) as Map<String,dynamic>;

  Future<Map<String, dynamic>> fetchAutomationStatus() async =>
      (await _get('/automatic/status')) as Map<String, dynamic>;

  Future<Map<String, dynamic>> fetchDailyLimit() async =>
      (await _get('/automatic/daily-limit')) as Map<String, dynamic>;

  Future<Map<String, dynamic>> setDailyLimit(String? eth) async =>
      (await _post('/automatic/daily-limit', {'limit_eth': eth, 'consent': true},
        timeout: const Duration(seconds: 50))) as Map<String, dynamic>;

  Future<Map<String, dynamic>> startCopyChecks(String watch, Map<String, dynamic> limits) async =>
      (await _post('/copy-mints/watches/${Uri.encodeComponent(watch)}/checks', limits,
        timeout: const Duration(seconds: 40))) as Map<String, dynamic>;

  Future<void> stopCopyChecks(String watch) async {
    await _delete('/copy-mints/watches/${Uri.encodeComponent(watch)}/checks');
  }

  Future<Map<String, dynamic>> fetchCopyCheckResults() async =>
      (await _get('/copy-mints/check-results')) as Map<String, dynamic>;

  Future<Map<String, dynamic>> setAutomationPaused(bool paused) async =>
      (await _post('/automatic/pause', {'paused': paused})) as Map<String, dynamic>;

  Future<void> removeDrop(String id) async {
    await _delete('/drops/${Uri.encodeComponent(id)}');
  }

  Future<List<MintTaskModel>> fetchQueue() async {
    final data = await _get('/tasks/queue') as Map<String, dynamic>;
    return (data['tasks'] as List)
        .map((t) => MintTaskModel.fromJson(t))
        .toList();
  }

  Future<MintTaskModel> armTask({
    required DropModel drop,
    required MintStageModel stage,
    required int quantity,
    required String feeCapEth,
    String? walletId,
    String? grantId,
    String? idempotencyKey,
    String? priceCapEth,
    String? totalCapEth,
    String? expiresAt,
    String mintKind = 'public',
    bool conditionalEligibility = false,
  }) async {
    if (walletId == null || grantId == null || idempotencyKey == null) {
      throw const ApiException(
        'Select a provisioned automatic wallet policy and review exact limits first.',
      );
    }
    return armAutomaticTask({
      'wallet_id': walletId,
      'grant_id': grantId,
      'drop_id': drop.id,
      'stage_id': stage.id,
      'quantity': quantity,
      'fee_cap_eth': feeCapEth,
      'price_cap_eth': priceCapEth,
      'total_cap_eth': totalCapEth,
      'expires_at': expiresAt,
      'mint_kind': mintKind,
      'conditional_eligibility': conditionalEligibility,
      'user_consent_confirmed': true,
      'idempotency_key': idempotencyKey,
    });
  }

  Future<Map<String, dynamic>> previewAutomaticTask(
    Map<String, dynamic> request,
  ) async {
    final result = (await _post('/tasks/draft', request)) as Map<String,dynamic>;
    if (request['scheduled_for_utc'] != null) {
      final time = DateTime.parse('${request['scheduled_for_utc']}').toUtc();
      final expected = (time.microsecondsSinceEpoch+999999) ~/ 1000000;
      if ((result['snapshot'] as Map?)?['execute_at'] != expected) {
        throw const ApiException('The server did not confirm your selected mint time. Refresh before setting automatic minting.');
      }
    }
    return result;
  }

  Future<MintTaskModel> armAutomaticTask(Map<String, dynamic> request) async {
    final task = MintTaskModel.fromJson(
      (await _post('/tasks/arm', request)) as Map<String, dynamic>,
    );
    if (task.id.isEmpty) {
      throw const ApiException(
        'The server did not confirm a saved task. Retry with the same request.',
      );
    }
    if (request['scheduled_for_utc'] != null) {
      final requested = DateTime.parse('${request['scheduled_for_utc']}').toUtc();
      final expected = (requested.microsecondsSinceEpoch+999999) ~/ 1000000;
      if (task.scheduledForUtc.toUtc().millisecondsSinceEpoch ~/ 1000 != expected) {
        throw const ApiException('The saved mint time could not be confirmed. Refresh the queue before retrying.');
      }
    }
    return task;
  }

  Future<List<Map<String, dynamic>>> fetchAutomaticPolicies() async =>
      ((await _get('/automatic/policies')) as List)
          .cast<Map<String, dynamic>>();

  Future<void> disableAutomaticPolicy(String id) async {
    await _post('/automatic/policies/$id/disable', {});
  }

  Future<Map<String, dynamic>> fetchCopyMints() async =>
      (await _get('/copy-mints')) as Map<String, dynamic>;
  Future<Map<String, dynamic>> fetchCopyActivity({
    String? watchId,
    int offset = 0,
  }) async =>
      (await _get(
            '/copy-mints/activity?offset=$offset${watchId == null ? '' : '&watch_id=${Uri.encodeComponent(watchId)}'}',
          ))
          as Map<String, dynamic>;
  Future<void> followCopyWallet(Map<String, dynamic> request) async {
    await _post('/copy-mints/watches', request);
  }

  Future<void> removeCopyWallet(String id) async {
    await _delete('/copy-mints/watches/$id');
  }

  Future<void> pauseCopying(bool paused, {String? watchId}) async {
    await _post(
      '/copy-mints${watchId == null ? '' : '/watches/$watchId'}/pause',
      {'paused': paused},
      timeout: const Duration(seconds: 60),
    );
  }

  Future<Map<String, dynamic>> approveCopyRule(
    String watchId,
    Map<String, dynamic> request,
  ) async =>
      (await _post(
            '/copy-mints/watches/$watchId/rules',
            request,
            timeout: const Duration(seconds: 60),
          ))
          as Map<String, dynamic>;
  Future<Map<String, dynamic>> approveWalletCopyRules(
    String watchId, Map<String, dynamic> request,
  ) async {
    final result = await _post('/copy-mints/watches/$watchId/wallet-rules', request,
        timeout: const Duration(seconds: 90));
    final rules = result is Map ? result['rules'] : null;
    final ids = request['grant_ids'] as List;
    if (result is! Map || result['id'] != request['request_id'] || rules is! List ||
        rules.length != ids.length || rules.any((r) => r is! Map || r['snapshot'] is! Map) ||
        rules.map((r) => r['snapshot']['grant_id']).toSet().length != ids.length ||
        ids.any((id) => !rules.any((r) => r['snapshot']['grant_id'] == id))) {
      throw const ApiException('Copy approval could not be confirmed. Retry with the same limits.');
    }
    return Map<String, dynamic>.from(result);
  }

  Future<void> retryCopyMint(String eventId) async {
    final result = await _post('/copy-mints/events/$eventId/retry', {},
        timeout: const Duration(seconds: 60));
    if (result is! Map || result['status'] != 'queued' || result['task_id'] is! String) {
      throw const ApiException('Retry was not confirmed. Refresh copy activity.');
    }
  }
  Future<Map<String, dynamic>> copyMintContext(String eventId) async =>
      (await _get('/copy-mints/events/$eventId/context'))
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> custodyImportConfig() async =>
      (await _get('/automatic/import/config')) as Map<String, dynamic>;

  Future<void> importCustodyWallet(Map<String, dynamic> payload) async {
    try {
      final result = await _post(
        '/automatic/import',
        payload,
        timeout: const Duration(seconds: 90),
      );
      if (result is! Map ||
          result['id'] != payload['request_id'] ||
          (payload['wallet_id'] != null
              ? result['wallet_id'] != payload['wallet_id']
              : result['wallet_id'] is! String ||
                    '${result['account']}'.toLowerCase() !=
                        '${payload['account_address']}'.toLowerCase())) {
        throw const ApiException('Import response could not be verified.');
      }
      if (payload['networks'] is List) {
        final requested = (payload['networks'] as List).cast<Map>();
        final grants = result['grants'];
        if (grants is! List ||
            grants.length != requested.length ||
            grants.any(
              (g) =>
                  g is! Map ||
                  g['wallet_id'] != result['wallet_id'] ||
                  '${g['account']}'.toLowerCase() !=
                      '${payload['account_address']}'.toLowerCase(),
            ) ||
            grants.map((g) => g['id']).toSet().length != requested.length ||
            grants.map((g) => g['chain_id']).toSet().length !=
                requested.length ||
            requested.any(
              (n) => !grants.any((g) => g['chain_id'] == n['chain_id']),
            )) {
          throw const ApiException('Network approvals could not be verified.');
        }
      }
    } catch (error) {
      // Never render a server/proxy response or exception containing a secret.
      const safeMessages = {
        'This wallet is still linked to another Mintly account. Unlink it there first.',
        'A previously signed mint for this wallet is unresolved. Wait for settlement before relinking.',
        'The signer has not confirmed this wallet is clear of unresolved signed mints. No wallet was linked.',
        'Mintly password is incorrect.',
        'Too many import attempts. Try again in 15 minutes.',
      };
      if (error is ApiException && safeMessages.contains(error.message)) {
        throw ApiException(error.message);
      }
      throw const ApiException(
        'Import not confirmed. Check your password, matching wallet key and limits, then retry. Refresh wallet policies first if the connection was interrupted.',
      );
    } finally {
      payload.remove('private_key');
      payload.remove('password');
    }
  }

  Future<Map<String, dynamic>> fetchHistory(
    String section, {
    int offset = 0,
  }) async =>
      (await _get('/history?section=$section&offset=$offset'))
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> automaticPlanContext(String id) async =>
      (await _post(
            '/mint-plans/$id/automatic-context',
            {},
            timeout: const Duration(seconds: 60),
          ))
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> removeTask(String id) async =>
      (await _delete('/tasks/$id')) as Map<String, dynamic>;

  Future<void> disarmTask(String taskId) async {
    await _post('/tasks/$taskId/disarm', {});
  }

  Future<List<ActivityModel>> fetchActivity() async {
    final data = await _get('/activity') as List;
    return data.map((a) => ActivityModel.fromJson(a)).toList();
  }

  Future<bool> importDrop(String text) async {
    if (!isAdmin) throw StateError('Only an admin can import drops.');
    await _post('/drops/import', {
      'raw_content': text,
      'source_author': username,
    });
    return true;
  }

  Future<List<MintPlanModel>> fetchMintPlans() async {
    final data = await _get('/mint-plans') as List;
    return data
        .map((item) => MintPlanModel.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<MintPlanModel> importOpenSeaMint(
    String url, {
    int quantity = 1,
    String? walletId,
  }) async => MintPlanModel.fromJson(
    (await _post('/mint-plans', {
          'url': url,
          'quantity': quantity,
          'wallet_id': walletId,
        }, timeout: const Duration(seconds: 60)))
        as Map<String, dynamic>,
  );

  Future<MintPlanModel> refreshMintPlan(String id) async =>
      MintPlanModel.fromJson(
        (await _post(
              '/mint-plans/$id/refresh',
              {},
              timeout: const Duration(seconds: 60),
            ))
            as Map<String, dynamic>,
      );

  Future<Map<String, dynamic>> removeMintPlan(String id) async =>
      (await _delete('/mint-plans/$id')) as Map<String, dynamic>;

  Future<List<Map<String, dynamic>>> fetchMintPermissions() async =>
      ((await _get('/mint-permissions')) as List).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> requestMintPermission(
    String planId,
    String mintEth, {
    int priceMultiplier = 1,
  }) async {
    final parts = mintEth.split('.');
    final wei =
        BigInt.parse(parts[0]) * BigInt.from(10).pow(18) +
        BigInt.parse((parts.length > 1 ? parts[1] : '').padRight(18, '0'));
    return (await _post('/mint-permissions', {
          'plan_id': planId,
          'max_mint_value_wei': (wei * BigInt.from(priceMultiplier)).toString(),
          'expiry_minutes': 15,
        }, timeout: const Duration(seconds: 90)))
        as Map<String, dynamic>;
  }

  Future<void> cancelMintPermission(String id) async {
    await _post('/mint-permissions/$id/cancel', {});
  }

  Future<Map<String, dynamic>> requestMintRevocation(String id) async =>
      (await _post('/mint-permissions/$id/revocation', {}))
          as Map<String, dynamic>;

  Future<List<Map<String, dynamic>>> fetchWallets() async {
    final data = await _get('/wallets') as List;
    return data.cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> startWalletPairing() async =>
      (await _post('/wallets/pairings', {})) as Map<String, dynamic>;

  Future<Map<String, dynamic>> walletPairingStatus(String id) async =>
      (await _get('/wallets/pairings/$id')) as Map<String, dynamic>;

  Future<void> unlinkWallet(String id) async {
    await _delete('/wallets/$id');
  }

  Future<Map<String, dynamic>?> registerDevice(String token) async =>
      (await _post('/notifications/register', {
            'token': token,
            'platform': 'android',
          }))
          as Map<String, dynamic>;

  Future<void> setNotificationPreferences(
    String token, {
    required bool dailyList,
    required bool mintStatus,
    bool? walletAlerts,
  }) async {
    await _post('/notifications/preferences', {
      'token': token,
      'daily_list': dailyList,
      'mint_status': mintStatus,
      'source_health': true,
      'wallet_alerts': ?walletAlerts,
    });
  }

  Future<void> unregisterDevice(String token) async {
    if (isLiveBackendConnected) {
      await _post('/notifications/unregister', {
        'token': token,
        'platform': 'android',
      });
    }
  }

  Future<List<Map<String, dynamic>>> listUsers() async {
    final data = await _get('/admin/users') as Map<String, dynamic>;
    return (data['users'] as List).cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>> createUser(
    String username,
    String adminPassword,
  ) async =>
      (await _post('/admin/users', {
            'username': username,
            'admin_password': adminPassword,
          }))
          as Map<String, dynamic>;

  Future<Map<String, dynamic>> resetUserPassword(
    String id,
    String adminPassword,
  ) async =>
      (await _post('/admin/users/$id/reset-password', {
            'admin_password': adminPassword,
          }))
          as Map<String, dynamic>;

  Future<void> deleteUser(String id, String adminPassword) async {
    await _post('/admin/users/$id/delete', {'admin_password': adminPassword});
  }
}
