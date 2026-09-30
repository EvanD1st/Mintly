import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/drop_model.dart';
import '../models/task_model.dart';
import '../models/activity_model.dart';
import '../services/api_service.dart';

class MintlyState {
  final List<DropModel> drops;
  final String filter;
  final DropModel? selectedDrop;
  final MintStageModel? selectedStage;
  final int selectedQty;
  final String feeCap;
  final List<MintTaskModel> queue;
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
    List<DropModel>? drops,
    String? filter,
    DropModel? selectedDrop,
    MintStageModel? selectedStage,
    int? selectedQty,
    String? feeCap,
    List<MintTaskModel>? queue,
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
      selectedDrop: selectedDrop ?? this.selectedDrop,
      selectedStage: selectedStage ?? this.selectedStage,
      selectedQty: selectedQty ?? this.selectedQty,
      feeCap: feeCap ?? this.feeCap,
      queue: queue ?? this.queue,
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

  MintlyNotifier(this._api)
      : super(MintlyState(
          drops: [],
          queue: [],
          activities: [],
          isLoading: false,
        ));

  Future<void> loadInitialData() async {
    if (!_api.isLiveBackendConnected) {
      state = MintlyState(drops: [], queue: [], activities: []);
      return;
    }
    state = state.copyWith(isLoading: true);
    try {
      final drops = await _api.fetchDrops(state.filter);
      final queue = await _api.fetchQueue();
      final activities = await _api.fetchActivity();
      state = state.copyWith(
        drops: drops,
        selectedDrop: drops.isNotEmpty ? drops.first : null,
        selectedStage: drops.isNotEmpty && drops.first.stages.isNotEmpty ? drops.first.stages.first : null,
        queue: queue,
        activities: activities,
        sourceStatusText: _api.sourceStatusText,
        checkedWalletLabel: _api.checkedWalletLabel,
        lastCheckedText: _api.lastCheckedText,
        isLoading: false,
      );
    } catch (error) {
      state = state.copyWith(isLoading: false, error: '$error');
    }
  }

  Future<void> setFilter(String filter) async {
    state = state.copyWith(filter: filter);
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
}

final apiServiceProvider = ChangeNotifierProvider<ApiService>((ref) {
  final api = ApiService();
  return api;
});

final mintlyProvider = StateNotifierProvider<MintlyNotifier, MintlyState>((ref) {
  final api = ref.read(apiServiceProvider);
  return MintlyNotifier(api);
});
