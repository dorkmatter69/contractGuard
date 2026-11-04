// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.26;
import {TaskEscrow} from "../src/TaskEscrow.sol";
import {TestUSD} from "../src/TestUSD.sol";
import {Vm} from "./TaskEscrow.t.sol";

contract CallbackToken is TestUSD {
    TaskEscrow public target;
    bytes32 public task;
    bytes32 public artifact;
    bytes public signature;
    uint256 public deadline;
    bool public armed;
    bool public blocked;
    bool public failTransfer;
    function arm(TaskEscrow target_, bytes32 task_, bytes32 artifact_, uint256 deadline_, bytes memory signature_) external {
        target = target_; task = task_; artifact = artifact_; deadline = deadline_; signature = signature_; armed = true;
    }
    function setFailure(bool fail) external { failTransfer = fail; }
    function transfer(address to, uint256 amount) public override returns (bool) {
        if (failTransfer) return false;
        if (armed) {
            armed = false;
            // The second task has a valid signature and is still Funded. This
            // would settle without the global reentrancy guard.
            (bool ok,) = address(target).call(abi.encodeCall(TaskEscrow.release, (task, artifact, deadline, signature)));
            blocked = !ok;
        }
        return super.transfer(to, amount);
    }
}
contract ShortToken is TestUSD {
    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        return super.transferFrom(from, to, amount - 1);
    }
}
contract AdversarialTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 constant KEY = 123456;
    bytes32 constant ARTIFACT = keccak256("artifact");
    function sign(TaskEscrow escrow, bytes32 task) internal returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(KEY, escrow.acceptanceDigest(task, ARTIFACT, 1900));
        return abi.encodePacked(r, s, v);
    }
    function testCrossTaskReentrancyBlocked() public {
        vm.warp(1000);
        CallbackToken token = new CallbackToken();
        TaskEscrow escrow = new TaskEscrow(address(token));
        token.mint(address(this), 200);
        token.approve(address(escrow), 200);
        address validator = vm.addr(KEY);
        bytes32 a = escrow.fund(address(0xB0B), validator, 100, 2000, keccak256("m"), keccak256("v"));
        bytes32 b = escrow.fund(address(0xB0B), validator, 100, 2000, keccak256("m"), keccak256("v"));
        bytes memory sigB = sign(escrow, b);
        token.arm(escrow, b, ARTIFACT, 1900, sigB);
        escrow.release(a, ARTIFACT, 1900, sign(escrow, a));
        require(token.blocked(), "cross-task reentrancy succeeded");
        require(token.balanceOf(address(escrow)) == 100, "wrong escrow balance");
        escrow.release(b, ARTIFACT, 1900, sigB);
        require(token.balanceOf(address(0xB0B)) == 200, "incorrect final balance");
    }
    function testFalseReturnRollsBackSettlementState() public {
        vm.warp(1000);
        CallbackToken token = new CallbackToken();
        TaskEscrow escrow = new TaskEscrow(address(token));
        token.mint(address(this), 100); token.approve(address(escrow), 100);
        bytes32 id = escrow.fund(address(0xB0B), vm.addr(KEY), 100, 2000, keccak256("m"), keccak256("v"));
        bytes memory sig = sign(escrow, id);
        token.setFailure(true);
        (bool ok,) = address(escrow).call(abi.encodeCall(TaskEscrow.release, (id, ARTIFACT, 1900, sig)));
        require(!ok && token.balanceOf(address(escrow)) == 100, "failed transfer lost funds");
        token.setFailure(false);
        escrow.release(id, ARTIFACT, 1900, sig);
        require(token.balanceOf(address(0xB0B)) == 100, "retry after reverted transfer failed");
    }
    function testInexactFundingRevertsAllState() public {
        vm.warp(1000);
        ShortToken token = new ShortToken();
        TaskEscrow escrow = new TaskEscrow(address(token));
        token.mint(address(this), 100); token.approve(address(escrow), 100);
        (bool ok,) = address(escrow).call(abi.encodeCall(TaskEscrow.fund,
            (address(0xB0B), vm.addr(KEY), 100, 2000, keccak256("m"), keccak256("v"))));
        require(!ok && escrow.nonces(address(this)) == 0, "inexact funding persisted");
        require(token.balanceOf(address(this)) == 100 && token.balanceOf(address(escrow)) == 0, "funding rollback failed");
    }
}
