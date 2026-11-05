class TodayAutomationStatus {
  const TodayAutomationStatus(this.approvals, {this.paused = false});

  final List<Map<String, dynamic>> approvals;
  final bool paused;
}
