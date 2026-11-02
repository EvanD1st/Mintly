import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:mintly/screens/admin_screen.dart';
import 'package:mintly/services/api_service.dart';
import 'package:mintly/state/app_state.dart';
import 'protected_accounts_test.dart' show Accounts, result;

void main() {
  testWidgets('admin issues a code without calling password reset', (
    tester,
  ) async {
    var issued = 0;
    final api = ApiService(
      client: MockClient((request) async {
        final path = request.url.path;
        if (path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({
              'token': 'test-admin',
              'user': {'id': 'admin', 'username': 'admin', 'role': 'admin'},
            }),
            200,
          );
        }
        if (path.endsWith('/admin/users')) {
          return http.Response(
            jsonEncode({
              'users': [
                {
                  'id': 'member',
                  'username': 'member',
                  'role': 'member',
                  'must_change_password': false,
                },
              ],
            }),
            200,
          );
        }
        expect(path, endsWith('/admin/users/member/recovery-code'));
        expect(request.headers['Authorization'], 'Bearer test-admin');
        expect(
          jsonDecode(request.body)['admin_password'],
          'admin-confirmation',
        );
        issued++;
        return http.Response(
          jsonEncode({'recovery_code': 'MRC-${'a' * 32}'}),
          200,
        );
      }),
    );
    await api.login('admin', 'test-password');
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWith((ref) => api)],
        child: const MaterialApp(home: AdminScreen()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('One-time recovery code'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'admin-confirmation');
    await tester.tap(find.text('Confirm'));
    await tester.pumpAndSettle();
    expect(issued, 1);
    expect(find.text('Recovery code for member'), findsOneWidget);
    expect(find.text('MRC-${'a' * 32}'), findsOneWidget);
    expect(find.textContaining('password stays unchanged'), findsOneWidget);
    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();
  });

  test(
    'recovery code is not replayed when fingerprint saving is cancelled',
    () async {
      final accounts = Accounts()..allow = false;
      var redemptions = 0;
      var fallback = 0;
      final api = ApiService(
        accounts: accounts,
        client: MockClient((request) async {
          if (request.url.path.endsWith('/auth/device-login')) {
            redemptions++;
            return http.Response(jsonEncode(result('member')), 200);
          }
          expect(request.url.path, endsWith('/auth/session-only'));
          expect(request.headers['Authorization'], isNotNull);
          fallback++;
          return http.Response(
            jsonEncode({
              'token': 'ordinary-member',
              'user': {'id': 'member', 'username': 'member', 'role': 'member'},
            }),
            200,
          );
        }),
      );
      await api.checkProtectedAccounts();
      await api.login('member', 'MRC-${'a' * 32}');
      expect(redemptions, 1);
      expect(fallback, 1);
      expect(api.userId, 'member');
      expect(api.sessionRemembered, isFalse);
      expect(accounts.records, isEmpty);
      api.dispose();
    },
  );
}
