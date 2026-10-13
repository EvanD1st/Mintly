import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'dart:io';

abstract class ProtectedAccounts {
  Future<Map<String, dynamic>> capabilities();
  Future<bool> unlock();
  Future<List<Map<String, dynamic>>> accounts(String origin);
  Future<Map<String, dynamic>?> read(String origin, String account);
  Future<void> save(Map<String, dynamic> record);
  Future<void> remove(String origin, String account);
}

class PlatformProtectedAccounts implements ProtectedAccounts {
  static const _channel = MethodChannel('mintly/protected-accounts');
  static Future<void> authenticatedForeground() async {
    if (kIsWeb || !Platform.isAndroid) return;
    try {
      await _channel.invokeMethod<void>('foreground_authenticated');
    } on MissingPluginException {
      /* Older APKs retain their ordinary window behavior. */
    } on PlatformException {
      /* Window privacy stays enabled until a successful phone unlock. */
    }
  }

  @override
  Future<Map<String, dynamic>> capabilities() async {
    if (kIsWeb || !Platform.isAndroid) return {};
    try {
      return await _channel.invokeMapMethod<String, dynamic>('capabilities') ??
          {};
    } on MissingPluginException {
      return {};
    } on PlatformException {
      return {'version': 2, 'device_secure': false};
    }
  }

  @override
  Future<bool> unlock() async {
    try {
      return await _channel.invokeMethod<bool>('unlock') ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }

  @override
  Future<List<Map<String, dynamic>>> accounts(String origin) async =>
      (await _channel.invokeListMethod<dynamic>('accounts', {
                'origin': origin,
              }) ??
              [])
          .map((r) => Map<String, dynamic>.from(r))
          .toList();
  @override
  Future<Map<String, dynamic>?> read(String origin, String account) =>
      _channel.invokeMapMethod<String, dynamic>('read', {
        'origin': origin,
        'user_id': account,
      });
  @override
  Future<void> save(Map<String, dynamic> record) =>
      _channel.invokeMethod<void>('save', record);
  @override
  Future<void> remove(String origin, String account) => _channel
      .invokeMethod<void>('remove', {'origin': origin, 'user_id': account});
}
