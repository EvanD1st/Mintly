class MintTaskModel {
  final String id;
  final String walletId;
  final String dropId;
  final String stageId;
  final String status;
  final bool isDemo;
  final DateTime scheduledForUtc;
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

  MintTaskModel({
    required this.id,
    required this.walletId,
    required this.dropId,
    required this.stageId,
    required this.status,
    required this.isDemo,
    required this.scheduledForUtc,
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
  });

  factory MintTaskModel.fromJson(Map<String, dynamic> json) {
    return MintTaskModel(
      id: json['id'] ?? '',
      walletId: json['wallet_id'] ?? '',
      dropId: json['drop_id'] ?? '',
      stageId: json['stage_id'] ?? '',
      status: json['status'] ?? 'armed',
      isDemo: json['is_demo'] ?? false,
      scheduledForUtc: DateTime.tryParse(json['scheduled_for_utc'] ?? '') ?? DateTime.now(),
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
    );
  }
}
