class ActivityModel {
  final String id;
  final String eventType;
  final String label;
  final String detail;
  final String iconName;
  final bool isDemo;
  final String formattedTime;

  ActivityModel({
    required this.id,
    required this.eventType,
    required this.label,
    required this.detail,
    required this.iconName,
    required this.isDemo,
    required this.formattedTime,
  });

  factory ActivityModel.fromJson(Map<String, dynamic> json) {
    return ActivityModel(
      id: json['id'] ?? '',
      eventType: json['event_type'] ?? 'info',
      label: json['label'] ?? '',
      detail: json['detail'] ?? '',
      iconName: json['icon_name'] ?? 'bell',
      isDemo: json['is_demo'] ?? false,
      formattedTime: json['formatted_time'] ?? 'Now',
    );
  }
}
