import 'network_metadata.dart';

class MintTaskModel {
  String get nativeCurrency => nativeSymbol(chain);
  final String id;
  final String? planId;
  final String walletId;
  final String dropId;
  final String stageId;
  final String status;
  final bool isDemo;
  final DateTime scheduledForUtc;
  final DateTime? createdAt;
  final int quantity;
  final String unitPriceEth;
  final String feeCapEth;
  final String totalCapEth;
  final String dropName;
  final String chain;
  final String stageName;
  final String timeWatLabel;
  final String iconName;
  final String? transactionHash;
  final String? explorerUrl;
  final String? failureReason;
  final String? scheduleNote;
  final Map<String, dynamic>? externalMint;
  final Map<String, dynamic>? progress;
  final Map<String, dynamic>? lifecycle;

  MintTaskModel({
    required this.id,
    this.planId,
    required this.walletId,
    required this.dropId,
    required this.stageId,
    required this.status,
    required this.isDemo,
    required this.scheduledForUtc,
    this.createdAt,
    required this.quantity,
    required this.unitPriceEth,
    required this.feeCapEth,
    required this.totalCapEth,
    required this.dropName,
    required this.chain,
    required this.stageName,
    required this.timeWatLabel,
    required this.iconName,
    this.transactionHash,
    this.explorerUrl,
    this.failureReason,
    this.scheduleNote,
    this.externalMint,
    this.progress,
    this.lifecycle,
  });

  factory MintTaskModel.fromJson(Map<String, dynamic> json) {
    return MintTaskModel(
      id: json['id'] ?? '',
      planId: json['plan_id'],
      walletId: json['wallet_id'] ?? '',
      dropId: json['drop_id'] ?? '',
      stageId: json['stage_id'] ?? '',
      status: json['status'] ?? 'armed',
      isDemo: json['is_demo'] ?? false,
      scheduledForUtc:
          DateTime.tryParse(json['scheduled_for_utc'] ?? '') ?? DateTime.now(),
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
      quantity: json['quantity'] ?? 1,
      unitPriceEth: json['unit_price_eth'] ?? '0',
      feeCapEth: json['fee_cap_eth'] ?? '0',
      totalCapEth: json['total_cap_eth'] ?? '0',
      dropName: json['drop_name'] ?? '',
      chain: json['chain'] ?? 'Base',
      stageName: json['stage_name'] ?? 'Allowlist',
      timeWatLabel: json['time_wat_label'] ?? '',
      iconName: json['icon_name'] ?? 'gem',
      transactionHash: json['transaction_hash'],
      explorerUrl: json['explorer_url'],
      failureReason: json['failure_reason'],
      scheduleNote: json['schedule_note'],
      externalMint: json['external_mint'] is Map<String, dynamic>
          ? json['external_mint'] as Map<String, dynamic>
          : null,
      progress: json['progress'] is Map<String, dynamic>
          ? json['progress'] as Map<String, dynamic>
          : null,
      lifecycle: json['lifecycle'] is Map<String, dynamic>
          ? json['lifecycle'] as Map<String, dynamic>
          : null,
    );
  }
}
