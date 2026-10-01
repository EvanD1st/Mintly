// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;
// Local test-only NFT receipt and canonical SeaDrop call shape.
contract MockNFT {
    mapping(uint256 => address) public ownerOf;
    uint256 public totalSupply;
    function mintSeaDrop(address recipient, uint256 quantity) external {
        require(msg.sender == address(0x00005EA00Ac477B1030CE78506496e8C2dE24bf5));
        for (uint256 i; i < quantity; i++) ownerOf[++totalSupply] = recipient;
    }
}
contract MockSeaDrop {
    function mintPublic(address nft, address, address recipient, uint256 quantity) external payable {
        require(msg.value == 10 * quantity);
        MockNFT(nft).mintSeaDrop(recipient == address(0) ? msg.sender : recipient, quantity);
    }
}
