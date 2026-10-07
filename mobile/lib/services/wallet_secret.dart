import 'dart:typed_data';
import 'package:bip32/bip32.dart' as bip32;
import 'package:bip39/bip39.dart' as bip39;
import 'package:pointycastle/ecc/api.dart';
import 'package:pointycastle/digests/keccak.dart';

/// Runs in a short-lived device isolate. Only the linked account's key returns.
Uint8List? resolveWalletSecret(Map<String, String> input) {
  final curve = ECDomainParameters('secp256k1');
  String address(Uint8List key) {
    final scalar = BigInt.parse(_hex(key), radix: 16);
    if (scalar <= BigInt.zero || scalar >= curve.n) return '';
    final public = (curve.G * scalar)!.getEncoded(false);
    return '0x${_hex(KeccakDigest(256).process(public.sublist(1)).sublist(12))}';
  }

  Uint8List? seed, raw;
  final nodes = <bip32.BIP32>[];
  try {
    final expected = (input['address'] ?? '').toLowerCase();
    final selectedIndex = int.tryParse(input['account_index'] ?? '0');
    if (expected.isEmpty &&
        (selectedIndex == null || selectedIndex < 0 || selectedIndex >= 20)) {
      return null;
    }
    if (input['kind'] == 'private_key') {
      final text = input['secret']!.trim().replaceFirst(RegExp(r'^0x'), '');
      if (!RegExp(r'^[0-9a-fA-F]{64}$').hasMatch(text)) return null;
      raw = Uint8List.fromList([
        for (var i = 0; i < 64; i += 2)
          int.parse(text.substring(i, i + 2), radix: 16),
      ]);
      return address(raw) == expected ? Uint8List.fromList(raw) : null;
    }
    if (input['kind'] != 'phrase') return null;
    final phrase = input['secret']!
        .trim()
        .toLowerCase()
        .split(RegExp(r'\s+'))
        .join(' ');
    if (![12, 24].contains(phrase.split(' ').length) ||
        !bip39.validateMnemonic(phrase)) {
      return null;
    }
    seed = bip39.mnemonicToSeed(phrase);
    var node = bip32.BIP32.fromSeed(seed);
    nodes.add(node);
    // MetaMask Ethereum accounts: m/44'/60'/0'/0/index.
    for (final index in [0x8000002c, 0x8000003c, 0x80000000, 0]) {
      node = node.derive(index);
      nodes.add(node);
    }
    for (var index = 0; index < 20; index++) {
      final account = node.derive(index);
      nodes.add(account);
      if (expected.isEmpty
          ? index == selectedIndex
          : address(account.privateKey!) == expected) {
        return Uint8List.fromList(account.privateKey!);
      }
    }
    return null;
  } catch (_) {
    return null; // Parser/crypto exceptions must never echo a secret.
  } finally {
    seed?.fillRange(0, seed.length, 0);
    raw?.fillRange(0, raw.length, 0);
    for (final node in nodes) {
      node.privateKey?.fillRange(0, node.privateKey!.length, 0);
      node.chainCode.fillRange(0, node.chainCode.length, 0);
    }
    input.clear();
  }
}

String walletAddressFromKey(Uint8List key) {
  final curve = ECDomainParameters('secp256k1');
  final scalar = BigInt.parse(_hex(key), radix: 16);
  if (scalar <= BigInt.zero || scalar >= curve.n) {
    throw ArgumentError('Invalid account');
  }
  final public = (curve.G * scalar)!.getEncoded(false);
  return '0x${_hex(KeccakDigest(256).process(public.sublist(1)).sublist(12))}';
}

String _hex(Uint8List bytes) =>
    bytes.map((v) => v.toRadixString(16).padLeft(2, '0')).join();
