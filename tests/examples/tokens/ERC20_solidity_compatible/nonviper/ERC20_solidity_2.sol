// Author: Lorenz Breidenbach

pragma solidity ^0.4.10;
contract Token {
    // owner -> amount
    mapping(address => uint256) balances;
    // owner -> spender -> max amount
    mapping(address => mapping(address => uint256)) allowances;
    
    uint256 supply;

    event Transfer(address indexed _from, address indexed _to, uint256 _value);

    event Approval(address indexed _owner, address indexed _spender, uint256 _value);

    // Deposits ether with the contract and converts it to tokens.
    // One wei is worth one token.
    function deposit() payable {
        // overflow check. not necessary for 1-to-1 token-to-wei peg, but
        // might be good to have in case somebody decides to modify this code
        // to have the owner issue tokens, etc...
        if (supply + msg.value < supply) {
            throw;
        }
        supply += msg.value;
        balances[msg.sender] += msg.value;
        Transfer(0x0, msg.sender, msg.value);
    }
    
    // Converts tokens to ether and withdraws the ether. 
    // One token is worth one wei.
    function withdraw(uint256 _value) returns (bool success) {
        if (_value <= balances[msg.sender]) {
            balances[msg.sender] -= _value;
            supply -= _value;
            msg.sender.transfer(_value);
            Transfer(msg.sender, 0x0, _value);
            return true;
        } else {
            throw;
        }
    }
    
    // Spec: Get the total token supply
    function totalSupply() constant returns (uint256 totalSupply) {
        return supply;
    }

    // Spec: Get the account balance of another account with address _owner
    // The spec is a bit surprising to me. Why should this only work for the
    // balance of "another account", i.e. only if _owner != msg.sender?
    // For now, I am assuming that this is just due to unclear wording and that
    // anybody's balance may be queried this way.
    function balanceOf(address _owner) constant returns (uint256 balance) {
        return balances[_owner];
    }
    
    function internalTransfer(address _from, address _to, uint256 _value) internal returns (bool success) {
        if (_value <= balances[_from]) {
            balances[_from] -= _value;
            balances[_to] += _value;
            Transfer(_from, _to, _value);
            return true;
        } else {
            throw;
        }
    }
    
    // Spec: Send _value amount of tokens to address _to
    function transfer(address _to, uint256 _value) returns (bool success) {
        address _from = msg.sender;
        return internalTransfer(_from, _to, _value);
    }
    
    // Spec: Send _value amount of tokens from address _from to address _to
    function transferFrom(address _from, address _to, uint256 _value) returns (bool success) {
        address _spender = msg.sender;
        if(_value <= allowances[_from][_spender] && internalTransfer(_from, _to, _value)) {
            allowances[_from][_spender] -= _value;
            return true;
        } else {
            throw;
        }
    }
    
    // Spec: Allow _spender to withdraw from your account, multiple times, up 
    // to the _value amount. If this function is called again it overwrites the 
    // current allowance with _value.
    function approve(address _spender, uint256 _value) returns (bool success) {
        address _owner = msg.sender;
        allowances[_owner][_spender] = _value;
        Approval(_owner, _spender, _value);
        return true;
    }
    
    // Spec: Returns the amount which _spender is still allowed to withdraw 
    // from _owner.
    // What if the allowance is higher than the balance of the owner? 
    // Callers should be careful to use min(allowance, balanceOf) to make sure
    // that the allowance is actually present in the account!
    function allowance(address _owner, address _spender) constant returns (uint256 remaining) {
        return allowances[_owner][_spender];
    }
}
