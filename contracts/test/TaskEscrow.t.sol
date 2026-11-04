// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.26;
import {TaskEscrow} from "../src/TaskEscrow.sol";
import {TestUSD} from "../src/TestUSD.sol";

interface Vm {
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function prank(address caller) external;
    function warp(uint256 timestamp) external;
    function chainId(uint256 id) external;
}

/// @dev No forge-std dependency; Foundry's native test discovery and cheatcodes only.
contract TaskEscrowTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    TestUSD token;
    TaskEscrow escrow;
    uint256 constant KEY = 123456;
    address payer = address(0xA11CE);
    address payee = address(0xB0B);
    bytes32 constant MANDATE = keccak256("tenant-a/mandate-1");
    bytes32 constant VALIDATOR = keccak256("episode/v1/data-v1");
    bytes32 constant ARTIFACT = keccak256("artifact");

    function setUp() public {
        vm.warp(1000);
        token = new TestUSD();
        escrow = new TaskEscrow(address(token));
        token.mint(payer, 1000000);
        vm.prank(payer);
        token.approve(address(escrow), type(uint256).max);
    }
    function fund(uint256 amount) internal returns (bytes32) {
        address validator = vm.addr(KEY);
        vm.prank(payer);
        return escrow.fund(payee, validator, amount, 2000, MANDATE, VALIDATOR);
    }
    function signature(bytes32 id, uint256 key) internal returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, escrow.acceptanceDigest(id, ARTIFACT, 1900));
        return abi.encodePacked(r, s, v);
    }
    function tryRelease(bytes32 id, bytes32 artifact, bytes memory sig) internal returns (bool) {
        (bool ok,) = address(escrow).call(abi.encodeCall(TaskEscrow.release, (id, artifact, 1900, sig)));
        return ok;
    }
    function testReleaseAndReplay() public {
        bytes32 id = fund(100);
        bytes memory sig = signature(id, KEY);
        require(tryRelease(id, ARTIFACT, sig), "release failed");
        require(token.balanceOf(payee) == 100, "wrong payee balance");
        require(!tryRelease(id, ARTIFACT, sig), "replay accepted");
    }
    function testMalformedAndNoncanonicalSignature() public {
        bytes32 id = fund(100);
        require(!tryRelease(id, ARTIFACT, hex"0102"), "short signature accepted");
        bytes memory highS = abi.encodePacked(bytes32(uint256(1)), bytes32(type(uint256).max), uint8(27));
        require(!tryRelease(id, ARTIFACT, highS), "high-s signature accepted");
        require(!tryRelease(id, ARTIFACT, new bytes(65)), "zero signature accepted");
    }
    function testWrongSignerAndArtifact() public {
        bytes32 id = fund(100);
        require(!tryRelease(id, ARTIFACT, signature(id, KEY + 1)), "wrong signer accepted");
        require(!tryRelease(id, keccak256("changed"), signature(id, KEY)), "changed artifact accepted");
    }
    function testCrossTaskReplay() public {
        bytes32 a = fund(100);
        bytes32 b = fund(100);
        require(a != b, "duplicate ID");
        require(!tryRelease(b, ARTIFACT, signature(a, KEY)), "cross-task replay accepted");
    }
    function testCrossChainReplay() public {
        bytes32 id = fund(100);
        bytes memory sig = signature(id, KEY);
        vm.chainId(block.chainid + 1);
        require(!tryRelease(id, ARTIFACT, sig), "cross-chain replay accepted");
    }
    function testCrossContractReplay() public {
        bytes32 id = fund(100);
        TaskEscrow other = new TaskEscrow(address(token));
        vm.prank(payer);
        token.approve(address(other), 100);
        address validator = vm.addr(KEY);
        vm.prank(payer);
        bytes32 otherId = other.fund(payee, validator, 100, 2000, MANDATE, VALIDATOR);
        require(id == otherId, "fixture nonce mismatch");
        (bool ok,) = address(other).call(abi.encodeCall(TaskEscrow.release,
            (otherId, ARTIFACT, 1900, signature(id, KEY))));
        require(!ok, "cross-contract replay accepted");
    }
    function testRefundBoundaryAndDoubleRefund() public {
        bytes32 id = fund(100);
        vm.prank(payer);
        (bool early,) = address(escrow).call(abi.encodeCall(TaskEscrow.refund, (id)));
        require(!early, "early refund accepted");
        vm.warp(2000);
        vm.prank(payee);
        (bool outsider,) = address(escrow).call(abi.encodeCall(TaskEscrow.refund, (id)));
        require(!outsider, "outsider refund accepted");
        vm.prank(payer);
        escrow.refund(id);
        require(token.balanceOf(payer) == 1000000, "refund balance mismatch");
        vm.prank(payer);
        (bool twice,) = address(escrow).call(abi.encodeCall(TaskEscrow.refund, (id)));
        require(!twice, "double refund accepted");
    }
    function testWrongSettlementNonce() public {
        bytes32 id = fund(100);
        bytes32 body = keccak256(abi.encode(
            keccak256("Acceptance(bytes32 taskId,bytes32 mandateHash,bytes32 artifactHash,bytes32 validatorHash,address validator,uint256 settlementNonce,uint256 deadline)"),
            id, MANDATE, ARTIFACT, VALIDATOR, vm.addr(KEY), uint256(999), uint256(1900)));
        bytes32 wrongDigest = keccak256(abi.encodePacked("\x19\x01", escrow.domainSeparator(), body));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(KEY, wrongDigest);
        require(!tryRelease(id, ARTIFACT, abi.encodePacked(r,s,v)), "wrong nonce settled");
    }
    function testRevokedValidatorCannotSettle() public {
        bytes32 id = fund(100);
        bytes memory sig = signature(id, KEY);
        address validator = vm.addr(KEY);
        vm.prank(validator);
        escrow.revokeValidator();
        require(!tryRelease(id, ARTIFACT, sig), "revoked validator settled");
        vm.warp(2000);
        vm.prank(payer);
        escrow.refund(id);
        require(token.balanceOf(payer) == 1000000, "revoked task not refundable");
    }
    function testUnauthorizedWithdrawalAndMissingTask() public {
        bytes32 id = fund(100);
        vm.warp(2000);
        vm.prank(address(0xBAD));
        (bool withdrawn,) = address(escrow).call(abi.encodeCall(TaskEscrow.refund, (id)));
        require(!withdrawn, "unauthorized withdrawal");
        require(token.balanceOf(address(escrow)) == 100, "funds lost");
        require(!tryRelease(bytes32(uint256(42)), ARTIFACT, new bytes(65)), "missing task released");
    }
    function testExpiredAcceptance() public {
        bytes32 id = fund(100);
        bytes memory sig = signature(id, KEY);
        vm.warp(1901);
        require(!tryRelease(id, ARTIFACT, sig), "expired signature accepted");
    }
    function testFuzzConservation(uint96 rawAmount) public {
        uint256 amount = uint256(rawAmount) % 1000000 + 1;
        bytes32 id = fund(amount);
        require(token.balanceOf(address(escrow)) == amount, "funding mismatch");
        require(tryRelease(id, ARTIFACT, signature(id, KEY)), "release failed");
        require(token.balanceOf(payer) + token.balanceOf(payee) == 1000000, "value not conserved");
        require(token.balanceOf(address(escrow)) == 0, "stranded task balance");
    }
}
