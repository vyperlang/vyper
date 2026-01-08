"""
Example test showing CodeModel DSL usage.
"""

import pytest
from eth_utils import to_wei

from tests.dsl import CodeModel


def test_counter_with_init(get_contract):
    """Simple counter with initialization."""
    model = CodeModel()

    count = model.storage_var("count: uint256")
    owner = model.storage_var("owner: address")

    code = (
        model.function("__init__(initial_count: uint256)")
        .deploy()
        .body(
            f"""
            {count} = initial_count
            {owner} = msg.sender
        """
        )
        .done()
        .function("increment()")
        .external()
        .body(f"{count} += 1")
        .done()
        .function("get_count() -> uint256")
        .external()
        .view()
        .body(f"return {count}")
        .done()
        .build()
    )

    c = get_contract(code, initial_count=10)
    assert c.get_count() == 10
    c.increment()
    assert c.get_count() == 11


def test_array_operations_with_internal_helper(get_contract):
    """Array operations using internal function."""
    model = CodeModel()

    values = model.storage_var("values: DynArray[uint256, 100]")

    # internal helper to find max value
    find_max = model.function("_find_max(arr: DynArray[uint256, 100]) -> uint256").internal().view()
    find_max.body(
        """
        max_val: uint256 = 0
        for val: uint256 in arr:
            if val > max_val:
                max_val = val
        return max_val
    """
    ).done()

    code = (
        model.function("add(val: uint256)")
        .external()
        .body(f"{values}.append(val)")
        .done()
        .function("get_max() -> uint256")
        .external()
        .view()
        .body(f"return {find_max}({values})")
        .done()
        .build()
    )

    c = get_contract(code)

    c.add(5)
    c.add(10)
    c.add(3)
    assert c.get_max() == 10


def test_hashmap_with_structs(get_contract, env):
    """HashMap with struct values."""
    model = CodeModel()

    model.struct(
        """User:
    balance: uint256
    active: bool
    joined_at: uint256"""
    )

    users = model.storage_var("users: HashMap[address, User]")
    user_count = model.storage_var("user_count: uint256")

    code = (
        model.function("register()")
        .external()
        .body(
            f"""
            assert {users}[msg.sender].joined_at == 0, "Already registered"
            {users}[msg.sender] = User(
                balance=0,
                active=True,
                joined_at=block.timestamp
            )
            {user_count} += 1
        """
        )
        .done()
        .function("deposit()")
        .external()
        .payable()
        .body(
            f"""
            assert {users}[msg.sender].active, "User not active"
            {users}[msg.sender].balance += msg.value
        """
        )
        .done()
        .function("get_user(addr: address) -> User")
        .external()
        .view()
        .body(f"return {users}[addr]")
        .done()
        .build()
    )

    c = get_contract(code)

    # fund the account
    env.set_balance(env.deployer, 10**18)

    c.register()
    c.deposit(value=100)
    user = c.get_user(env.deployer)
    assert user[0] == 100  # balance
    assert user[1] is True  # active


def test_constants_and_immutables(get_contract, env):
    """Constants and immutables usage."""
    model = CodeModel()

    # constants
    max_supply = model.constant("MAX_SUPPLY: constant(uint256) = 10**18")
    fee_rate = model.constant("FEE_RATE: constant(uint256) = 250")  # 2.5%
    fee_divisor = model.constant("FEE_DIVISOR: constant(uint256) = 10000")

    # immutables
    owner = model.immutable("OWNER: address")
    deployed_at = model.immutable("DEPLOYED_AT: uint256")

    # storage
    total_fees = model.storage_var("total_fees: uint256")

    code = (
        model.function("__init__()")
        .deploy()
        .body(
            f"""
            {owner} = msg.sender
            {deployed_at} = block.timestamp
        """
        )
        .done()
        .function("calculate_fee(amount: uint256) -> uint256")
        .external()
        .pure()
        .body(
            f"""
            assert amount <= {max_supply}, "Amount too large"
            return amount * {fee_rate} // {fee_divisor}
        """
        )
        .done()
        .function("collect_fee(amount: uint256) -> uint256")
        .external()
        .body(
            f"""
            fee: uint256 = amount * {fee_rate} // {fee_divisor}
            {total_fees} += fee
            return fee
        """
        )
        .done()
        .function("get_owner() -> address")
        .external()
        .view()
        .body(f"return {owner}")
        .done()
        .build()
    )

    c = get_contract(code)

    assert c.calculate_fee(10000) == 250
    assert c.collect_fee(10000) == 250
    assert c.get_owner() == env.deployer


