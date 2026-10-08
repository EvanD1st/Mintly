import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';

enum NoticeTone { neutral, error }

/// App notices reuse existing message/action data, with a fixed-position fade.
/// SnackBar is configuration only: its sliding Material transition is never built.
class MintlyNotice {
  static final navigatorKey = GlobalKey<NavigatorState>();
  static final _entries = <OverlayEntry>{};

  static void show(BuildContext context, SnackBar notice, {NoticeTone tone = NoticeTone.neutral}) {
    if (!context.mounted) return;
    _show(Overlay.maybeOf(context, rootOverlay: true), notice, tone);
  }

  static void showGlobal(SnackBar notice, {NoticeTone tone = NoticeTone.neutral}) {
    _show(navigatorKey.currentState?.overlay, notice, tone);
  }

  static void _show(OverlayState? overlay, SnackBar notice, NoticeTone tone) {
    if (overlay == null || !overlay.mounted) return;
    dismissAll();
    late OverlayEntry entry;
    void remove() {
      if (!_entries.remove(entry)) return;
      entry.remove();
      entry.dispose();
    }
    entry = OverlayEntry(builder: (context) => _Notice(
      notice: notice, tone: tone, remove: remove,
      forget: () => _entries.remove(entry),
    ));
    _entries.add(entry);
    overlay.insert(entry);
  }

  /// Clear transient messages on account changes, sign-out and backgrounding.
  static void dismissAll() {
    for (final entry in _entries.toList()) {
      _entries.remove(entry);
      entry.remove();
      entry.dispose();
    }
  }
}

class _Notice extends StatefulWidget {
  const _Notice({required this.notice, required this.tone, required this.remove, required this.forget});
  final SnackBar notice;
  final NoticeTone tone;
  final VoidCallback remove;
  final VoidCallback forget;
  @override
  State<_Notice> createState() => _NoticeState();
}

class _NoticeState extends State<_Notice> with WidgetsBindingObserver {
  static const _fade = Duration(milliseconds: 180);
  Timer? _timer, _dismissTimer;
  bool _visible = false, _started = false, _closing = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (MediaQuery.disableAnimationsOf(context)) {
      _visible = true;
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !_closing) setState(() => _visible = true);
      });
    }
    if (!MediaQuery.accessibleNavigationOf(context) || widget.notice.action == null) {
      _timer = Timer(widget.notice.duration, _dismiss);
    }
  }

  void _dismiss() {
    if (_closing || !mounted) return;
    _closing = true;
    _timer?.cancel();
    if (MediaQuery.disableAnimationsOf(context)) {
      widget.remove();
      return;
    }
    setState(() => _visible = false);
    _dismissTimer = Timer(_fade, widget.remove);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      MintlyNotice.dismissAll();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _dismissTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    widget.forget();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.of(context);
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final accent = widget.tone == NoticeTone.error ? colors.error : colors.primary;
    final bottom = media.viewInsets.bottom > 0
        ? media.viewInsets.bottom + 16
        : math.max(media.padding.bottom, media.viewPadding.bottom) + 80;
    final action = widget.notice.action;
    return Positioned(
      left: 16, right: 16, bottom: bottom,
      child: Align(
        alignment: Alignment.bottomCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: IgnorePointer(
            ignoring: _closing,
            child: AnimatedOpacity(
              duration: media.disableAnimations ? Duration.zero : _fade,
              curve: Curves.easeOut,
              opacity: _visible ? 1 : 0,
              child: Semantics(
                liveRegion: true, container: true,
                child: Material(
                  key: const Key('mintly-notice-card'),
                  color: colors.surface,
                  elevation: 8,
                  shadowColor: Colors.black.withValues(alpha: 0.16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                    side: BorderSide(color: colors.outline.withValues(alpha: 0.7)),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(14, 8, 4, 8),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(color: accent.withValues(alpha: 0.12), shape: BoxShape.circle),
                          child: CustomPaint(size: const Size(18, 18), painter: _NoticeMark(accent)),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            DefaultTextStyle(
                              style: theme.textTheme.bodyMedium!.copyWith(color: colors.onSurface, fontWeight: FontWeight.w500),
                              maxLines: 4, overflow: TextOverflow.ellipsis,
                              child: widget.notice.content,
                            ),
                            if (action != null)
                              TextButton(
                                onPressed: () { action.onPressed(); _dismiss(); },
                                child: Text(action.label),
                              ),
                          ],
                        )),
                        IconButton(
                          tooltip: 'Dismiss message',
                          onPressed: _dismiss,
                          icon: CustomPaint(size: const Size(18, 18), painter: _NoticeMark(colors.onSurfaceVariant, close: true)),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NoticeMark extends CustomPainter {
  const _NoticeMark(this.color, {this.close = false});
  final Color color;
  final bool close;
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = color..style = PaintingStyle.stroke..strokeWidth = 1.6..strokeCap = StrokeCap.round;
    if (close) {
      canvas.drawLine(const Offset(4, 4), const Offset(14, 14), paint);
      canvas.drawLine(const Offset(14, 4), const Offset(4, 14), paint);
    } else {
      canvas.drawCircle(const Offset(9, 9), 7.5, paint);
      canvas.drawLine(const Offset(9, 8), const Offset(9, 13), paint);
      canvas.drawCircle(const Offset(9, 5), 0.5, paint);
    }
  }
  @override
  bool shouldRepaint(_NoticeMark old) => old.color != color || old.close != close;
}
