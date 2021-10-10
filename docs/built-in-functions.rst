.. index:: function, built-in;

.. _built_in_functions:

Built in Functions
##################

Vyper provides a collection of built in functions available in the global namespace of all
contracts.

Bitwise Operations
==================

.. py:function:: bitwise_and(x: uint256, y: uint256) -> uint256

    Perform a "bitwise and" operation. Each bit of the output is 1 if the corresponding bit of ``x`` AND of ``y`` is 1, otherwise it's 0.

    .. code-block:: python

        @external
        @view
        def foo(x: uint256, y: uint256) -> uint256:
            return bitwise_and(x, y)

    .. code-block:: python

        >>> ExampleContract.foo(31337, 8008135)
        12353

.. py:function:: bitwise_not(x: uint256) -> uint256

    Return the complement of ``x`` - the number you get by switching each 1 for a 0 and each 0 for a 1.

    .. code-block:: python

        @external
        @view
        def foo(x: uint256) -> uint256:
            return bitwise_not(x)

    .. code-block:: python

        >>> ExampleContract.foo(0)
        115792089237316195423570985008687907853269984665640564039457584007913129639935

.. py:function:: bitwise_or(x: uint256, y: uint256) -> uint256

    Perform a "bitwise or" operation. Each bit of the output is 0 if the corresponding bit of ``x`` AND of ``y`` is 0, otherwise it's 1.

    .. code-block:: python

        @external
        @view
        def foo(x: uint256, y: uint256) -> uint256:
            return bitwise_or(x, y)

    .. code-block:: python

        >>> ExampleContract.foo(31337, 8008135)
        8027119

.. py:function:: bitwise_xor(x: uint256, y: uint256) -> uint256

    Perform a "bitwise exclusive or" operation. Each bit of the output is the same as the corresponding bit in ``x`` if that bit in ``y`` is 0, and it's the complement of the bit in ``x`` if that bit in ``y`` is 1.

    .. code-block:: python

        @external
        @view
        def foo(x: uint256, y: uint256) -> uint256:
            return bitwise_xor(x, y)

    .. code-block:: python

        >>> ExampleContract.foo(31337, 8008135)
        8014766

.. py:function:: shift(x: uint256, _shift: int128) -> uint256

    Return ``x`` with the bits shifted ``_shift`` places. A positive ``_shift`` value equals a left shift, a negative value is a right shift.

    .. code-block:: python

        @external
        @view
        def foo(x: uint256, y: int128) -> uint256:
            return shift(x, y)

    .. code-block:: python

        >>> ExampleContract.foo(2, 8)
        512

Chain Interaction
=================

.. py:function:: create_forwarder_to(target: address, value: uint256 = 0[, salt: bytes32]) -> address

    Deploys a small contract that duplicates the logic of the contract at ``target``, but has it's own state since every call to ``target`` is made using ``DELEGATECALL`` to ``target``. To the end user, this should be indistinguishable from an independantly deployed contract with the same code as ``target``.

.. note::

  It is very important that the deployed contract at ``target`` is code you know and trust, and does not implement the ``selfdestruct`` opcode as this will affect the operation of the forwarder contract.

    * ``target``: Address of the contract to duplicate
    * ``value``: The wei value to send to the new contract address (Optional, default 0)
    * ``salt``: A ``bytes32`` value utilized by the ``CREATE2`` opcode (Optional, if supplied deterministic deployment is done via ``CREATE2``)

    Returns the address of the duplicated contract.

    .. code-block:: python

        @external
        def foo(_target: address) -> address:
            return create_forwarder_to(_target)

