import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/drop_model.dart';
import '../models/task_model.dart';
import '../models/activity_model.dart';
import '../models/mint_plan_model.dart';
import '../services/api_service.dart';

class MintlyState {
  final List<DropModel> drops;
  final String filter;
  final DropModel? selectedDrop;
  final MintStageModel? selectedStage;
  final int selectedQty;
  final String feeCap;
  final List<MintTaskModel> queue;
  final List<MintPlanModel> mintPlans;
  final List<Map<String, dynamic>> mintPermissions;
  final List<ActivityModel> activities;
  final bool isMonitoring;
  final bool isConsentChecked;
  final bool isLoading;
  final String? error;
  final String sourceStatusText;
  final String checkedWalletLabel;
  final String lastCheckedText;

  MintlyState({
    required this.drops,
    this.filter = 'all',
    this.selectedDrop,
    this.selectedStage,
    this.selectedQty = 1,
    this.feeCap = '0.0001',
    required this.queue,
    this.mintPlans = const [],
    this.mintPermissions = const [],
    required this.activities,
    this.isMonitoring = true,
    this.isConsentChecked = false,
    this.isLoading = false,
    this.error,
    this.sourceStatusText = 'Waiting for live data',
    this.checkedWalletLabel = 'No wallet connected',
    this.lastCheckedText = 'Eligibility unverified',
  });

  MintlyState copyWith({
    bool clearSelection = false,
    List<DropModel>? drops,
    String? filter,
    DropModel? selectedDrop,
    MintStageModel? selectedStage,
    int? selectedQty,
    String? feeCap,
    List<MintTaskModel>? queue,
    List<MintPlanModel>? mintPlans,
    List<Map<String, dynamic>>? mintPermissions,
    List<ActivityModel>? activities,
    bool? isMonitoring,
    bool? isConsentChecked,
    bool? isLoading,
    String? error,
    String? sourceStatusText,
    String? checkedWalletLabel,
    String? lastCheckedText,
  }) {
    return MintlyState(
      drops: drops ?? this.drops,
      filter: filter ?? this.filter,
      selectedDrop: clearSelection ? null : selectedDrop ?? this.selectedDrop,
      selectedStage: clearSelection ? null : selectedStage ?? this.selectedStage,
      selectedQty: selectedQty ?? this.selectedQty,
      feeCap: feeCap ?? this.feeCap,
      queue: queue ?? this.queue,
      mintPlans: mintPlans ?? this.mintPlans,
      mintPermissions: mintPermissions ?? this.mintPermissions,
      activities: activities ?? this.activities,
      isMonitoring: isMonitoring ?? this.isMonitoring,
      isConsentChecked: isConsentChecked ?? this.isConsentChecked,
      isLoading: isLoading ?? this.isLoading,
      error: error,
      sourceStatusText: sourceStatusText ?? this.sourceStatusText,
      checkedWalletLabel: checkedWalletLabel ?? this.checkedWalletLabel,
      lastCheckedText: lastCheckedText ?? this.lastCheckedText,
    );
  }
}

class MintlyNotifier extends StateNotifier<MintlyState> {
  final ApiService _api;
  int _loadGeneration = 0;

  MintlyNotifier(this._api)
      : super(MintlyState(
          drops: [],
          queue: [],
          activities: [],
          isLoading: false,
        ));

  Future<void> loadInitialData() async {
    final generation = ++_loadGeneration;
    if (!_api.isLiveBackendConnected) {
      state = MintlyState(drops: [], queue: [], activities: []);
      return;
    }
    state = state.copyWith(isLoading: true);
    final errors = <String>[];
    bool isCurrent() => mounted && generation == _loadGeneration && _api.isLiveBackendConnected;

    Future<void> loadSection<T>(String label, Future<T> Function() fetch,
        MintlyState Function(T) apply) async {
      try {
        final result = await fetch();
        if (isCurrent()) state = apply(result);
      } catch (error) {
        errors.add('$label: $error');
      }
    }

    await Future.wait([
      loadSection('Drops', () => _api.fetchDrops(state.filter), (drops) => state.copyWith(
        drops: drops,
        clearSelection: drops.isEmpty,
        selectedDrop: drops.isNotEmpty ? drops.first : null,
        selectedStage: drops.isNotEmpty && drops.first.stages.isNotEmpty ? drops.first.stages.first : null,
        sourceStatusText: _api.sourceStatusText,
        checkedWalletLabel: _api.checkedWalletLabel,
        lastCheckedText: _api.lastCheckedText,
      )),
      loadSection('Mint tasks', _api.fetchQueue, (queue) => state.copyWith(queue: queue)),
      loadSection('Mint plans', _api.fetchMintPlans, (plans) => state.copyWith(mintPlans: plans)),
      loadSection('Mint permissions', _api.fetchMintPermissions,
        (permissions) => state.copyWith(mintPermissions: permissions)),
      loadSection('Activity', _api.fetchActivity, (activities) => state.copyWith(activities: activities)),
    ]);
    if (isCurrent()) {
      state = state.copyWith(isLoading: false, error: errors.isEmpty ? null : errors.join('\n'));
    }
  }

