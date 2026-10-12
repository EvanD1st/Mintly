import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:http/http.dart' as http;
import 'package:pointycastle/digests/sha256.dart';
import 'thumbnail_storage.dart' as storage;

bool trustedThumbnailUrl(String url) {
  final u = Uri.tryParse(url);
  if (u == null ||
      u.scheme != 'https' ||
      u.userInfo.isNotEmpty ||
      (u.hasPort && u.port != 443)) {
    return false;
  }
  return u.host == 'seadn.io' ||
      u.host.endsWith('.seadn.io') ||
      u.host == 'openseauserdata.com' ||
      u.host.endsWith('.openseauserdata.com');
}

String thumbnailKey(String value) => SHA256Digest()
    .process(Uint8List.fromList(utf8.encode(value)))
    .map((b) => b.toRadixString(16).padLeft(2, '0'))
    .join();

class ThumbnailCache {
  final http.Client client;
  final _pending = <String, Future<Uint8List?>>{};
  final _memory = <String, Uint8List>{};
  final _lanes = [Future<void>.value(), Future<void>.value()];
  var _nextLane = 0;
  ThumbnailCache({http.Client? client}) : client = client ?? http.Client();

  Future<Uint8List?> lastImage(String reference) async {
    final meta = await storage.readThumbnail('ref_${thumbnailKey(reference)}');
    try {
      final url = jsonDecode(utf8.decode(meta!)) as String;
      if (!trustedThumbnailUrl(url)) return null;
      return _memory[url] ?? await storage.readThumbnail(thumbnailKey(url));
    } catch (_) {
      return null;
    }
  }

  Future<Uint8List?> load(String reference, String url) async {
    if (!trustedThumbnailUrl(url)) return null;
    final bytes = await (_pending[url] ??= _schedule(url));
    _pending.remove(url);
    if (bytes != null) {
      await storage.writeThumbnail(
        'ref_${thumbnailKey(reference)}',
        Uint8List.fromList(utf8.encode(jsonEncode(url))),
      );
    }
    return bytes;
  }

  Future<Uint8List?> _schedule(String url) {
    if (_memory.containsKey(url)) return Future.value(_memory[url]);
    final lane = _nextLane++ % _lanes.length;
    final result = _lanes[lane].then((_) => _load(url));
    _lanes[lane] = result.then<void>((_) {}, onError: (Object _) {});
    return result;
  }

  Future<Uint8List?> _load(String url) async {
    if (_memory.containsKey(url)) return _memory[url];
    var bytes = await storage.readThumbnail(thumbnailKey(url));
    if (bytes == null) {
      try {
        final request = http.Request('GET', Uri.parse(url))
          ..followRedirects = false;
        final response = await client
            .send(request)
            .timeout(const Duration(seconds: 12));
        if (response.statusCode != 200 ||
            !(response.headers['content-type'] ?? '').startsWith('image/') ||
            (response.contentLength ?? 0) > 4 * 1024 * 1024) {
          await response.stream.listen((_) {}).cancel();
          return null;
        }
        final buffer = BytesBuilder(copy: false);
        await for (final part in response.stream.timeout(
          const Duration(seconds: 12),
        )) {
          buffer.add(part);
          if (buffer.length > 4 * 1024 * 1024) return null;
        }
        final downloaded = buffer.takeBytes();
        if (downloaded.isEmpty) return null;
        final encodedBuffer = await ui.ImmutableBuffer.fromUint8List(
          downloaded,
        );
        final descriptor = await ui.ImageDescriptor.encoded(encodedBuffer);
        try {
          if (descriptor.width * descriptor.height > 16 * 1024 * 1024)
            return null;
        } finally {
          descriptor.dispose();
          encodedBuffer.dispose();
        }
        final codec = await ui.instantiateImageCodec(
          downloaded,
          targetWidth: 256,
          allowUpscaling: false,
        );
        try {
          final frame = await codec.getNextFrame();
          try {
            final encoded = await frame.image.toByteData(
              format: ui.ImageByteFormat.png,
            );
            bytes = encoded?.buffer.asUint8List();
          } finally {
            frame.image.dispose();
          }
        } finally {
          codec.dispose();
        }
        if (bytes == null || bytes.length > 4 * 1024 * 1024) return null;
        await storage.writeThumbnail(thumbnailKey(url), bytes);
      } catch (_) {
        return null;
      }
    }
    _memory[url] = bytes;
    while (_memory.values.fold<int>(0, (n, b) => n + b.length) >
        8 * 1024 * 1024) {
      _memory.remove(_memory.keys.first);
    }
    return bytes;
  }
}
