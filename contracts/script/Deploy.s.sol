// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.26;
import {TaskEscrow} from "../src/TaskEscrow.sol";
import {TestUSD} from "../src/TestUSD.sol";
interface BroadcastVm {
    function startBroadcast() external;
    function stopBroadcast() external;
}
contract Deploy {
    BroadcastVm constant vm = BroadcastVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    function run() external returns (TestUSD token, TaskEscrow escrow) {
        require(block.chainid == 84532 || block.chainid == 31337, "testnet or local only");
        vm.startBroadcast();
        token = new TestUSD();
        escrow = new TaskEscrow(address(token));
        vm.stopBroadcast();
    }
}