  Future<void> setFilter(String filter) async {
    state = state.copyWith(filter: filter);
    await loadInitialData();
  }

  Future<void> removeDrop(String id) async {
    await _api.removeDrop(id);
    state = state.copyWith(drops: state.drops.where((drop) => drop.id != id).toList(),
      clearSelection: state.selectedDrop?.id == id);
    await loadInitialData();
  }

  void selectDrop(DropModel drop) {
    state = state.copyWith(
      selectedDrop: drop,
      selectedStage: drop.stages.isNotEmpty ? drop.stages.first : null,
      selectedQty: 1,
      feeCap: '0.0001',
      isConsentChecked: false,
    );
  }

  void setStage(MintStageModel stage) {
    state = state.copyWith(selectedStage: stage);
  }

  void incrementQuantity() {
    final limit = state.selectedStage?.limitPerWallet ?? 1;
    if (state.selectedQty < limit) {
      state = state.copyWith(selectedQty: state.selectedQty + 1);
    }
  }

  void decrementQuantity() {
    if (state.selectedQty > 1) {
      state = state.copyWith(selectedQty: state.selectedQty - 1);
    }
  }

  void setFeeCap(String fee) {
    state = state.copyWith(feeCap: fee);
  }

  void setConsent(bool consent) {
    state = state.copyWith(isConsentChecked: consent);
  }

  Future<MintTaskModel?> armCurrentTask() async {
    if (state.selectedDrop == null || state.selectedStage == null) return null;
    
    final task = await _api.armTask(
      drop: state.selectedDrop!,
      stage: state.selectedStage!,
      quantity: state.selectedQty,
      feeCapEth: state.feeCap,
    );

    final queue = await _api.fetchQueue();
    final activities = await _api.fetchActivity();
    state = state.copyWith(queue: queue, activities: activities);
    return task;
  }

  Future<bool> removeTask(String id) async {
    final result = await _api.removeTask(id);
    await loadInitialData();
    return result['in_flight'] == true;
  }

  Future<void> disarmTask(String taskId) async {
    await _api.disarmTask(taskId);
    final queue = await _api.fetchQueue();
    final activities = await _api.fetchActivity();
    state = state.copyWith(queue: queue, activities: activities);
  }

  Future<bool> importList(String text) async {
    final ok = await _api.importDrop(text);
    await loadInitialData();
    return ok;
  }

  Future<void> importOpenSeaMint(String url, {int quantity = 1, String? walletId}) async {
    final plan = await _api.importOpenSeaMint(url, quantity: quantity, walletId: walletId);
    _saveMintPlan(plan);
    await loadInitialData();
  }

  void _saveMintPlan(MintPlanModel plan) {
    state = state.copyWith(mintPlans: [
      plan,
      ...state.mintPlans.where((existing) => existing.id != plan.id),
    ]);
  }

  Future<MintPlanModel> refreshMintPlan(String id) async {
    final plan = await _api.refreshMintPlan(id);
    _saveMintPlan(plan);
    await loadInitialData();
    return plan;
  }

  Future<bool> removeMintPlan(String id) async {
    final result = await _api.removeMintPlan(id);
    state = state.copyWith(mintPlans: state.mintPlans.where((plan) => plan.id != id).toList());
    await loadInitialData();
    return result['in_flight'] == true;
  }

  Future<Map<String, dynamic>> requestMintPermission(MintPlanModel plan) async {
    final price = plan.mintValueEth ?? plan.priceEth;
    if (price == null) throw StateError('Check the exact mint price first.');
    final result = await _api.requestMintPermission(plan.id, price, priceMultiplier: plan.mintValueEth == null ? plan.quantity : 1);
    await loadInitialData();
    return result;
  }

  Future<void> cancelMintPermission(String id) async {
    await _api.cancelMintPermission(id);
    await loadInitialData();
  }
  Future<Map<String,dynamic>> requestMintRevocation(String id) => _api.requestMintRevocation(id);
}

final apiServiceProvider = ChangeNotifierProvider<ApiService>((ref) {
  final api = ApiService();
  return api;
});

final mintlyProvider = StateNotifierProvider<MintlyNotifier, MintlyState>((ref) {
  final api = ref.read(apiServiceProvider);
  return MintlyNotifier(api);
});
