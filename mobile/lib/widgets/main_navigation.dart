import 'package:flutter/material.dart';
import 'screen_components.dart';

class MainNavigationScope extends InheritedWidget {
  final ValueChanged<int> onSelected;
  const MainNavigationScope({
    super.key,
    required this.onSelected,
    required super.child,
  });
  static MainNavigationScope? maybeOf(BuildContext context) =>
      context.getInheritedWidgetOfExactType<MainNavigationScope>();
  @override
  bool updateShouldNotify(MainNavigationScope old) => false;
}

class AppNavigationBar extends StatelessWidget {
  final int selected;
  final ValueChanged<int> onSelected;
  const AppNavigationBar({
    super.key,
    required this.selected,
    required this.onSelected,
  });
  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF111F17),
        border: Border(top: BorderSide(color: scheme.outline)),
      ),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
          child: Row(
            children: [
              for (final (index, label, glyph) in const [
                (0, 'Today', 'calendar'),
                (1, 'Mint plans', 'list'),
                (2, 'Copy', 'people'),
                (3, 'Activity', 'trend'),
                (4, 'Wallet', 'wallet'),
              ])
                Expanded(
                  child: Semantics(
                    selected: selected == index,
                    button: true,
                    child: InkWell(
                      onTap: () => onSelected(index),
                      borderRadius: BorderRadius.circular(13),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 150),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 2,
                          vertical: 7,
                        ),
                        decoration: BoxDecoration(
                          color: selected == index
                              ? const Color(0xFF213D2A)
                              : Colors.transparent,
                          borderRadius: BorderRadius.circular(13),
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            AppGlyph(
                              glyph,
                              size: 20,
                              color: selected == index
                                  ? scheme.primary
                                  : scheme.onSurface.withValues(alpha: .7),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              label,
                              textAlign: TextAlign.center,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: selected == index
                                    ? FontWeight.w700
                                    : FontWeight.w500,
                                color: selected == index
                                    ? scheme.primary
                                    : scheme.onSurface.withValues(alpha: .7),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

Widget? detailsNavigation(BuildContext origin, int selected) {
  final scope = MainNavigationScope.maybeOf(origin);
  if (scope == null) return null;
  return AppNavigationBar(
    selected: selected,
    onSelected: (index) {
      if (!origin.mounted) return;
      Navigator.of(origin).popUntil((route) => route.isFirst);
      scope.onSelected(index);
    },
  );
}
