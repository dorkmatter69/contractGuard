// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.26;

/// @notice Public-mint toy token, no monetary value, TESTNET ONLY. Not USDC.
contract TestUSD {
    string public constant name = "ContractGuard Test USD";
    string public constant symbol = "CGTEST";
    uint8 public constant decimals = 6;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);

    function mint(address to, uint256 amount) external {
        require(to != address(0), "zero recipient");
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }
    function transfer(address to, uint256 amount) public virtual returns (bool) {
        move(msg.sender, to, amount);
        return true;
    }
    function transferFrom(address from, address to, uint256 amount) public virtual returns (bool) {
        allowance[from][msg.sender] -= amount;
        emit Approval(from, msg.sender, allowance[from][msg.sender]);
        move(from, to, amount);
        return true;
    }
    function move(address from, address to, uint256 amount) private {
        require(to != address(0), "zero recipient");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
