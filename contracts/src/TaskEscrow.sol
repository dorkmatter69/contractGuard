// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.26;

interface IERC20 {
    function balanceOf(address owner) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

/// @notice Experimental escrow for one explicitly configured standard ERC-20.
/// @dev Trusted EOA validator attestations, NOT ZKP. No admin, upgrades or disputes.
///      Fee-on-transfer, rebasing and malicious tokens are unsupported.
contract TaskEscrow {
    enum State { Missing, Funded, Released, Refunded }
    struct Task {
        address payer;
        address payee;
        address validator;
        uint256 amount;
        uint256 expires;
        bytes32 mandateHash;
        bytes32 validatorHash;
        State state;
    }
    IERC20 public immutable token;
    mapping(bytes32 => Task) public tasks;
    mapping(address => uint256) public nonces;
    uint256 private entered = 1;
    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant ACCEPT_TYPEHASH = keccak256(
        "Acceptance(bytes32 taskId,bytes32 mandateHash,bytes32 artifactHash,bytes32 validatorHash,uint256 deadline)");
    uint256 private constant HALF_ORDER =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    event Funded(bytes32 indexed taskId, address indexed payer, address indexed payee,
                 uint256 amount, bytes32 mandateHash, bytes32 validatorHash, uint256 expires, address validator);
    event Released(bytes32 indexed taskId, bytes32 artifactHash, address indexed payee, uint256 amount);
    event Refunded(bytes32 indexed taskId, address indexed payer, uint256 amount);

    modifier nonReentrant() {
        require(entered == 1, "reentrant");
        entered = 2;
        _;
        entered = 1;
    }

    constructor(address token_) {
        require(token_.code.length > 0, "invalid token");
        token = IERC20(token_);
    }

    /// @notice Caller is payer; IDs are namespaced by payer and a monotonic nonce.
    function fund(address payee, address validator, uint256 amount, uint256 expires,
                  bytes32 mandateHash, bytes32 validatorHash) external nonReentrant returns (bytes32 id) {
        require(payee != address(0) && payee != address(this) && validator != address(0), "invalid address");
        require(amount > 0 && expires > block.timestamp, "invalid terms");
        require(mandateHash != bytes32(0) && validatorHash != bytes32(0), "empty commitment");
        id = keccak256(abi.encode(msg.sender, nonces[msg.sender]++));
        tasks[id] = Task(msg.sender, payee, validator, amount, expires, mandateHash, validatorHash, State.Funded);
        uint256 beforeBalance = token.balanceOf(address(this));
        safeCall(abi.encodeCall(IERC20.transferFrom, (msg.sender, address(this), amount)));
        require(token.balanceOf(address(this)) == beforeBalance + amount, "inexact funding");
        emit Funded(id, msg.sender, payee, amount, mandateHash, validatorHash, expires, validator);
    }

    function domainSeparator() public view returns (bytes32) {
        return keccak256(abi.encode(DOMAIN_TYPEHASH, keccak256("ContractGuardTaskEscrow"),
            keccak256("1"), block.chainid, address(this)));
    }

    function acceptanceDigest(bytes32 id, bytes32 artifactHash, uint256 deadline) public view returns (bytes32) {
        Task storage task = tasks[id];
        bytes32 body = keccak256(abi.encode(ACCEPT_TYPEHASH, id, task.mandateHash,
            artifactHash, task.validatorHash, deadline));
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator(), body));
    }

    /// @notice Anyone may relay an exact authorized acceptance, including the payee.
    function release(bytes32 id, bytes32 artifactHash, uint256 deadline, bytes calldata signature)
        external nonReentrant {
        Task storage task = tasks[id];
        require(task.state == State.Funded, "not funded");
        require(block.timestamp < task.expires && block.timestamp <= deadline && deadline <= task.expires,
                "expired acceptance");
        require(artifactHash != bytes32(0) && signature.length == 65, "invalid evidence");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        require(uint256(s) <= HALF_ORDER && (v == 27 || v == 28), "noncanonical signature");
        address signer = ecrecover(acceptanceDigest(id, artifactHash, deadline), v, r, s);
        require(signer != address(0) && signer == task.validator, "unauthorized validator");
        task.state = State.Released;
        safeCall(abi.encodeCall(IERC20.transfer, (task.payee, task.amount)));
        emit Released(id, artifactHash, task.payee, task.amount);
    }

    /// @notice Payer refunds after expiry; it cannot cancel before the agreed deadline.
    function refund(bytes32 id) external nonReentrant {
        Task storage task = tasks[id];
        require(task.state == State.Funded && msg.sender == task.payer, "not refundable");
        require(block.timestamp >= task.expires, "not expired");
        task.state = State.Refunded;
        safeCall(abi.encodeCall(IERC20.transfer, (task.payer, task.amount)));
        emit Refunded(id, task.payer, task.amount);
    }

    function safeCall(bytes memory data) private {
        (bool ok, bytes memory result) = address(token).call(data);
        require(ok && (result.length == 0 || abi.decode(result, (bool))), "token transfer failed");
    }
}
