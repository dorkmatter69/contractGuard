// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.26;
import {TaskEscrow} from "../src/TaskEscrow.sol";
import {TestUSD} from "../src/TestUSD.sol";

interface ScenarioVm {
    function envAddress(string calldata name) external returns (address);
    function envUint(string calldata name) external returns (uint256);
    function envBytes32(string calldata name) external returns (bytes32);
    function envBytes(string calldata name) external returns (bytes memory);
    function startBroadcast(address sender) external;
    function stopBroadcast() external;
}

/// @dev No script ever reads a private key, seed or keystore password. Foundry's
///      external CLI signer handles operator-interactive signing separately.
abstract contract ScenarioBase {
    ScenarioVm constant vm = ScenarioVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    function target() internal returns (TaskEscrow escrow, address payer) {
        require(block.chainid == 84532 || block.chainid == 31337, "testnet/local only");
        escrow = TaskEscrow(vm.envAddress("ESCROW_ADDRESS"));
        payer = vm.envAddress("PAYER_ADDRESS");
        TestUSD token = TestUSD(address(escrow.token()));
        require(keccak256(bytes(token.symbol())) == keccak256("CGTEST") && token.decimals() == 6,
                "only no-value CGTEST demo tokens");
    }
}

/// @notice Mint bounded no-value demo units and fund one authorized task.
contract FundScenario is ScenarioBase {
    function run() external returns (bytes32 taskId) {
        (TaskEscrow escrow, address payer) = target();
        TestUSD token = TestUSD(address(escrow.token()));
        uint256 amount = vm.envUint("TASK_AMOUNT");
        uint256 expires = vm.envUint("TASK_EXPIRES");
        require(amount > 0 && amount <= 1000000, "bounded demo amount only");
        require(expires >= block.timestamp + 120 && expires <= block.timestamp + 86400, "invalid demo expiry");
        address payee = vm.envAddress("PAYEE_ADDRESS");
        address validator = vm.envAddress("VALIDATOR_ADDRESS");
        bytes32 mandateHash = vm.envBytes32("MANDATE_HASH");
        bytes32 validatorHash = vm.envBytes32("VALIDATOR_HASH");
        vm.startBroadcast(payer);
        token.mint(payer, amount);
        token.approve(address(escrow), amount);
        taskId = escrow.fund(payee, validator, amount, expires, mandateHash, validatorHash);
        vm.stopBroadcast();
    }
}

contract ReleaseScenario is ScenarioBase {
    function run() external {
        (TaskEscrow escrow, address payer) = target();
        bytes32 task = vm.envBytes32("TASK_ID");
        bytes32 artifact = vm.envBytes32("ARTIFACT_HASH");
        uint256 deadline = vm.envUint("ACCEPTANCE_DEADLINE");
        bytes memory signature = vm.envBytes("ACCEPTANCE_SIGNATURE"); // public attestation, not a key
        vm.startBroadcast(payer);
        escrow.release(task, artifact, deadline, signature);
        vm.stopBroadcast();
    }
}

contract RefundScenario is ScenarioBase {
    function run() external {
        (TaskEscrow escrow, address payer) = target();
        bytes32 task = vm.envBytes32("TASK_ID");
        vm.startBroadcast(payer);
        escrow.refund(task);
        vm.stopBroadcast();
    }
}
