class MintStageModel {
  final String id;
  final String dropId;
  final String stageName;
  final DateTime startTimeUtc;
  final DateTime? endTimeUtc;
  final int priceWei;
  final String priceEthStr;
  final int limitPerWallet;
  final String eligibilityStatus;
  final String? eligibilityEvidence;

  MintStageModel({
    required this.id,
    required this.dropId,
    required this.stageName,
    required this.startTimeUtc,
    this.endTimeUtc,
    required this.priceWei,
    required this.priceEthStr,
    required this.limitPerWallet,
    required this.eligibilityStatus,
    this.eligibilityEvidence,
  });

  factory MintStageModel.fromJson(Map<String, dynamic> json) {
    return MintStageModel(
      id: json['id'] ?? '',
      dropId: json['drop_id'] ?? '',
      stageName: json['stage_name'] ?? 'Unknown stage',
      startTimeUtc: DateTime.parse(json['start_time_utc'] as String),
      endTimeUtc: DateTime.tryParse(json['end_time_utc'] as String? ?? ''),
      priceWei: json['price_wei'] ?? 0,
      priceEthStr: json['price_eth_str'] ?? '',
      limitPerWallet: json['limit_per_wallet'] ?? 0,
      eligibilityStatus: json['eligibility_status'] ?? 'unknown',
      eligibilityEvidence: json['eligibility_evidence'],
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'drop_id': dropId,
    'stage_name': stageName,
    'start_time_utc': startTimeUtc.toIso8601String(),
    'price_wei': priceWei,
    'price_eth_str': priceEthStr,
    'limit_per_wallet': limitPerWallet,
    'eligibility_status': eligibilityStatus,
    'eligibility_evidence': eligibilityEvidence,
  };
}

class DropModel {
  final String id;
  final String name;
  final String chain;
  final int chainId;
  final String? contractAddress;
  final String mintPageUrl;
  final String siteLabel;
  final String iconName;
  final String statusLabel;
  final String statusKind; // 'eligible', 'manual', 'ineligible'
  final bool isSupportedIntegration;
  final String? manualNotice;
  final bool isDemo;
  final List<MintStageModel> stages;

  DropModel({
    required this.id,
    required this.name,
    required this.chain,
    required this.chainId,
    this.contractAddress,
    required this.mintPageUrl,
    required this.siteLabel,
    required this.iconName,
    required this.statusLabel,
    required this.statusKind,
    required this.isSupportedIntegration,
    this.manualNotice,
    required this.isDemo,
    required this.stages,
  });

  factory DropModel.fromJson(Map<String, dynamic> json) {
    var rawStages = json['stages'] as List<dynamic>? ?? [];
    return DropModel(
      id: json['id'] ?? '',
      name: json['name'] ?? '',
      chain: json['chain'] ?? 'Unknown',
      chainId: json['chain_id'] ?? 0,
      contractAddress: json['contract_address'],
      mintPageUrl: json['mint_page_url'] ?? '',
      siteLabel: json['site_label'] ?? 'Unverified source',
      iconName: json['icon_name'] ?? 'gem',
      statusLabel: json['status_label'] ?? 'Unverified',
      statusKind: json['status_kind'] ?? 'unknown',
      isSupportedIntegration: json['is_supported_integration'] ?? false,
      manualNotice: json['manual_notice'],
      isDemo: json['is_demo'] ?? false,
      stages: rawStages.map((s) => MintStageModel.fromJson(s as Map<String, dynamic>)).toList(),
    );
  }
}
