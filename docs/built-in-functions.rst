.. index:: function, built-in;

.. _built_in_functions:

***********************
Built in Functions
***********************

Vyper contains a set amount of built in functions that would be timely and/or unachievable to write in Vyper.

.. _functions:

Functions
=========
**floor**
---------
::

  def floor(a) -> b:
    """
    :param a: value to round down
    :type a: decimal

    :output b: int128
    """

Rounds a decimal down to the nearest integer.

**ceil**
---------
::

  def ceil(a) -> b:
    """
    :param a: value to round up
    :type a: decimal

    :output b: int128
    """

Rounds a decimal up to the nearest integer.

**convert**
-------------------------
::

  def convert(a, b) -> c:
    """
    :param a: value to convert
    :type a: either bool, decimal, int128, uint256 or bytes32
    :param b: the destination type to convert to
    :type b: type of either decimal, int128, uint256 or bytes32

    :output c: either decimal, int128, uint256 or bytes32
    """

Converts a variable/ literal from one type to another.

**clear**
-------------------------
::

  def clear(a):
    """
    :param a: variable to reset to its default value
    :type a: all types
    """

Clears a variable's contents to the default value of its type.

**as_wei_value**
-------------------------
::

  def as_wei_value(a, b) -> c:
    """
    :param a: value for the ether unit
    :type a: uint256 or int128 or decimal
    :param b: ether unit name (e.g. ``"wei"``)
    :type b: str_literal

    :output c: wei_value
    """

The value of the input number as ``wei``, converted based on the specified unit.

**as_unitless_number**
-------------------------
::

  def as_unitless_number(a) -> b:
    """
    :param a: value to remove units from
    :type a: either decimal or int128

    :output b: either decimal or int128
    """

Turns a ``int128``, ``uint256``, ``decimal`` with units into one without units (used for assignment and math).

**slice**
---------
::

  def slice(a, start=b, len=c) -> d:
    """
    :param a: bytes to be sliced
    :type a: either bytes or bytes32
    :param b: start position of the slice
    :type b: int128
    :param c: length of the slice
    :type c: int128

    :output d: bytes
    """

Takes a list of bytes and copies, then returns a specified chunk.

**len**
-------
::

  def len(a) -> b:
    """
    :param a: value to get the length of
    :type a: bytes

    :output b: int128
    """

Returns the length of a given list of bytes.

**concat**
----------
::

  def concat(a, b, ...) -> c:
    """
    :param a: value to combine
    :type a: bytes, bytes32
    :param b: value to combine
    :type b: bytes, bytes32

    :output b: bytes
    """

Takes 2 or more bytes arrays of type ``bytes32`` or ``bytes`` and combines them into one.

**sha3/ keccak256**
--------------------
::

  def sha3(a) -> b:
    """
    :param a: value to hash
    :type a: either str_literal, bytes, bytes32

    :output b: bytes32
    """

