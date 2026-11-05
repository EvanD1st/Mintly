import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../widgets/main_navigation.dart';
import '../state/app_state.dart';
import '../widgets/network_budget_card.dart';
import '../widgets/collection_thumbnail.dart';
import '../services/push_service.dart';
import 'discover_screen.dart';
import 'queue_screen.dart';
import 'history_screen.dart';
import 'copy_mints_screen.dart';
import 'wallet_screen.dart';
import 'free_drops_screen.dart';

class MainShell extends ConsumerStatefulWidget {
  const MainShell({super.key});

  @override
  ConsumerState<MainShell> createState() => _MainShellState();
}

class _MainShellState extends ConsumerState<MainShell>
    with WidgetsBindingObserver {
  int _currentIndex = 0;
  bool _openingNotices = true;
  bool _autoPromptPresented = false;
  bool _autoPromptHandled = false, _autoPromptChecking = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    PushService.instance.todayRequests.addListener(_openToday);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        await _showAutoArmingPrompt(opening: true);
        if (mounted && !_autoPromptPresented) await _showCopyUpdate();
      } finally {
        _openingNotices = false;
        if (mounted) _showAutoArmingPrompt();
      }
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _showAutoArmingPrompt();
    });
  }

  Future<void> _showAutoArmingPrompt({bool opening = false}) async {
    if (!mounted ||
        (_openingNotices && !opening) ||
        _autoPromptHandled ||
        _autoPromptChecking ||
        _currentIndex != 0 ||
        WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed ||
        ModalRoute.of(context)?.isCurrent != true) {
      return;
    }
    _autoPromptChecking = true;
    final api = ref.read(apiServiceProvider);
    final owner = api.userId;
    try {
      if (owner.isEmpty || api.screenLocked) return;
      final status = await api.fetchFreeDropApprovals();
      if (!mounted ||
          ref.read(apiServiceProvider).userId != owner ||
          ref.read(apiServiceProvider).screenLocked ||
          _currentIndex != 0 ||
          WidgetsBinding.instance.lifecycleState != AppLifecycleState.resumed ||
          ModalRoute.of(context)?.isCurrent != true) {
        return;
      }
      if (status['enabled_once'] == true) {
        _autoPromptHandled = true;
        return;
      }
      if (status['enabled_once'] != false) return;
      _autoPromptHandled = true;
      _autoPromptPresented = true;
      final open = await showDialog<bool>(
        context: context,
        animationStyle: const AnimationStyle(
          duration: Duration(milliseconds: 240),
          reverseDuration: Duration(milliseconds: 180),
          curve: Curves.easeOutCubic,
        ),
        builder: (context) => AlertDialog(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(24),
          ),
          title: const Text('Turn on Auto-Arming'),
          content: const Text(
            'Mintly can automatically arm free mints you qualify for from Today’s list. You still pay gas.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Not now'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Turn on'),
            ),
          ],
        ),
      );
      if (!mounted || ref.read(apiServiceProvider).userId != owner) return;
      // A background/resume while this dialog was open must not stack it again.
      _autoPromptHandled = true;
      if (open == true &&
          mounted &&
          ref.read(apiServiceProvider).userId == owner) {
        await Navigator.of(
          context,
        ).push(MaterialPageRoute(builder: (_) => const FreeDropsScreen()));
      }
    } catch (_) {
      // Keep Today usable offline. A failed check never counts as enabling it.
    } finally {
      _autoPromptChecking = false;
      if (mounted && ref.read(apiServiceProvider).userId != owner) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _showAutoArmingPrompt();
        });
      }
    }
  }

  void _openToday() {
    if (!mounted ||
        PushService.instance.todayOwner !=
            ref.read(apiServiceProvider).userId) {
      return;
    }
    Navigator.of(context).popUntil((route) => route.isFirst);
    _selectTab(0);
    ref.read(mintlyProvider.notifier).refreshFeed();
  }

  Future<void> _showCopyUpdate() async {
    final api = ref.read(apiServiceProvider);
    try {
      if (!await api.showFreePhaseNotice() || !mounted) return;
      final openCopy = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (context) => PopScope(
          canPop: false,
          child: AlertDialog(
            title: const Text('New: copy any eligible free phase'),
            content: const Text(
              'A followed wallet minted in a phase you cannot join? Mintly can now try another free phase you qualify for in the same collection.\n\nGo to Copy, tap Manage for the wallet you follow, select Free mints only, then enable Copy any eligible free phase and approve your settings.\n\nYour saved settings will already be filled in. Gas limits still apply, and FCFS supply is not guaranteed.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Got it'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Go to Copy'),
              ),
            ],
          ),
        ),
      );
      if (!mounted) return;
      if (openCopy == true) _selectTab(2);
      await api.markFreePhaseNoticeSeen();
    } catch (_) {
      // Retry a failed notice check on the next authenticated opening.
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    PushService.instance.todayRequests.removeListener(_openToday);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      _autoPromptHandled = false;
    }
    if (state == AppLifecycleState.resumed) {
      ref.read(mintlyProvider.notifier).loadInitialData();
      ref.invalidate(networkBudgetsProvider);
      ref.invalidate(collectionArtworkProvider);
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _showAutoArmingPrompt();
      });
    }
  }

  final List<Widget> _screens = const [
    DiscoverScreen(),
    QueueScreen(),
    CopyMintsScreen(),
    HistoryScreen(embedded: true),
    WalletScreen(),
  ];

  void _selectTab(int index) {
    setState(() => _currentIndex = index);
    if (index == 2 || index == 4) ref.invalidate(networkBudgetsProvider);
    if (index == 1) ref.read(mintlyProvider.notifier).loadInitialData();
    if (index == 0) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _showAutoArmingPrompt();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(
      apiServiceProvider.select((api) => (api.userId, api.screenLocked)),
      (previous, next) {
        if (previous?.$1 != next.$1) _autoPromptHandled = false;
        if (!next.$2) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) _showAutoArmingPrompt();
          });
        }
      },
    );
    return Scaffold(
      appBar: AppBar(toolbarHeight: 0),
      body: MainNavigationScope(
        onSelected: _selectTab,
        child: IndexedStack(index: _currentIndex, children: _screens),
      ),
      bottomNavigationBar: AppNavigationBar(
        selected: _currentIndex,
        onSelected: _selectTab,
      ),
    );
  }
}
