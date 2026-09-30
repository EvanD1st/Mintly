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

  bool get isConfigured => _messaging != null;

  Future<void> initialize() async {
    try {
      await Firebase.initializeApp();
      _messaging = FirebaseMessaging.instance;
      FirebaseMessaging.onMessage.listen((message) {
        final notification = message.notification;
        if (notification == null) return;
        messengerKey.currentState?.showSnackBar(SnackBar(
          content: Text('${notification.title ?? 'Mintly'}: ${notification.body ?? ''}'),
        ));
      });
      _messaging!.onTokenRefresh.listen((token) async {
        final oldToken = _token;
        _token = token;
        try {
          if (_api != null) {
            if (oldToken != null && oldToken != token) {
              await _api!.unregisterDevice(oldToken);
            }
            await _api!.registerDevice(token);
            await _api!.setNotificationPreferences(token,
              dailyList: preferences.value.dailyList,
              mintStatus: preferences.value.mintStatus);
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
    _api = api;
    if (_messaging == null) return false;
    final permission = await _messaging!.requestPermission();
    if (permission.authorizationStatus != AuthorizationStatus.authorized &&
        permission.authorizationStatus != AuthorizationStatus.provisional) {
      return false;
    }
    _token = await _messaging!.getToken();
    if (_token == null) return false;
    await api.registerDevice(_token!);
    await api.setNotificationPreferences(_token!,
      dailyList: preferences.value.dailyList,
      mintStatus: preferences.value.mintStatus);
    return true;
  }

  Future<void> disconnect() async {
    final api = _api;
    if (api != null && _token != null) await api.unregisterDevice(_token!);
    _api = null;
  }

  Future<void> setPreferences({bool? dailyList, bool? mintStatus}) async {
    final next = PushPreferences(
      dailyList: dailyList ?? preferences.value.dailyList,
      mintStatus: mintStatus ?? preferences.value.mintStatus,
    );
    if (_api == null || _token == null) {
      throw Exception('Connect to Mintly and allow notifications first.');
    }
    await _api!.setNotificationPreferences(_token!,
      dailyList: next.dailyList, mintStatus: next.mintStatus);
    preferences.value = next;
  }
}
