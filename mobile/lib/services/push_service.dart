import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import 'api_service.dart';

class PushPreferences {
  const PushPreferences({this.dailyList = true, this.mintStatus = true});
  final bool dailyList;
  final bool mintStatus;
}

class PushService {
  PushService._();
  static final instance = PushService._();

  final messengerKey = GlobalKey<ScaffoldMessengerState>();
  final preferences = ValueNotifier(const PushPreferences());
  FirebaseMessaging? _messaging;
  ApiService? _api;
  String? _token;
  int _generation = 0;

  bool acceptsMessage(Map<String, dynamic> data) {
    final api = _api;
    if (api == null || !api.isLiveBackendConnected) return false;
    final owner = data['user_id'];
    if (data['category'] == 'mint_status' && owner == null) return false;
    if (owner != null && (api.userId.isEmpty || owner != api.userId)) {
      return false;
    }
    return data['category'] != 'source_health' || api.isAdmin;
  }

  bool get isConfigured => _messaging != null;

  Future<void> initialize() async {
    try {
      await Firebase.initializeApp();
      _messaging = FirebaseMessaging.instance;
      FirebaseMessaging.onMessage.listen((message) {
        if (!acceptsMessage(message.data)) return;
        final notification = message.notification;
        if (notification == null) return;
        messengerKey.currentState?.showSnackBar(
          SnackBar(
            content: Text(
              '${notification.title ?? 'Mintly'}: ${notification.body ?? ''}',
            ),
          ),
        );
      });
      _messaging!.onTokenRefresh.listen((token) async {
        final api = _api;
        final generation = _generation;
        final revision = api?.sessionRevision;
        final oldToken = _token;
        _token = token;
        try {
          if (api != null && api.isLiveBackendConnected) {
            if (oldToken != null && oldToken != token) {
              await api.unregisterDevice(oldToken);
            }
            if (generation != _generation || revision != api.sessionRevision) {
              return;
            }
            await api.registerDevice(token);
            if (generation != _generation || revision != api.sessionRevision) {
              return;
            }
            await api.setNotificationPreferences(
              token,
              dailyList: preferences.value.dailyList,
              mintStatus: preferences.value.mintStatus,
            );
          }
        } catch (error) {
          debugPrint('FCM token refresh registration failed: $error');
        }
      });
    } catch (error) {
      debugPrint('Firebase is not configured for this build: $error');
    }
  }

  Future<bool> connect(ApiService api) async {
    final generation = ++_generation;
    final revision = api.sessionRevision;
    _api = api;
    preferences.value = const PushPreferences();
    if (_messaging == null) return false;
    final permission = await _messaging!.requestPermission();
    if (generation != _generation || revision != api.sessionRevision) {
      return false;
    }
    if (permission.authorizationStatus != AuthorizationStatus.authorized &&
        permission.authorizationStatus != AuthorizationStatus.provisional) {
      return false;
    }
    final token = await _messaging!.getToken();
    if (generation != _generation || revision != api.sessionRevision) {
      return false;
    }
    _token = token;
    if (_token == null) return false;
    final registration = await api.registerDevice(_token!);
    if (generation != _generation || revision != api.sessionRevision) {
      return false;
    }
    final saved = registration?['preferences'];
    if (saved is Map<String, dynamic>) {
      preferences.value = PushPreferences(
        dailyList: saved['daily_list'] == true,
        mintStatus: saved['mint_status'] == true,
      );
    }
    return true;
  }

  Future<void> disconnect() async {
    final api = _api;
    final token = _token;
    _generation++;
    _api = null;
    _token = null;
    preferences.value = const PushPreferences();
    try {
      if (api != null && token != null) await api.unregisterDevice(token);
    } finally {
      // Retire this device token so an old account cannot deliver after sign-out.
      if (_messaging != null) await _messaging!.deleteToken();
    }
  }

  Future<void> setPreferences({bool? dailyList, bool? mintStatus}) async {
    final generation = _generation;
    final api = _api;
    final revision = api?.sessionRevision;
    final next = PushPreferences(
      dailyList: dailyList ?? preferences.value.dailyList,
      mintStatus: mintStatus ?? preferences.value.mintStatus,
    );
    if (_api == null || _token == null) {
      throw Exception('Connect to Mintly and allow notifications first.');
    }
    await api!.setNotificationPreferences(
      _token!,
      dailyList: next.dailyList,
      mintStatus: next.mintStatus,
    );
    if (generation == _generation && revision == api.sessionRevision) {
      preferences.value = next;
    }
  }
}
