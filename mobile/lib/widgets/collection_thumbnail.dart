import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../state/app_state.dart';

final collectionArtworkProvider = FutureProvider.autoDispose
    .family<String?, String>((ref, reference) async {
      final api = ref.watch(apiServiceProvider);
      if (!api.isLiveBackendConnected || reference.isEmpty) return null;
      return api.collectionArtwork(reference);
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
    final url = ref.watch(collectionArtworkProvider(reference)).valueOrNull;
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
          child: url == null
              ? fallback
              : Image.network(
                  url,
                  fit: BoxFit.cover,
                  cacheWidth: (size * MediaQuery.devicePixelRatioOf(context))
                      .round(),
                  excludeFromSemantics: true,
                  errorBuilder: (_, error, stack) => fallback,
                  loadingBuilder: (_, child, progress) =>
                      progress == null ? child : fallback,
                ),
        ),
      ),
    );
  }
}
