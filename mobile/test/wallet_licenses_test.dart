import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mintly/services/wallet_licenses.dart';

void main() {
  test(
    'OTA carries all recovery package notices without a NOTICES asset',
    () async {
      LicenseRegistry.reset();
      registerWalletLicenses();
      registerWalletLicenses();
      final entries = await LicenseRegistry.licenses.toList();
      expect(entries.length, 8);
      expect(entries.expand((e) => e.packages).toSet(), {
        'bip32',
        'bip39',
        'bs58check',
        'convert',
        'crypto',
        'hex',
        'js',
        'pointycastle',
      });
      for (final entry in entries) {
        final notice = entry.paragraphs.map((p) => p.text).join('\n');
        expect(notice, contains('Copyright'));
        expect(notice, contains('SOFTWARE'));
      }
    },
  );
}
