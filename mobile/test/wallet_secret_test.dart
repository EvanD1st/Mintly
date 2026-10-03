import 'package:flutter_test/flutter_test.dart';
import 'package:mintly/services/wallet_secret.dart';

// Public Hardhat test mnemonic, never use these accounts with real funds.
const phrase = 'test test test test test test test test test test test junk';
const firstAddress = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266';
const firstKey =
    'ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80';

void main() {
  test(
    'phrase selects exact MetaMask accounts against independent eth-account vectors',
    () {
      for (final vector in [
        (firstAddress, firstKey),
        (
          '0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
          '59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d',
        ),
        (
          '0x8626f6940E2eb28930eFb4CeF49B2d1F2C9C1199',
          'df57089febbacf7ba0bc227dafbffa9fc08a93fdc68e1e42411a14efcf23656e',
        ),
      ]) {
        final input = {
          'kind': 'phrase',
          'secret': phrase,
          'address': vector.$1,
        };
        final key = resolveWalletSecret(input);
        expect(
          key?.map((v) => v.toRadixString(16).padLeft(2, '0')).join(),
          vector.$2,
        );
        expect(input, isEmpty);
      }
    },
  );
  test(
    'rejects checksum errors, unrelated account, unsupported mode and account beyond search limit',
    () {
      for (final input in [
        {
          'kind': 'phrase',
          'secret': List.filled(12, 'test').join(' '),
          'address': firstAddress,
        },
        {
          'kind': 'phrase',
          'secret': phrase,
          'address': '0x09DB0a93B389bEF724429898f539AEB7ac2Dd55f',
        },
        {'kind': 'phrase', 'secret': phrase, 'address': '0x${'00' * 20}'},
        {'kind': 'other', 'secret': phrase, 'address': firstAddress},
      ]) {
        expect(resolveWalletSecret(input), isNull);
        expect(input, isEmpty);
      }
    },
  );
  test(
    'private key must also match linked address and must be a valid scalar',
    () {
      expect(
        resolveWalletSecret({
          'kind': 'private_key',
          'secret': '0x$firstKey',
          'address': firstAddress,
        }),
        isNotNull,
      );
      expect(
        resolveWalletSecret({
          'kind': 'private_key',
          'secret': firstKey,
          'address': '0x${'11' * 20}',
        }),
        isNull,
      );
      expect(
        resolveWalletSecret({
          'kind': 'private_key',
          'secret': '00' * 32,
          'address': firstAddress,
        }),
        isNull,
      );
      expect(
        resolveWalletSecret({
          'kind': 'private_key',
          'secret': 'ff' * 32,
          'address': firstAddress,
        }),
        isNull,
      );
    },
  );
}
