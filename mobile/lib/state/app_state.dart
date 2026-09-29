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
  final bool isRechecked;
  final bool isConsentChecked;
  final bool isLoading;
  final bool isDemoMode;

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
    this.isRechecked = false,
    this.isConsentChecked = false,
    this.isLoading = false,
    this.isDemoMode = true,
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
    bool? isRechecked,
    bool? isConsentChecked,
    bool? isLoading,
    bool? isDemoMode,
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
      isRechecked: isRechecked ?? this.isRechecked,
      isConsentChecked: isConsentChecked ?? this.isConsentChecked,
      isLoading: isLoading ?? this.isLoading,
      isDemoMode: isDemoMode ?? this.isDemoMode,
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
          isLoading: true,
        )) {
    loadInitialData();
  }

  Future<void> loadInitialData() async {
    state = state.copyWith(isLoading: true);
    final drops = await _api.fetchDrops(state.filter);
    final queue = await _api.fetchQueue();
    final activities = await _api.fetchActivity();
    
    state = state.copyWith(
      drops: drops,
      selectedDrop: drops.isNotEmpty ? drops.first : null,
      selectedStage: drops.isNotEmpty && drops.first.stages.isNotEmpty ? drops.first.stages.first : null,
      queue: queue,
      activities: activities,
      isLoading: false,
    );
  }

  Future<void> setFilter(String filter) async {
    state = state.copyWith(filter: filter);
    final drops = await _api.fetchDrops(filter);
    state = state.copyWith(drops: drops);
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

  void recheckEligibility() {
    state = state.copyWith(isRechecked: true);
  }

  void toggleMonitoring() {
    state = state.copyWith(isMonitoring: !state.isMonitoring);
  }

  Future<bool> importList(String text) async {
    final ok = await _api.importDrop(text);
    await loadInitialData();
    return ok;
  }
}

final apiServiceProvider = Provider<ApiService>((ref) => ApiService());

final mintlyProvider = StateNotifierProvider<MintlyNotifier, MintlyState>((ref) {
  final api = ref.watch(apiServiceProvider);
  return MintlyNotifier(api);
});
