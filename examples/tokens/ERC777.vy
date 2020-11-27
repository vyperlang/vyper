    # @dev Implementation of ERC-777 token standard.
    # @author Carl Farterson (@carlfarterson)
    # https://github.com/ethereum/EIPs/blob/master/EIPS/eip-777.md

    # from vyper.interfaces import ERC777

    # implements: ERC777
    event Transfer:
        sender: indexed(address)
        reciver: indexed(address)
        value: uint256

    event Approval:
        owner: indexed(address)
        spender: indexed(address)
        value: uint256

    event Sent:
        operater: indexed(address)
        sender: indexed(address)
        receiver: indexed(address)
        amount: uint256
        data: bytes32
        operaterData: bytes32

    event Minted:
        operater: indexed(address)
        receiver: indexed(address)
        amount: uint256
        data: bytes32
        operaterData: bytes32

    event Burned:
        operater: indexed(address)
        sender: indexed(address)
        amount: uint256
        data: bytes32
        operaterData: bytes32

    event AuthorizedOperator:
        operator: indexed(address)
        tokenHolder: indexed(address)

    event RevokedOperator:
        operator: indexed(address)
        tokenHolder: indexed(address)


    name: public(String[64])
    symbol: public(String[32])
    granularity: uint256 = 1
    decimals: uint256 = 18

    balanceOf: public(HashMap[address, uint256])
    _allowances: HashMap[address, HashMap[address, uint256]]

    @external
    def __init__(_name: String[64], _symbol: String[32]):
        pass

    @external
    def _send(recipient: address, amount: uint256, data: bytes32):
        pass

    @external
    def allowance(holder: address, spender: address) -> uint256:
        return _allowances[holder][spender]

    @external
    def approve(spender: address, value: uint256) -> bool:
        holder: address = msg.sender
        assert holder != ZERO_ADDRESS
        assert spender != ZERO_ADDRESS

        _allowances[holder][spender] = value
        log.Approval(holder, spender, value)