.. py:function:: raw_call(to: address, data: Bytes, max_outsize: int = 0, gas: uint256 = gasLeft, value: uint256 = 0, is_delegate_call: bool = False, is_static_call: bool = False) -> Bytes[max_outsize]

    Call to the specified Ethereum address.

    * ``to``: Destination address to call to
    * ``data``: Data to send to the destination address
    * ``max_outsize``: Maximum length of the bytes array returned from the call. If the returned call data exceeds this length, only this number of bytes is returned.
    * ``gas``: The amount of gas to attach to the call. If not set, all remainaing gas is forwarded.
    * ``value``: The wei value to send to the address (Optional, default ``0``)
    * ``is_delegate_call``: If ``True``, the call will be sent as ``DELEGATECALL`` (Optional, default ``False``)
    * ``is_static_call``: If ``True``, the call will be sent as ``STATICCALL`` (Optional, default ``False``)

    Returns the data returned by the call as a ``Bytes`` list, with ``max_outsize`` as the max length.

    Returns ``None`` if ``max_outsize`` is omitted or set to ``0``.

    .. note::

        The actual size of the returned data may be less than ``max_outsize``. You can use ``len`` to obtain the actual size.

        Returns the address of the duplicated contract.

    .. code-block:: python

        @external
        @payable
        def foo(_target: address) -> Bytes[32]:
            response: Bytes[32] = raw_call(_target, 0xa9059cbb, max_outsize=32, value=msg.value)
            return response

.. py:function:: raw_log(topics: bytes32[4], data: Union[Bytes, bytes32]) -> None

    Provides low level access to the ``LOG`` opcodes, emitting a log without having to specify an ABI type.

    * ``topics``: List of ``bytes32`` log topics. The length of this array determines which opcode is used.
    * ``data``: Unindexed event data to include in the log. May be given as ``Bytes`` or ``bytes32``.

    .. code-block:: python

        @external
        def foo(_topic: bytes32, _data: Bytes[100]):
            raw_log([_topic], _data)

.. py:function:: selfdestruct(to: address) -> None

    Trigger the ``SELFDESTRUCT`` opcode (``0xFF``), causing the contract to be destroyed.

    * ``to``: Address to forward the contract's ether balance to

    .. warning::

        This method delete the contract from the blockchain. All non-ether assets associated with this contract are "burned" and the contract is no longer accessible.

    .. code-block:: python

        @external
        def do_the_needful():
            selfdestruct(msg.sender)

.. py:function:: send(to: address, value: uint256) -> None

    Send ether from the contract to the specified Ethereum address.

    * ``to``: The destination address to send ether to
    * ``value``: The wei value to send to the address

    .. note::

        The amount to send is always specified in ``wei``.

    .. code-block:: python

        @external
        def foo(_receiver: address, _amount: uint256):
            send(_receiver, _amount)

Cryptography
============

.. py:function:: ecadd(a: uint256[2], b: uint256[2]) -> uint256[2]

    Take two points on the Alt-BN128 curve and add them together.

    .. code-block:: python

        @external
        @view
        def foo(x: uint256[2], y: uint256[2]) -> uint256[2]:
            return ecadd(x, y)

    .. code-block:: python

        >>> ExampleContract.foo([1, 2], [1, 2])
        [
            1368015179489954701390400359078579693043519447331113978918064868415326638035,
            9918110051302171585080402603319702774565515993150576347155970296011118125764,
        ]

.. py:function:: ecmul(point: uint256[2], scalar: uint256) -> uint256[2]

    Take a point on the Alt-BN128 curve (``p``) and a scalar value (``s``), and return the result of adding the point to itself ``s`` times, i.e. ``p * s``.

    * ``point``: Point to be multiplied
    * ``scalar``: Scalar value

    .. code-block:: python

        @external
        @view
        def foo(point: uint256[2], scalar: uint256) -> uint256[2]:
            return ecmul(point, scalar)

    .. code-block:: python

        >>> ExampleContract.foo([1, 2], 3)
        [
            3353031288059533942658390886683067124040920775575537747144343083137631628272,
            19321533766552368860946552437480515441416830039777911637913418824951667761761,
        ]

