import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';

void main() {
  test('live data requires login and never falls back to samples', () async {
    final api = ApiService(client: MockClient((_) async => throw StateError('Unexpected request')));
    await expectLater(api.fetchDrops('all'), throwsStateError);
    expect(api.isLiveBackendConnected, isFalse);
    api.dispose();
  });

  test('authenticated failures do not turn into fake success', () async {
    final api = ApiService(client: MockClient((request) async {
      if (request.url.path.endsWith('/auth/login')) {
        return http.Response(jsonEncode({'token': 'session-token',
          'user': {'username': 'member', 'role': 'member', 'must_change_password': false}}), 200);
      }
      expect(request.headers['Authorization'], 'Bearer session-token');
      return http.Response('{"detail":"Live source unavailable"}', 503);
    }));
    await api.login('member', 'password');
    await expectLater(api.fetchDrops('all'), throwsA(isA<ApiException>().having(
      (error) => error.toString(), 'display message', 'Live source unavailable')));
    await expectLater(api.disarmTask('existing-task'), throwsException);
    await expectLater(api.importDrop('text'), throwsStateError);
    api.dispose();
  });
}