def test_events_and_logging(get_contract, get_logs, env):
    """Events and logging with get_logs verification."""
    model = CodeModel()

    # events
    model.event(
        """Transfer:
        sender: indexed(address)
        receiver: indexed(address)
        amount: uint256"""
    )
    model.event(
        """Approval:
        owner: indexed(address)
        spender: indexed(address)
        amount: uint256"""
    )
    model.event(
        """Burn:
        account: indexed(address)
        amount: uint256
        reason: String[100]"""
    )

    balances = model.storage_var("balances: HashMap[address, uint256]")

    code = (
        model.function("__init__()")
        .deploy()
        .body(f"{balances}[msg.sender] = 1000")
        .done()
        .function("transfer(to: address, amount: uint256)")
        .external()
        .body(
            f"""
            {balances}[msg.sender] -= amount
            {balances}[to] += amount
            log Transfer(sender=msg.sender, receiver=to, amount=amount)
        """
        )
        .done()
        .function("approve(spender: address, amount: uint256)")
        .external()
        .body("log Approval(owner=msg.sender, spender=spender, amount=amount)")
        .done()
        .function("burn(amount: uint256, reason: String[100])")
        .external()
        .body(
            f"""
            {balances}[msg.sender] -= amount
            log Burn(account=msg.sender, amount=amount, reason=reason)
        """
        )
        .done()
        .build()
    )

    c = get_contract(code)

    # test transfer event
    receiver = "0x1234567890123456789012345678901234567890"
    c.transfer(receiver, 100)
    (log,) = get_logs(c, "Transfer")
    assert log.args.sender == env.deployer
    assert log.args.receiver == receiver
    assert log.args.amount == 100

    # test approval event
    spender = "0x2222222222222222222222222222222222222222"
    c.approve(spender, 500)
    (log,) = get_logs(c, "Approval")
    assert log.args.owner == env.deployer
    assert log.args.spender == spender
    assert log.args.amount == 500

    # test burn event with string
    c.burn(50, "Testing burn functionality")
    (log,) = get_logs(c, "Burn")
    assert log.args.account == env.deployer
    assert log.args.amount == 50
    assert log.args.reason == "Testing burn functionality"


def test_flags_and_enums(get_contract):
    """Flags (enums) usage."""
    model = CodeModel()

    model.flag(
        """OrderStatus:
    PENDING
    FILLED
    CANCELLED
    EXPIRED"""
    )

    model.struct(
        """Order:
    amount: uint256
    price: uint256
    status: OrderStatus
    created_at: uint256"""
    )

    orders = model.storage_var("orders: HashMap[uint256, Order]")
    next_id = model.storage_var("next_order_id: uint256")

    code = (
        model.function("create_order(amount: uint256, price: uint256) -> uint256")
        .external()
        .body(
            f"""
            order_id: uint256 = {next_id}
            {orders}[order_id] = Order(
                amount=amount,
                price=price,
                status=OrderStatus.PENDING,
                created_at=block.timestamp
            )
            {next_id} += 1
            return order_id
        """
        )
        .done()
        .function("cancel_order(order_id: uint256)")
        .external()
        .body(
            f"""
            assert {orders}[order_id].status == OrderStatus.PENDING, "Not pending"
            {orders}[order_id].status = OrderStatus.CANCELLED
        """
        )
        .done()
        .function("get_order_status(order_id: uint256) -> OrderStatus")
        .external()
        .view()
        .body(f"return {orders}[order_id].status")
        .done()
        .build()
    )

    c = get_contract(code)

    order_id = c.create_order(100, 50)
    assert c.get_order_status(order_id) == 1  # PENDING (flags start at 1)
    c.cancel_order(order_id)
    assert c.get_order_status(order_id) == 4  # CANCELLED