.. py:function:: ecrecover(hash: bytes32, v: uint256, r: uint256, s: uint256) -> address

    Recover the address associated with the public key from the given elliptic curve signature.

    * ``r``: first 32 bytes of signature
    * ``s``: second 32 bytes of signature
    * ``v``: final 1 byte of signature

    Returns the associated address, or ``0`` on error.

    .. code-block:: python

        @external
        @view
        def foo(hash: bytes32, v: uint256, r:uint256, s:uint256) -> address:
            return ecrecover(hash, v, r, s)
    
    .. code-block:: python

        >>> ExampleContract.foo('0x6c9c5e133b8aafb2ea74f524a5263495e7ae5701c7248805f7b511d973dc7055',
             28,
             78616903610408968922803823221221116251138855211764625814919875002740131251724, 
             37668412420813231458864536126575229553064045345107737433087067088194345044408
            )
        '0x9eE53ad38Bb67d745223a4257D7d48cE973FeB7A'

.. py:function:: keccak256(_value) -> bytes32

    Return a ``keccak256`` hash of the given value.

    * ``_value``: Value to hash. Can be a literal string, ``Bytes``, or ``bytes32``.

    .. code-block:: python

        @external
        @view
        def foo(_value: Bytes[100]) -> bytes32
            return keccak256(_value)

    .. code-block:: python

        >>> ExampleContract.foo(b"potato")
        0x9e159dfcfe557cc1ca6c716e87af98fdcb94cd8c832386d0429b2b7bec02754f

.. py:function:: sha256(_value) -> bytes32

    Return a ``sha256`` (SHA2 256bit output) hash of the given value.

    * ``_value``: Value to hash. Can be a literal string, ``Bytes``, or ``bytes32``.

    .. code-block:: python

        @external
        @view
        def foo(_value: Bytes[100]) -> bytes32
            return sha256(_value)

    .. code-block:: python

        >>> ExampleContract.foo(b"potato")
        0xe91c254ad58860a02c788dfb5c1a65d6a8846ab1dc649631c7db16fef4af2dec

Data Manipulation
=================

.. py:function:: concat(a, b, *args) -> Union[Bytes, String]

    Take 2 or more bytes arrays of type ``bytes32``, ``Bytes`` or ``String`` and combine them into a single value.

    If the input arguments are ``String`` the return type is ``String``.  Otherwise the return type is ``Bytes``.

    .. code-block:: python

        @external
        @view
        def foo(a: String[5], b: String[5], c: String[5]) -> String[100]:
            return concat(a, " ", b, " ", c, "!")

    .. code-block:: python

        >>> ExampleContract.foo("why","hello","there")
        "why hello there!"

.. py:function:: convert(value, type_) -> Any

    Converts a variable or literal from one type to another.

    * ``value``: Value to convert
    * ``type_``: The destination type to convert to (``bool``, ``decimal``, ``int128``, ``uint256`` or ``bytes32``)

    Returns a value of the type specified by ``type_``.

    For more details on available type conversions, see :ref:`type_conversions`.

.. py:function:: extract32(b: Bytes, start: int128, output_type=bytes32) -> Any

    Extract a value from a ``Bytes`` list.

    * ``b``: ``Bytes`` list to extract from
    * ``start``: Start point to extract from
    * ``output_type``: Type of output (``bytes32``, ``int128``, or ``address``). Defaults to ``bytes32``.

    Returns a value of the type specified by ``output_type``.

    .. code-block:: python

        @external
        @view
        def foo(Bytes[32]) -> address:
            return extract32(b, 12, output_type=address)

    .. code-block:: python

        >>> ExampleContract.foo("0x0000000000000000000000009f8F72aA9304c8B593d555F12eF6589cC3A579A2")
        "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2"

.. py:function:: slice(b: Union[Bytes, bytes32, String], start: uint256, length: uint256) -> Union[Bytes, String]

    Copy a list of bytes and return a specified slice.

    * ``b``: value being sliced
    * ``start``: start position of the slice
    * ``length``: length of the slice

    If the value being sliced is a ``Bytes`` or ``bytes32``, the return type is ``Bytes``.  If it is a ``String``, the return type is ``String``.

    .. code-block:: python

        @external
        @view
        def foo(s: string[32]) -> string[5]:
            return slice(s, 4, 5)

    .. code-block:: python

        >>> ExampleContract.foo("why hello! how are you?")
        "hello"

