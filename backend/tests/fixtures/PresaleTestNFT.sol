// SPDX-License-Identifier: MIT
pragma solidity 0.8.17;

import {ISeaDrop} from "src/interfaces/ISeaDrop.sol";
import {INonFungibleSeaDropToken} from "src/interfaces/INonFungibleSeaDropToken.sol";
import {AllowListData, SignedMintValidationParams} from "src/lib/SeaDropStructs.sol";

// Test collection only. The mint policy is enforced by the real SeaDrop.
contract PresaleTestNFT {
    address public immutable seaDrop;
    address public immutable owner;
    uint256 public totalSupply;
    mapping(address => uint256) public minted;
    mapping(uint256 => address) public ownerOf;
    constructor(address drop) {seaDrop=drop;owner=msg.sender;}
    function supportsInterface(bytes4 interfaceId) external pure returns(bool) {
        return interfaceId==type(INonFungibleSeaDropToken).interfaceId || interfaceId==0x01ffc9a7;
    }
    function mintSeaDrop(address minter,uint256 quantity) external {
        require(msg.sender==seaDrop);
        minted[minter]+=quantity;
        for(uint256 i=0;i<quantity;i++)ownerOf[++totalSupply]=minter;
    }
    function getMintStats(address minter) external view returns(uint256,uint256,uint256) {
        return(minted[minter],totalSupply,100);
    }
    function configure(bytes32 root,address fee,address signer,SignedMintValidationParams calldata bounds) external {
        require(msg.sender==owner);
        ISeaDrop(seaDrop).updateAllowList(AllowListData(root,new string[](0),""));
        ISeaDrop(seaDrop).updateAllowedFeeRecipient(fee,true);
        ISeaDrop(seaDrop).updateCreatorPayoutAddress(owner);
        ISeaDrop(seaDrop).updateSignedMintValidationParams(signer,bounds);
    }
    function replaceRoot(bytes32 root) external {
        require(msg.sender==owner);
        ISeaDrop(seaDrop).updateAllowList(AllowListData(root,new string[](0),""));
    }
}
