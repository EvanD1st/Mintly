import 'dart:math';
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
        barrierDismissible: false,
        animationStyle: const AnimationStyle(
          duration: Duration(milliseconds: 240),
          reverseDuration: Duration(milliseconds: 180),
          curve: Curves.easeOutCubic,
        ),
        builder: (context) => _AutoArmingDialog(
          enable: (requestId) async {
            if (!mounted ||
                ref.read(apiServiceProvider).userId != owner ||
                api.screenLocked) {
              throw Exception(
                'Unlock this account before turning on Auto-Arming.',
              );
            }
            await api.enableFreeDrops(requestId, api.selectedFeedWallet);
          },
        ),
      );
      if (!mounted || ref.read(apiServiceProvider).userId != owner) return;
      // A background/resume while this dialog was open must not stack it again.
      _autoPromptHandled = true;
      if (open == true &&
          mounted &&
          ref.read(apiServiceProvider).userId == owner) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Auto-Arming is on.')));
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

class _AutoArmingDialog extends StatefulWidget {
  const _AutoArmingDialog({required this.enable});
  final Future<void> Function(String requestId) enable;
  @override
  State<_AutoArmingDialog> createState() => _AutoArmingDialogState();
}

class _AutoArmingDialogState extends State<_AutoArmingDialog> {
  bool _busy = false;
  String? _error;
  late final String _requestId;
  @override
  void initState() {
    super.initState();
    final bytes = List.generate(16, (_) => Random.secure().nextInt(256));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    _requestId =
        '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  Future<void> _enable() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.enable(_requestId);
      if (mounted) {
        Navigator.pop(context, true);
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _error = error.toString().replaceFirst('Exception: ', '');
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_busy,
    child: AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      title: Row(
        children: [
          const Expanded(child: Text('Turn on Auto-Arming')),
          IconButton(
            tooltip: 'Close Auto-Arming',
            onPressed: _busy ? null : () => Navigator.pop(context, false),
            icon: const Icon(Icons.close),
          ),
        ],
      ),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Mintly will arm free mints from Today for your selected wallet, using the maximum NFTs it can mint. Your saved gas limits apply. You still pay gas.',
            ),
            if (_busy)
              const Padding(
                padding: EdgeInsets.only(top: 12),
                child: LinearProgressIndicator(),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
          ],
        ),
      ),
      actions: [
        FilledButton(
          onPressed: _busy ? null : _enable,
          child: Text(_busy ? 'Turning on...' : 'Turn on'),
        ),
      ],
    ),
  );
}