def test_payable_and_value_handling(get_contract, env):
    """Payable functions and value handling."""
    model = CodeModel()

    deposits = model.storage_var("deposits: HashMap[address, uint256]")
    total_deposits = model.storage_var("total_deposits: uint256")

    code = (
        model.function("deposit()")
        .external()
        .payable()
        .body(
            f"""
            {deposits}[msg.sender] += msg.value
            {total_deposits} += msg.value
        """
        )
        .done()
        .function("withdraw(amount: uint256)")
        .external()
        .body(
            f"""
            assert {deposits}[msg.sender] >= amount, "Insufficient balance"
            {deposits}[msg.sender] -= amount
            {total_deposits} -= amount
            send(msg.sender, amount)
        """
        )
        .done()
        .function("get_balance(addr: address) -> uint256")
        .external()
        .view()
        .body(f"return {deposits}[addr]")
        .done()
        .build()
    )

    c = get_contract(code)

    # fund the account
    env.set_balance(env.deployer, to_wei(10, "ether"))

    # deposit some ether
    c.deposit(value=to_wei(1, "ether"))
    assert c.get_balance(env.deployer) == to_wei(1, "ether")

    # withdraw half
    c.withdraw(to_wei(0.5, "ether"))
    assert c.get_balance(env.deployer) == to_wei(0.5, "ether")


def test_nonreentrant_guards(get_contract):
    """Nonreentrant modifier usage."""
    model = CodeModel()

    bal = model.storage_var("bal: uint256")

    code = (
        model.function("protected_withdraw(amount: uint256)")
        .external()
        .nonreentrant()
        .body(
            f"""
            assert {bal} >= amount
            {bal} -= amount
            raw_call(msg.sender, b"", value=amount)
        """
        )
        .done()
        .function("protected_update(new_value: uint256)")
        .external()
        .nonreentrant()
        .body(f"{bal} = new_value")
        .done()
        .build()
    )

    get_contract(code)
    # just check it compiles - actual reentrancy testing would require attack contract


def test_complex_internal_function_chain(get_contract):
    """Multiple internal functions calling each other."""
    model = CodeModel()

    max_size = model.constant("MAX_DATA_SIZE: constant(uint256) = 100")
    data = model.storage_var(f"data: DynArray[uint256, {max_size}]")

    # internal function to validate index
    validate_index = model.function("_validate_index(idx: uint256)").internal().view()
    validate_index.body(
        f"""
        assert idx < len({data}), "Index out of bounds"
    """
    ).done()

    # internal function to swap elements
    swap = model.function("_swap(i: uint256, j: uint256)").internal()
    swap.body(
        f"""
        {validate_index}(i)
        {validate_index}(j)
        temp: uint256 = {data}[i]
        {data}[i] = {data}[j]
        {data}[j] = temp
    """
    ).done()

    # internal function to bubble sort
    sort = model.function("_bubble_sort()").internal()
    sort.body(
        f"""
        n: uint256 = len({data})
        for i: uint256 in range(n, bound={max_size}):
            for j: uint256 in range(n - i - 1, bound={max_size}):
                if {data}[j] > {data}[j + 1]:
                    {swap}(j, j + 1)
    """
    ).done()

    code = (
        model.function("add(val: uint256)")
        .external()
        .body(f"{data}.append(val)")
        .done()
        .function("sort_data()")
        .external()
        .body(f"{sort}()")
        .done()
        .function("get(idx: uint256) -> uint256")
        .external()
        .view()
        .body(
            f"""
            {validate_index}(idx)
            return {data}[idx]
        """
        )
        .done()
        .build()
    )

    c = get_contract(code)

    # add unsorted data
    c.add(5)
    c.add(2)
    c.add(8)
    c.add(1)

    # sort
    c.sort_data()

    # check sorted
    assert c.get(0) == 1
    assert c.get(1) == 2
    assert c.get(2) == 5
    assert c.get(3) == 8


@pytest.mark.parametrize("decimals,multiplier", [(6, 10**6), (18, 10**18), (2, 100)])
def test_parametrized_with_constants(get_contract, decimals, multiplier):
    """Parametrized test with constants."""
    model = CodeModel()

    # constant based on parameter
    model.constant(f"DECIMALS: constant(uint8) = {decimals}")
    model.constant(f"MULTIPLIER: constant(uint256) = {multiplier}")

    bal = model.storage_var("bal: uint256")

    code = (
        model.function("deposit(tokens: uint256)")
        .external()
        .body(f"{bal} += tokens * MULTIPLIER")
        .done()
        .function("get_balance() -> uint256")
        .external()
        .view()
        .body(f"return {bal}")
        .done()
        .function("get_decimals() -> uint8")
        .external()
        .pure()
        .body("return DECIMALS")
        .done()
        .build()
    )

    c = get_contract(code)

    assert c.get_decimals() == decimals
    c.deposit(5)
    assert c.get_balance() == 5 * multiplier
