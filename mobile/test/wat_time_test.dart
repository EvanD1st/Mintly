import 'package:flutter_test/flutter_test.dart';
import 'package:mintly/services/wat_time.dart';
import 'package:mintly/services/api_service.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('12:05 WAT is 11:05 UTC, with correct date rollover and 24-hour display', () {
    expect(WatTime.fromWall(2026,10,8,12,5),DateTime.utc(2026,10,8,11,5));
    expect(WatTime.fromWall(2026,10,8,0,5),DateTime.utc(2026,10,7,23,5));
    expect(WatTime.label(DateTime.utc(2026,10,7,23,5)),'08/10/2026 00:05 WAT');
    expect(WatTime.parseWall('08/10/2026','12:05'),DateTime.utc(2026,10,8,11,5));
    expect(WatTime.parseWall('08/10/2026','12:05:30'),DateTime.utc(2026,10,8,11,5,30));
    expect(WatTime.parseWall('31/02/2026','12:05'),isNull);
    expect(WatTime.parseWall('08/10/2026','24:05'),isNull);
    expect(WatTime.parseWall('08/10/2026','12:60'),isNull);
  });
  test('default is stage opening when future, otherwise the next minute', () {
    final now=DateTime.utc(2026,10,8,11,4,20);
    expect(WatTime.defaultForStage(DateTime.utc(2026,10,8,11,5),now),DateTime.utc(2026,10,8,11,5));
    expect(WatTime.defaultForStage(DateTime.utc(2026,10,8,11),now),DateTime.utc(2026,10,8,11,5));
  });
  test('old server ignoring selected mint time cannot produce an automatic review', () async {
    final api=ApiService(client:MockClient((r) async => r.url.path.endsWith('/auth/login')
        ? http.Response('{"token":"test","user":{"username":"member"}}',200)
        : http.Response('{"snapshot":{"start":1},"review_hash":"hash"}',200)));
    await api.login('member','password');
    await expectLater(api.previewAutomaticTask({'scheduled_for_utc':'2026-10-08T11:05:00Z'}),throwsA(isA<ApiException>()));
  });
}
