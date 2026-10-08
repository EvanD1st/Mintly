/// WAT has a fixed UTC+1 offset. Never use the phone's local timezone for minting.
class WatTime {
  static DateTime wall(DateTime utc) => utc.toUtc().add(const Duration(hours:1));
  static DateTime fromWall(int year, int month, int day, int hour, int minute, {int second = 0}) =>
      DateTime.utc(year,month,day,hour,minute,second).subtract(const Duration(hours:1));
  static DateTime? parseWall(String date, String time) {
    final day = RegExp(r'^(\d{1,2})/(\d{1,2})/(\d{4})$').firstMatch(date.trim());
    final clock = RegExp(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$').firstMatch(time.trim());
    if (day == null || clock == null) return null;
    final d = int.parse(day[1]!), m = int.parse(day[2]!), y = int.parse(day[3]!);
    final h = int.parse(clock[1]!), n = int.parse(clock[2]!), s = int.parse(clock[3] ?? '0');
    if (h > 23 || n > 59 || s > 59 || y < 2000 || y > 2100) return null;
    final value = DateTime.utc(y,m,d,h,n,s);
    if (value.year != y || value.month != m || value.day != d) return null;
    return value.subtract(const Duration(hours:1));
  }
  static String label(DateTime utc) {
    final date = wall(utc);
    String pad(int value) => value.toString().padLeft(2,'0');
    return '${pad(date.day)}/${pad(date.month)}/${date.year} ${pad(date.hour)}:${pad(date.minute)}'
        '${date.second == 0 ? '' : ':${pad(date.second)}'} WAT';
  }
  static DateTime defaultForStage(DateTime startUtc, DateTime nowUtc) {
    if (startUtc.toUtc().isAfter(nowUtc.toUtc())) {
      return DateTime.fromMillisecondsSinceEpoch(
          ((startUtc.toUtc().microsecondsSinceEpoch+999999) ~/ 1000000)*1000,isUtc:true);
    }
    return DateTime.fromMillisecondsSinceEpoch(
        ((nowUtc.toUtc().millisecondsSinceEpoch ~/ 60000)+1)*60000,isUtc:true);
  }
}
