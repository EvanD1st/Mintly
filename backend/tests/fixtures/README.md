The ABI/creation bytecode fixture is exported from `@metamask/delegation-abis`
as installed by `@metamask/smart-accounts-kit@2.0.0` (MIT-0 OR Apache-2.0 license).
The golden file was generated using Smart Accounts Kit 2.0.0's `createCaveatBuilder`,
`hashDelegation`, `DelegationManager.encode.redeemDelegations`,
`DelegationManager.encode.disableDelegation` and viem `hashTypedData`.
SDK repository: https://github.com/MetaMask/smart-accounts-kit

The local EVM test deploys these real contracts, enables an ephemeral EIP-7702
account, verifies a single exact delegated execution, and rejects altered
targets, altered values, reuse, revocation and expiration. All accounts and
balances are local test data. Never fund these test accounts on a real network.
