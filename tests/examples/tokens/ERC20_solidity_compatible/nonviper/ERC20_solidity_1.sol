// Author: Florian Tramer

// https://github.com/ethereum/EIPs/issues/20
contract ERC20Interface {
    function totalSupply() constant returns (uint256 totalSupply);
    function balanceOf(address _owner) constant returns (uint256 balance);
    function transfer(address _to, uint256 _value) returns (bool success);
    function transferFrom(address _from, address _to, uint256 _value) returns (bool success);
    function approve(address _spender, uint256 _value) returns (bool success);
    function allowance(address _owner, address _spender) constant returns (uint256 remaining);
    
    function deposit() payable;
    function withdraw(uint256 _value) returns (bool success);
    
    event Transfer(address indexed _from, address indexed _to, uint256 _value);
    event Approval(address indexed _owner, address indexed _spender, uint256 _value);
}

contract MyToken is ERC20Interface {
    // mapping from account address to current balance
    mapping(address => uint256) _accountBalances;
    
    // mapping from account owner to accounts allowed to withdraw 
    // specified amounts
    mapping(address => mapping(address => uint256)) _approvals;
    
    uint256 private _totalSupply = 0;

    function deposit() payable {
        // check that deposit doesn't overflow total_supply
        assert(_totalSupply + msg.value >= _totalSupply);

        _accountBalances[msg.sender] += msg.value;
        _totalSupply += msg.value;
        Transfer(0x0, msg.sender, msg.value);
    }
    
    function withdraw(uint256 _value) returns (bool success) {
        if ( _accountBalances[msg.sender] < _value ) { throw; }

        // reduce funds BEFORE we send
        _accountBalances[msg.sender] -= _value;
        _totalSupply -= _value;

        if ( msg.sender.send(_value) ) {
            Transfer(msg.sender, 0x0, _value);
            return true;
        } else {
            throw;
        }
    }
    
    function totalSupply() constant returns (uint256 total_supply) {
        return _totalSupply;
    }
    
    function balanceOf(address _owner) constant returns (uint256 balance) {
        return _accountBalances[_owner];   
    }
    
    function transfer(address _to, uint256 _value) returns (bool success) {
        if ( _accountBalances[msg.sender] >= _value  // sender has enough resources
        ){
            _accountBalances[msg.sender] -= _value;
            _accountBalances[_to] += _value;
            Transfer(msg.sender, _to, _value);
            return true;
        }
        
        throw;
    }
    
    function transferFrom(address _from, address _to, uint256 _value) returns (bool success) {
        if ( _approvals[_from][msg.sender] >= _value  // sender is approved to withdraw
             && _accountBalances[_from] >= _value  // origin account has enough resources
        ){
            _approvals[_from][msg.sender] -= _value;
            _accountBalances[_from] -= _value;
            _accountBalances[_to] += _value;
            Transfer(_from, _to, _value);
            return true;
        }
        
        throw;   
    }
    
    function approve(address _spender, uint256 _value) returns (bool success) {
        _approvals[msg.sender][_spender] = _value;
        Approval(msg.sender, _spender, _value);
        return true;
    }
    
    function allowance(address _owner, address _spender) constant returns (uint256 remaining) {
        return _approvals[_owner][_spender];   
    }
}
