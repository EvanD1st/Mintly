import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/api_service.dart';

void main() {
  test('offline demo makes no server requests', () async {
    final api = ApiService(client: MockClient((_) async => throw StateError('Unexpected request')));
    expect(await api.fetchDrops('all'), isNotEmpty);
    expect(api.isLiveBackendConnected, isFalse);
    expect(await api.importDrop('unsubmitted text'), isFalse);
    api.dispose();
  });

  test('rejects invalid token without entering connected mode', () async {
    final api = ApiService(client: MockClient((_) async => http.Response('{}', 401)));
    await expectLater(api.connectBackend('invalid'), throwsException);
    expect(api.isLiveBackendConnected, isFalse);
    api.dispose();
  });

  test('authenticated request errors cannot become demo success', () async {
    final api = ApiService(client: MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer session-token');
      if (request.url.path.endsWith('/wallets')) return http.Response('[{"id":"wallet-1"}]', 200);
      return http.Response('{}', 503);
    }));
    await api.connectBackend('session-token');
    await expectLater(api.fetchDrops('all'), throwsException);
    await expectLater(api.disarmTask('existing-task'), throwsException);
    await expectLater(api.importDrop('text'), throwsException);
    api.dispose();
  });
}
