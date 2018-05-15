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
    :type a: either decimal or int128

    :output b: integer
    """
Rounds a decimal down to the nearest integer.

**decimal**
-----------
::

  def decimal(a) -> b:
    """
    :param a: value to turn into decimal
    :type a: either decimal or int128

    :output b: decimal
    """
Turns a number into a decimal.

**as_unitless_number**
-------------------------
::

  def as_unitless_number(a) -> b:
    """
    :param a: value to remove units from
    :type a: either decimal or int128

    :output b: either decimal or int128
    """
Turns a ``int128`` or ``decimal`` with units into one without units (used for assignment and math).

**as_num128**
---------------
::

  def as_num128(a) -> b:
    """
    :param a: value to turn into int128
    :type a: either int128, bytes32, uint256, or bytes

    :output b: int128
    """
Turns input into a int128.

**as_uint256**
----------------
::

  def as_uint256(a) -> b:
    """
    :param a: value to turn into uint256
    :type a: either num_literal, int128, bytes32, or address

    :output b: uint256
    """
Turns input into a ``uint256`` (uint256).

**as_bytes32**
----------------
::

  def as_bytes32(a) -> b:
    """
    :param a: value to turn into bytes32
    :type a: either int128, uint256, address

    :output b: bytes32
    """
Turns input into a ``bytes32``.

**slice**
---------
::

  def slice(a, start=b, length=c) -> d:
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
    :type a: bytes
    :param b: value to combine
    :type b: bytes

    :output b: bytes
    """
Takes 2 or more bytes arrays of type ``bytes32`` or ``bytes`` and combines them into one.

* **keccak256 (sha3)**
----------------------
::

  def keccak256(a) -> b:
    """
    :param a: value to hash
    :type a: either str_literal, bytes, bytes32

    :output b: bytes32
    """
Returns ``keccak_256`` (Ethereums sha3) hash of input.

**method_id**
---------------
::

  def method_id(a) -> b:
    """
    :param a: method declaration
    :type a: str_literal

    :output b: bytes
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
    :type a: num252[2]
    :param b: pair to be added
    :type b: num252[2]

    :output sum: uint256[2]
    """

Takes two elliptical curves and adds them together.

**ecmul**
---------------
::

  def ecmul(a, b) -> product:
    """
    :param a: pair to be multiplied
    :type a: num252[2]
    :param b: pair to be multiplied
    :type b: num252[2]

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
    :param c: type of output
    :type c: either bytes32, num128, or address

    :output d: either bytes32, num128, or address
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
