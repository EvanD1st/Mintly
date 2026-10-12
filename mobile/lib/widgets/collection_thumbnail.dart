import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';
import 'dart:async';
import 'dart:typed_data';
import '../services/thumbnail_cache.dart';

final thumbnailCacheProvider = Provider((ref) => ThumbnailCache());

final collectionArtworkProvider = StreamProvider.autoDispose
    .family<Uint8List?, String>((ref, reference) async* {
      final api = ref.watch(apiServiceProvider);
      if (!api.isLiveBackendConnected || reference.isEmpty) {
        yield null;
        return;
      }
      final cache = ref.watch(thumbnailCacheProvider);
      var disposed = false;
      Timer? timer;
      Completer<void>? waiting;
      ref.onDispose(() {
        disposed = true;
        timer?.cancel();
        if (waiting != null && !waiting.isCompleted) waiting.complete();
      });
      final previous = await cache.lastImage(reference);
      if (disposed) return;
      yield previous;
      for (var attempt = 0; !disposed; attempt++) {
        final url = await api.collectionArtwork(
          reference,
          retryMissing: attempt > 0,
        );
        if (disposed) return;
        final bytes = url == null ? null : await cache.load(reference, url);
        if (disposed) return;
        if (bytes != null) {
          yield bytes;
          return;
        }
        waiting = Completer<void>();
        timer = Timer(
          Duration(
            seconds: attempt == 0
                ? 60
                : attempt == 1
                ? 120
                : 300,
          ),
          () => waiting!.complete(),
        );
        await waiting.future;
      }
    });

/// Artwork is optional presentation data, independent of mint preparation.
class CollectionThumbnail extends ConsumerWidget {
  final String reference, name;
  final double size;
  const CollectionThumbnail({
    super.key,
    required this.name,
    this.reference = '',
    this.size = 58,
  });
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bytes = ref.watch(collectionArtworkProvider(reference)).valueOrNull;
    final scheme = Theme.of(context).colorScheme;
    final fallback = Container(
      color: scheme.primary.withValues(alpha: .12),
      alignment: Alignment.center,
      child: Icon(
        Icons.filter_vintage_outlined,
        color: scheme.primary,
        size: size * .42,
      ),
    );
    return Semantics(
      label: '$name collection artwork',
      image: true,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: SizedBox.square(
          dimension: size,
          child: bytes == null
              ? fallback
              : Image.memory(
                  bytes,
                  fit: BoxFit.cover,
                  cacheWidth: (size * MediaQuery.devicePixelRatioOf(context))
                      .round(),
                  excludeFromSemantics: true,
                  errorBuilder: (_, error, stack) => fallback,
                ),
        ),
      ),
    );
  }
}