Math
====

.. py:function:: abs(value: int256) -> int256

    Return the absolute value of a signed integer.

    * ``value``: Integer to return the absolute value of

    .. code-block:: python

        @external
        @view
        def foo(value: int256) -> int256:
            return abs(value)

    .. code-block:: python

        >>> ExampleContract.foo(-31337)
        31337

.. py:function:: ceil(value: decimal) -> int128

    Round a decimal up to the nearest integer.

    * ``value``: Decimal value to round up

    .. code-block:: python

        @external
        @view
        def foo(value: decimal) -> uint256:
            return ceil(value)

    .. code-block:: python

        >>> ExampleContract.foo(3.1337)
        4

.. py:function:: floor(value: decimal) -> int128

    Round a decimal down to the nearest integer.

    * ``value``: Decimal value to round down

    .. code-block:: python

        @external
        @view
        def foo(value: decimal) -> uint256:
            return floor(value)

    .. code-block:: python

        >>> ExampleContract.foo(3.1337)
        3

.. py:function:: max(a: numeric, b: numeric) -> numeric

    Return the creater value of ``a`` and ``b``. The input values may be any numeric type as long as they are both of the same type.  The output value is the same as the input values.

    .. code-block:: python

        @external
        @view
        def foo(a: uint256, b: uint256) -> uint256:
            return max(a, b)

    .. code-block:: python

        >>> ExampleContract.foo(23, 42)
        42

.. py:function:: min(a: numeric, b: numeric) -> numeric

    Returns the lesser value of ``a`` and ``b``. The input values may be any numeric type as long as they are both of the same type.  The output value is the same as the input values.

    .. code-block:: python

        @external
        @view
        def foo(a: uint256, b: uint256) -> uint256:
            return min(a, b)

    .. code-block:: python

        >>> ExampleContract.foo(23, 42)
        23

.. py:function:: pow_mod256(a: uint256, b: uint256) -> uint256

    Return the result of ``a ** b % (2 ** 256)``.

    This method is used to perform exponentiation without overflow checks.

    .. code-block:: python

        @external
        @view
        def foo(a: uint256, b: uint256) -> uint256:
            return pow_mod256(a, b)

    .. code-block:: python

        >>> ExampleContract.foo(2, 3)
        8
        >>> ExampleContract.foo(100, 100)
        59041770658110225754900818312084884949620587934026984283048776718299468660736

.. py:function:: sqrt(d: decimal) -> decimal

    Return the square root of the provided decimal number, using the Babylonian square root algorithm.

    .. code-block:: python

        @external
        @view
        def foo(d: decimal) -> decimal:
            return sqrt(d)

    .. code-block:: python

        >>> ExampleContract.foo(9.0)
        3.0

.. py:function:: uint256_addmod(a: uint256, b: uint256, c: uint256) -> uint256

    Return the modulo of ``(a + b) % c``. Reverts if ``c == 0``.

    .. code-block:: python

        @external
        @view
        def foo(a: uint256, b: uint256, c: uint256) -> uint256:
            return uint256_addmod(a, b, c)

    .. code-block:: python

        >>> (6 + 13) % 8
        3
        >>> ExampleContract.foo(6, 13, 8)
        3

.. py:function:: uint256_mulmod(a: uint256, b: uint256, c: uint256) -> uint256

    Return the modulo from ``(a * b) % c``. Reverts if ``c == 0``.

    .. code-block:: python

        @external
        @view
        def foo(a: uint256, b: uint256, c: uint256) -> uint256:
            return uint256_mulmod(a, b, c)

    .. code-block:: python

        >>> (11 * 2) % 5
        2
        >>> ExampleContract.foo(11, 2, 5)
        2

Utilities
=========