Returns ``keccak256`` (Ethereum's sha3) hash of input.
Note that it can be called either by using ``sha3`` or ``keccak256``.


**sha256**
--------------------
::

  def sha256(a) -> b:
    """
    :param a: value to hash
    :type a: either str_literal, bytes, bytes32

    :output b: bytes32
    """

Returns ``sha256`` (SHA2 256bit output) hash of input.


**sqrt**
--------
::

  def sqrt(a: decimal) -> decimal:
    """
    :param a:
    :type a: decimal, larger than 0.0

    :output sqrt: decimal
    """

Returns the suare of the provided decimal number, using the Babylonian square root algorithm.


**method_id**
---------------
::

  def method_id(a, b) -> c:
    """
    :param a: method declaration
    :type a: str_literal
    :param b: type of output
    :type b: either bytes32 or bytes[4]

    :output c: either bytes32 or bytes[4]
    """

Takes a function declaration and returns its method_id (used in data field to call it).

**ecrecover**
---------------
::

  def ecrecover(hash, v, r, s) -> b:
    """
    :param hash: a signed hash
    :type hash: bytes32
    :param v:
    :type v: uint256
    :param r: elliptic curve point
    :type r: uint256
    :param s: elliptic curve point
    :type s: uint256

    :output b: address
    """

Takes a signed hash and vrs and returns the public key of the signer.

**ecadd**
---------------
::

  def ecadd(a, b) -> sum:
    """
    :param a: pair to be added
    :type a: uint256[2]
    :param b: pair to be added
    :type b: uint256[2]

    :output sum: uint256[2]
    """

Takes two elliptical curves and adds them together.

**ecmul**
---------------
::

  def ecmul(a, b) -> product:
    """
    :param a: pair to be multiplied
    :type a: uint256[2]
    :param b: number to be multiplied
    :type b: uint256

    :output product: uint256[2]
    """

Takes two elliptical curves and multiplies them together.

**extract32**
---------------
::

  def extract32(a, b, type=c) -> d:
    """
    :param a: where 32 bytes are extracted from
    :type a: bytes
    :param b: start point of bytes to be extracted
    :type b: int128
    :param c: type of output (Optional, default: bytes32)
    :type c: either bytes32, int128, or address

    :output d: either bytes32, int128, or address
    """

**RLPList**
---------------
::

  def _RLPList(a, b) -> c:
    """
    :param a: encoded data
    :type a: bytes
    :param b: RLP list
    :type b: list

    :output c: LLLnode
    """

Takes encoded RLP data and an unencoded list of types. Usage::

  vote_msg: bytes <= 1024 = ...

  values = RLPList(vote_msg, [int128, int128, bytes32, bytes, bytes])

  var1: int128 = values[0]
  var2: int128 = values[1]
  var3: bytes32 = values[2]
  var4: bytes <= 1024 = values[3]
  var5: bytes <= 1024 = values[4]

Note: RLP decoder needs to be deployed if one wishes to use it outside of the Vyper test suite. Eventually, the decoder will be available on mainnet at a fixed address. But for now, here's how to create RLP decoder on other chains:

\1. send 6270960000000000 wei to 0xd2c560282c9C02465C2dAcdEF3E859E730848761

\2. Publish this tx to create the contract::

   0xf90237808506fc23ac00830330888080b902246102128061000e60003961022056600060007f010000000000000000000000000000000000000000000000000000000000000060003504600060c082121515585760f882121561004d5760bf820336141558576001905061006e565b600181013560f783036020035260005160f6830301361415585760f6820390505b5b368112156101c2577f010000000000000000000000000000000000000000000000000000000000000081350483602086026040015260018501945060808112156100d55760018461044001526001828561046001376001820191506021840193506101bc565b60b881121561014357608081038461044001526080810360018301856104600137608181141561012e5760807f010000000000000000000000000000000000000000000000000000000000000060018401350412151558575b607f81038201915060608103840193506101bb565b60c08112156101b857600182013560b782036020035260005160388112157f010000000000000000000000000000000000000000000000000000000000000060018501350402155857808561044001528060b6838501038661046001378060b6830301830192506020810185019450506101ba565bfe5b5b5b5061006f565b601f841315155857602060208502016020810391505b6000821215156101fc578082604001510182826104400301526020820391506101d8565b808401610420528381018161044003f350505050505b6000f31b2d4f

\3. This is the contract address: 0xCb969cAAad21A78a24083164ffa81604317Ab603

****************************
Low Level Built in Functions
****************************

Vyper contains a set of built in functions which executes unique OPCODES such as send or selfdestruct.

.. low_level_functions:

Low Level Functions
===================

**send**
--------
::

  def send(a, b):
    """
    :param a: the destination address to send ether to
    :type a: address
    :param b: the wei value to send to the address
    :type b: uint256(wei)
    """

Sends ether from the contract to the specified Ethereum address.
Note that the amount to send should be specified in wei.

**raw_call**
------------
::

  def raw_call(a, b, outsize=c, gas=d, value=e, delegate_call=f) -> g:
    """
    :param a: the destination address to call to
    :type a: address
    :param b: the data to send the called address
    :type b: bytes
    :param c: the max-length for the bytes array returned from the call.
    :type c: fixed literal value
    :param d: the gas amount to attach to the call.
    :type d: uint256
    :param e: the wei value to send to the address (Optional, default: 0)
    :type e: uint256
    :param f: the bool of whether or not to use DELEGATECALL (Optional, default: False)
    :type f: bool

    :output g: bytes[outsize]
    """

Calls to the specified Ethereum address.
The call should pass data and may optionally send eth value (specified in wei) as well.
The call must specify a gas amount to attach the call and and the outsize.
Returns the data returned by the call as a bytes array with the outsize as the max length.

**selfdestruct**
----------------
::

  def selfdestruct(a):
    """
    :param a: the address to send the contracts left ether to
    :type a: address
    """

Causes a self destruction of the contract, triggers the ``SELFDESTRUCT`` opcode (0xff).
CAUTION! This method will delete the contract from the Ethereum blockchain. All none ether assets associated with this contract will be "burned" and the contract will be inaccessible.

**raise**
----------
::

  def raise(msg):
    """
    :param a: the exception reason (must be <= 32 bytes)
    :type a: str
    """

Raises an exception by triggering the OPCODE ``REVERT`` (0xfd) with the provided reason given as the error message. The code will stop operation, the contract's state will be reverted to the state before the transaction took place and the remaining gas will be returned to the transaction's sender.

Note: To give it a more Python like syntax, the raise function can be called without parenthesis, the syntax would be ``raise "An exception"``. Even though both options will compile, it's recommended to use the Pythonic version without parentheses.

**assert**
----------
::

  def assert(a, reason=None):
    """
    :param a: the boolean condition to assert
    :type a: bool
    :param reason: the reason provided to REVERT
    :type b: str
    """

Asserts the specified condition. The behavior is equivalent to::
  if not a:
    raise reason
(the only difference in behavior is that ``assert`` can be called without a reason string, while ``raise`` requires a reason string).

Note: To give it a more Python like syntax, the assert function can be called without parenthesis, the syntax would be ``assert your_bool_condition``. Even though both options will compile, it's recommended to use the Pythonic version without parenthesis.

**raw_log**
-----------
::

  def raw_log(a, b):
    """
    :param a: the address of the contract to duplicate.
    :type a: * (any input)
    :param b: the name of the logged event.
    :type b: bytes
    """

Emits a log without specifying the abi type, with the arguments entered as the first input.

**create_forwarder_to**
-----------------------
::

  def create_forwarder_to(a, value=b):
    """
    :param a: the address of the contract to duplicate.
    :type a: address
    :param b: the wei value to send to the new contract instance (Optional, default: 0)
    :type b: uint256(wei)
    """

Duplicates a contract's code and deploys it as a new instance, by means of a DELEGATECALL.
You can also specify wei value to send to the new contract as ``value=the_value``.


**blockhash**
---------------
::

  def blockhash(a) -> hash:
    """
    :param a: the number of the block to get
    :type a: uint256

    :output hash: bytes32
    """

Returns the hash of the block at the specified height.

**Note: The EVM only provides access to the most 256 blocks. This function will return 0 if the block number is greater than or equal to the current block number or more than 256 blocks behind the current block.**
