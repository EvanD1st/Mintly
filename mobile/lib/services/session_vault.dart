import 'package:flutter/services.dart';

abstract class SessionVault {
  Future<Map<String, dynamic>?> read();
  Future<bool> save(Map<String, dynamic> session);
  Future<void> clear();
}

class PlatformSessionVault implements SessionVault {
  static const _channel = MethodChannel('mintly/secure-session');
  @override
  Future<Map<String, dynamic>?> read() async {
    try {
      final data = await _channel.invokeMapMethod<String, dynamic>('read');
      return data;
    } on MissingPluginException { return null; }
      on PlatformException { return null; }
  }
  @override
  Future<bool> save(Map<String, dynamic> session) async {
    try { return await _channel.invokeMethod<bool>('save', session) ?? false; }
    on MissingPluginException { return false; }
    on PlatformException { return false; }
  }
  @override
  Future<void> clear() async {
    try { await _channel.invokeMethod<void>('clear'); }
    on MissingPluginException { /* Older OTA installers keep credentials in memory only. */ }
    on PlatformException { /* Server-side revocation still invalidates this token. */ }
  }
}
