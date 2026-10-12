const networkNames = <int, String>{
  1: 'Ethereum',
  8453: 'Base',
  4663: 'Robinhood',
  999: 'HyperEVM',
  33139: 'ApeChain',
  57073: 'Ink',
  11155111: 'Sepolia',
  31337: 'Local test',
};

String nativeSymbol(dynamic network) {
  final value = '$network'.toLowerCase();
  if (value == '999' || value == 'hyperevm') return 'HYPE';
  if (value == '33139' || value == 'apechain' || value == 'ape_chain') {
    return 'APE';
  }
  return 'ETH';
}
