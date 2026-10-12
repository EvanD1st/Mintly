import 'dart:io';
import 'dart:typed_data';

Future<Directory> _directory() async => Directory(
  '${Directory.systemTemp.path}/mintly_thumbnails_v1',
).create(recursive: true);

Future<Uint8List?> readThumbnail(String key) async {
  try {
    final file = File('${(await _directory()).path}/$key');
    final age = File('${file.path}.age');
    if (!await age.exists() ||
        DateTime.now().difference(
              DateTime.fromMillisecondsSinceEpoch(
                int.parse(await age.readAsString()),
              ),
            ) >
            const Duration(days: 7)) {
      return null;
    }
    if (!await file.exists() || await file.length() > 4 * 1024 * 1024) {
      return null;
    }
    final bytes = await file.readAsBytes();
    await file.setLastModified(DateTime.now());
    return bytes;
  } catch (_) {
    return null;
  }
}

Future<void> _writes = Future<void>.value();
Future<void> writeThumbnail(String key, Uint8List bytes) {
  final next = _writes.then((_) => _writeThumbnail(key, bytes));
  _writes = next;
  return next;
}

Future<void> _writeThumbnail(String key, Uint8List bytes) async {
  if (bytes.length > 4 * 1024 * 1024) return;
  try {
    final directory = await _directory();
    final file = File('${directory.path}/$key');
    await file.writeAsBytes(bytes, flush: false);
    await File(
      '${file.path}.age',
    ).writeAsString('${DateTime.now().millisecondsSinceEpoch}');
    final files = await directory
        .list()
        .where((e) => e is File)
        .cast<File>()
        .toList();
    final sizes = <File, FileStat>{};
    var total = 0;
    for (final item in files) {
      final stat = await item.stat();
      sizes[item] = stat;
      total += stat.size;
    }
    files.sort((a, b) => sizes[a]!.modified.compareTo(sizes[b]!.modified));
    for (final item in files) {
      if (total <= 50 * 1024 * 1024) break;
      total -= sizes[item]!.size;
      await item.delete();
    }
  } catch (_) {
    // Cache failure never blocks a screen or any mint operation.
  }
}
