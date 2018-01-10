.. index:: function, built-in;

.. _built_in_functions:

***********************
Built in Functions
***********************

Vyper contains a set amount of built in functions that would be timely and/or unachievable to write in Vyper.

.. _functions:

Functions
=========
* **floor**
::

  def floor(a) -> b:
    """
    :param a: value to round down
    :type a: either decimal or num

    :output b: integer
    """
Rounds a decimal down to the nearest integer.

* **decimal**
::

  def decimal(a) -> b:
    """
    :param a: value to turn into decimal
    :type a: either decimal or num

    :output b: decimal
    """
Turns a number into a decimal.

* **as_unitless_number**
::

  def as_unitless_number(a) -> b:
    """
    :param a: value to remove units from
    :type a: either decimal or num

    :output b: either decimal or num
    """
Turns a ``num`` or ``decimal`` with units into one without units (used for assignment and math).

* **as_num128**
::

  def as_num128(a) -> b:
    """
    :param a: value to turn into int128
    :type a: either num, bytes32, num256, or bytes

    :output b: num
    """
Turns input into a ``num`` (int128).

* **as_num256**
::

  def as_num256(a) -> b:
    """
    :param a: value to turn into num256
    :type a: either num_literal, num, bytes32, or address

    :output b: num256
    """
Turns input into a ``num256`` (uint256).

* **as_bytes32**
::

  def as_bytes32(a) -> b:
    """
    :param a: value to turn into bytes32
    :type a: either num, num256, address

    :output b: bytes32
    """
Turns input into a ``bytes32``.
* **slice**
::

  def slice(a, start=b, length=c) -> d:
    """
    :param a: bytes to be sliced
    :type a: either bytes or bytes32
    :param b: start position of the slice
    :type b: num
    :param c: length of the slice
    :type c: num

    :output d: bytes
    """
Takes a list of bytes and copies, then returns a specified chunk.

* **len**
::

  def len(a) -> b:
    """
    :param a: value to get the length of
    :type a: bytes

    :output b: num
    """
Returns the length of a given list of bytes.

* **concat**
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
::

  def keccak256(a) -> b:
    """
    :param a: value to hash
    :type a: either str_literal, bytes, bytes32

    :output b: bytes32
    """
Returns ``keccak_256`` (Ethereums sha3) hash of input.

* **method_id**
::

  def method_id(a) -> b:
    """
    :param a: method declaration
    :type a: str_literal

    :output b: bytes
    """

Takes a function declaration and returns its method_id (used in data field to call it).

* **ecrecover**
::

  def ecrecover(hash, v, r, s) -> b:
    """
    :param hash: a signed hash
    :type hash: bytes32
    :param v:
    :type v: num256
    :param r: elliptic curve point
    :type r: num256
    :param s: elliptic curve point
    :type s: num256

    :output b: address
    """

Takes a signed hash and vrs and returns the public key of the signer.

* **ecadd**
::

  def ecadd(a, b) -> sum:
    """
    :param a: pair to be added
    :type a: num252[2]
    :param b: pair to be added
    :type b: num252[2]

    :output sum: num256[2]
    """

Takes two elliptical curves and adds them together.

* **ecmul**
::

  def ecmul(a, b) -> product:
    """
    :param a: pair to be multiplied
    :type a: num252[2]
    :param b: pair to be multiplied
    :type b: num252[2]

    :output product: num256[2]
    """

Takes two elliptical curves and multiplies them together.

* **extract32**
::

  def extract32(a, b, type=c) -> d:
    """
    :param a: where 32 bytes are extracted from
    :type a: bytes
    :param b: start point of bytes to be extracted
    :type b: num
    :param c: type of output
    :type c: either bytes32, num128, or address

    :output d: either bytes32, num128, or address
    """

Takes a byte array and extracts 32 bytes from it.

* **bytes_to_num**
::

  def bytes_to_num(a) -> b:
    """
    :param a: bytes to be transformed
    :type a: bytes

    :output d: num
    """

Transforms bytes to num.