.. py:function:: as_wei_value(_value, unit: str) -> uint256

    Take an amount of ether currency specified by a number and a unit and return the integer quantity of wei equivalent to that amount.

    * ``_value``: Value for the ether unit. Any numeric type may be used, however the value cannot be negative.
    * ``unit``: Ether unit name (e.g. ``"wei"``, ``"ether"``, ``"gwei"``, etc.) indicating the denomination of ``_value``. Must be given as a literal string.

    .. code-block:: python

        @external
        @view
        def foo(s: String[32]) -> uint256:
            return as_wei_value(1.337, "ether")

    .. code-block:: python

        >>> ExampleContract.foo(1)
        1337000000000000000

.. py:function:: blockhash(block_num: uint256) -> bytes32

    Return the hash of the block at the specified height.

    .. note::

        The EVM only provides access to the most 256 blocks. This function returns ``EMPTY_BYTES32`` if the block number is greater than or equal to the current block number or more than 256 blocks behind the current block.

    .. code-block:: python

        @external
        @view
        def foo() -> bytes32:
            return blockhash(block.number - 16)

    .. code-block:: python

        >>> ExampleContract.foo()
        0xf3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

.. py:function:: empty(typename) -> Any

    Return a value which is the default (zeroed) value of its type. Useful for initializing new memory variables.

    * ``typename``: Name of the type

    .. code-block:: python

        @external
        @view
        def foo():
            x: uint256[2][5] = empty(uint256[2][5])

.. py:function:: len(b: Union[Bytes, String]) -> uint256

    Return the length of a given ``Bytes`` or ``String``.

    .. code-block:: python

        @external
        @view
        def foo(s: String[32]) -> uint256:
            return len(s)

    .. code-block:: python

        >>> ExampleContract.foo("hello")
        5

.. py:function:: method_id(method, output_type: type = Bytes[4]) -> Union[bytes32, Bytes[4]]

    Takes a function declaration and returns its method_id (used in data field to call it).

    * ``method``: Method declaration as given as a literal string
    * ``output_type``: The type of output (``Bytes[4]`` or ``bytes32``). Defaults to ``Bytes[4]``.

    Returns a value of the type specified by ``output_type``.

    .. code-block:: python

        @external
        @view
        def foo() -> Bytes[4]:
            return method_id('transfer(address,uint256)', output_type=Bytes[4])

    .. code-block:: python

        >>> ExampleContract.foo()

.. py:function:: _abi_encode(\*args, ensure_tuple: bool = True) -> Bytes[<depends on input>]

    BETA, USE WITH CARE.
    Takes a variable number of args as input, and returns the ABIv2-encoded bytestring. Used for packing arguments to raw_call, EIP712 and other cases where a consistent and efficient serialization method is needed.
    Once this function has seen more use we provisionally plan to put it into the ``ethereum.abi`` namespace.

    * ``*args``: Arbitrary arguments
    * ``ensure_tuple``: If set to True, ensures that even a single argument is encoded as a tuple. In other words, ``bytes`` gets encoded as ``(bytes,)``, and ``(bytes,)`` gets encoded as ``((bytes,),)`` This is the calling convention for Vyper and Solidity functions. Except for very specific use cases, this should be set to True. Must be a literal.
    * ``method_id``: A literal hex or Bytes[4] value to append to the beginning of the abi-encoded bytestring.

    Returns a bytestring whose max length is determined by the arguments. For example, encoding a ``Bytes[32]`` results in a ``Bytes[64]`` (first word is the length of the bytestring variable).

    .. code-block:: python

        @external
        @view
        def foo() -> Bytes[132]:
            x: uint256 = 1
            y: Bytes[32] = "234"
            return _abi_encode(x, y, method_id=method_id("foo()"))

    .. code-block:: python

        >>> ExampleContract.foo().hex()
        "c2985578"
        "0000000000000000000000000000000000000000000000000000000000000001"
        "0000000000000000000000000000000000000000000000000000000000000040"
        "0000000000000000000000000000000000000000000000000000000000000003"
        "3233340000000000000000000000000000000000000000000000000000000000"
