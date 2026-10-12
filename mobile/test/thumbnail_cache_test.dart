import 'dart:ui' as ui;
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/services/thumbnail_cache.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('thumbnail CDN validation rejects redirects to arbitrary hosts', () {
    expect(trustedThumbnailUrl('https://i2c.seadn.io/a'), isTrue);
    for (final url in [
      'https://seadn.io.evil.test/a',
      'http://i.seadn.io/a',
      'https://user:password@i.seadn.io/a',
      'https://i.seadn.io:444/a',
    ]) {
      expect(trustedThumbnailUrl(url), isFalse);
    }
  });
  test(
    'concurrent screens share download and reopened cache reuses stored image',
    () async {
      var calls = 0;
      final recorder = ui.PictureRecorder();
      ui.Canvas(recorder).drawRect(
        const ui.Rect.fromLTWH(0, 0, 1, 1),
        ui.Paint()..color = const ui.Color(0xff00ff00),
      );
      final picture = recorder.endRecording();
      final image = await picture.toImage(1, 1);
      final png = (await image.toByteData(
        format: ui.ImageByteFormat.png,
      ))!.buffer.asUint8List();
      image.dispose();
      picture.dispose();
      final client = MockClient((r) async {
        calls++;
        return http.Response.bytes(
          png,
          200,
          headers: {'content-type': 'image/png'},
        );
      });
      final url =
          'https://i.seadn.io/test-${DateTime.now().microsecondsSinceEpoch}.png';
      final cache = ThumbnailCache(client: client);
      final images = await Future.wait([
        cache.load('plan:test', url),
        cache.load('copy:test', url),
      ]);
      expect(images.every((b) => b != null), isTrue);
      expect(calls, 1);
      final restarted = ThumbnailCache(client: client);
      expect(await restarted.lastImage('copy:test'), isNotNull);
      expect(await restarted.load('activity:test', url), isNotNull);
      expect(calls, 1);
    },
  );
  test(
    'invalid image and oversized response are not saved as successful thumbnails',
    () async {
      final cache = ThumbnailCache(
        client: MockClient(
          (r) async => http.Response(
            'invalid image',
            200,
            headers: {'content-type': 'image/png'},
          ),
        ),
      );
      expect(
        await cache.load(
          'bad',
          'https://i.seadn.io/bad-${DateTime.now().microsecondsSinceEpoch}',
        ),
        isNull,
      );
      expect(await cache.load('blocked', 'https://evil.test/image'), isNull);
    },
  );
}
