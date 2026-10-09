import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/services/session_vault.dart';

class MemoryVault implements SessionVault {
  Map<String, dynamic>? session;
  int clears = 0;
  @override
  Future<Map<String, dynamic>?> read() async => session;
  @override
  Future<bool> save(Map<String, dynamic> value) async { session = Map.of(value); return true; }
  @override
  Future<void> clear() async { clears++; session = null; }
}
Map<String, dynamic> credential() => {
  'token': 'a' * 64, 'origin': ApiService.baseUrl,
  'expires_at': DateTime.now().toUtc().add(const Duration(days: 1)).toIso8601String(),
};
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('restored session validates server identity before accepting saved token', () async {
    final vault = MemoryVault()..session = credential();
    final pending = Completer<http.Response>();
    final api = ApiService(vault: vault, client: MockClient((r) async {
      expect(r.url.path.endsWith('/auth/me'), true);
      expect(r.headers['Authorization'], 'Bearer ${vault.session!['token']}');
      return pending.future;
    }));
    final restore = api.restoreSession();
    await Future<void>.delayed(Duration.zero);
    expect(api.isLiveBackendConnected, false);
    expect(api.userId, isEmpty);
    pending.complete(http.Response('{"id":"server-owner","username":"member","role":"user"}', 200));
    expect(await restore, true);
    expect(api.userId, 'server-owner');
    expect(api.sessionRemembered, true);
    api.dispose();
  });
  for (final failure in ['expired', 'origin', 'revoked']) {
    test('$failure saved token cannot restore', () async {
      final vault = MemoryVault()..session = credential();
      if (failure == 'expired') vault.session!['expires_at'] = '2020-01-01T00:00:00Z';
      if (failure == 'origin') vault.session!['origin'] = 'https://other.example/api';
      var requests = 0;
      final api = ApiService(vault: vault, client: MockClient((r) async {
        requests++; return http.Response('{"detail":"Session expired"}', 401);
      }));
      expect(await api.restoreSession(), false);
      expect(api.isLiveBackendConnected, false);
      expect(vault.session, isNull);
      expect(requests, failure == 'revoked' ? 1 : 0);
      api.dispose();
    });
  }
  for (final method in ['GET', 'POST', 'DELETE']) {
    test('$method session expiry clears identity and secure storage', () async {
      final vault = MemoryVault();
      final api = ApiService(vault: vault, client: MockClient((r) async {
        if (r.url.path.endsWith('/auth/login')) return http.Response(jsonEncode({
          ...credential(), 'user': {'id': 'owner', 'username': 'member'},
        }), 200);
        expect(r.method, method);
        return http.Response('{"detail":"Session expired"}', 401);
      }));
      await api.login('member', 'never-store-password');
      expect(vault.session!.keys.toSet(), {'token', 'expires_at', 'origin'});
      final request = method == 'GET' ? api.fetchWallets() : method == 'POST'
          ? api.addWatchWallet('0x${'11' * 20}', 'Wallet') : api.unlinkWallet('wallet');
      await expectLater(request, throwsA(isA<ApiException>()));
      await Future<void>.delayed(Duration.zero);
      expect(api.isLiveBackendConnected, false);
      expect(api.username, isEmpty);
      expect(vault.session, isNull);
      api.dispose();
    });
  }
  test('late expired response from previous account cannot sign out new account', () async {
    final vault = MemoryVault();
    final stale = Completer<http.Response>();
    var loginCount = 0;
    final api = ApiService(vault: vault, client: MockClient((r) async {
      if (r.url.path.endsWith('/auth/login')) return http.Response(jsonEncode({
        ...credential(), 'user': {'id': '${++loginCount}', 'username': 'member'},
      }), 200);
      return stale.future;
    }));
    await api.login('member', 'password');
    final old = api.fetchWallets();
    final assertion = expectLater(old, throwsA(isA<ApiException>()));
    await api.login('member2', 'password');
    stale.complete(http.Response('{}', 401));
    await assertion;
    expect(api.userId, '2');
    expect(api.isLiveBackendConnected, true);
    expect(vault.session, isNotNull);
    api.dispose();
  });
  test('older OTA installer stays memory only without native vault', () async {
    final vault = PlatformSessionVault();
    expect(await vault.read(), isNull);
    expect(await vault.save(credential()), false);
    await vault.clear();
  });
}
