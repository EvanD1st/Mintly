class WalletModel {
  final String id;
  final String label;
  final String address;
  final String signingCapability;
  final bool isDefault;
  final bool isDemo;

  WalletModel({
    required this.id,
    required this.label,
    required this.address,
    required this.signingCapability,
    required this.isDefault,
    required this.isDemo,
  });

  factory WalletModel.fromJson(Map<String, dynamic> json) {
    return WalletModel(
      id: json['id'] ?? '',
      label: json['label'] ?? "Jenny's wallet",
      address: json['address'] ?? "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
      signingCapability: json['signing_capability'] ?? "watch_only",
      isDefault: json['is_default'] ?? true,
      isDemo: json['is_demo'] ?? false,
    );
  }
}
