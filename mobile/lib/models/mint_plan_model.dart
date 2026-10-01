class MintPlanModel {
  final String id;
  final String collectionName;
  final String openSeaUrl;
  final String chain;
  final String contractAddress;
  final String walletAddress;
  final String? stageName;
  final DateTime? startsAt;
  final DateTime? endsAt;
  final String? priceEth;
  final String? mintValueEth;
  final String? estimatedNetworkFeeEth;
  final String status;
  final String statusNote;
  final int quantity;
  final String? walletId;
  final String? estimatedTotalEth;
  final String? estimatedTotalUsdt;
  final DateTime? rateCheckedAt;

  const MintPlanModel({required this.id, required this.collectionName,
    required this.openSeaUrl, required this.chain, required this.contractAddress,
    required this.walletAddress,
    required this.stageName, required this.startsAt, required this.endsAt,
    required this.priceEth, required this.mintValueEth,
    required this.estimatedNetworkFeeEth, required this.status,
    required this.statusNote, this.quantity = 1, this.walletId, this.estimatedTotalEth,
    this.estimatedTotalUsdt, this.rateCheckedAt});

  factory MintPlanModel.fromJson(Map<String, dynamic> json) => MintPlanModel(
    id: json['id'] as String,
    collectionName: json['collection_name'] as String,
    openSeaUrl: json['opensea_url'] as String,
    chain: json['chain'] as String,
    contractAddress: json['contract_address'] as String,
    walletAddress: json['wallet_address'] as String,
    stageName: json['stage_name'] as String?,
    startsAt: DateTime.tryParse(json['starts_at']?.toString() ?? ''),
    endsAt: DateTime.tryParse(json['ends_at']?.toString() ?? ''),
    priceEth: json['price_eth'] as String?,
    mintValueEth: json['mint_value_eth'] as String?,
    estimatedNetworkFeeEth: json['estimated_network_fee_eth'] as String?,
    status: json['status'] as String,
    statusNote: json['status_note'] as String,
    quantity: json['quantity'] as int? ?? 1,
    walletId: json['wallet_id'] as String?,
    estimatedTotalEth: json['estimated_total_eth'] as String?,
    estimatedTotalUsdt: json['estimated_total_usdt'] as String?,
    rateCheckedAt: DateTime.tryParse(json['rate_checked_at']?.toString() ?? ''),
  );
}
