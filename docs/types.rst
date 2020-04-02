.. index:: type

.. _types:

Types
#####

Vyper is a statically typed language. This means that the type of each variable (state and local) must be specified or at least known at compile-time. Vyper provides several elementary types which can be combined to form complex types.

In addition, types can interact with each other in expressions containing operators.

.. note::

    Vyper does not currently support short circuiting. All values are evaluated during comparisons and boolean operations.

.. index:: ! value

Value Types
===========

The following types are also called value types because variables of these
types will always be passed by value, i.e. they are always copied when they
are used as function arguments or in assignments.

.. index:: ! bool, ! true, ! false

Boolean
-------

.. py:attribute:: bool

    A boolean is a type to store a logical/truth value.

    .. code-block:: python

        foo: bool = True

    The only possible values are the constants ``True`` and ``False``.

Operators
*********

====================  ===================
Operator              Description
====================  ===================
``not x``             Logical negation
``x and y``           Logical conjunction
``x or y``            Logical disjunction
``x == y``            Equality
``x != y``            Inequality
====================  ===================

.. index:: ! int128, ! int, ! integer

Signed Integer (128 bit)
------------------------

.. py:attribute:: int128

    A 128-bit signed integer is a type to store positive and negative integers.

    .. code-block:: python

        foo: int128 = -42

    :attr:`int128` may contain any integer value between -2\ :sup:`127` and (2\ :sup:`127` - 1), inclusive. Vyper does not allow decimal, hex, binary, or octal literals to be cast as integers.

Operators
*********

Comparisons
^^^^^^^^^^^

Comparisons return a :attr:`bool` value.

==========  ================
Operator    Description
==========  ================
``x < y``   Less than
``x <= y``  Less than or equal to
``x == y``  Equals
``x != y``  Does not equal
``x >= y``  Greater than or equal to
``x > y``   Greater than
==========  ================

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

* Arithmetic operations cannot be performed between different numeric types.
* The result of division is always truncated. For example, ``-5 / 3`` returns ``-1``.
* A transaction will revert if the result of an arithmetic operation would exceed the numeric bounds for the given type.
* A transaction will revert on an attempt to divide by zero or modulus zero.

=============  ======================
Operator       Description
=============  ======================
``x + y``      Addition
``x - y``      Subtraction
``-x``         Unary minus/Negation
``x * y``      Multiplication
``x / y``      Division
``x**y``       Exponentiation
``x % y``      Modulo
``min(x, y)``  Minimum
``max(x, y)``  Maximum
=============  ======================

.. index:: ! unit, ! uint256

Unsigned Integer (256 bit)
--------------------------

.. py:attribute:: uint256

    An unsigned integer (256 bit) is a type to store non-negative integers.

    .. code-block:: python

        foo: uint256 = 31337

    :attr:`uint256` may contain any integer value between 0 and (2\ :sup:`256`-1), inclusive.  Vyper does not allow decimal, hex, binary, or octal literals to be cast as integers.

Operators
*********

Comparisons
^^^^^^^^^^^

Comparisons return a boolean value.

==========  ================
Operator    Description
==========  ================
``x < y``   Less than
``x <= y``  Less than or equal to
``x == y``  Equals
``x != y``  Does not equal
``x >= y``  Greater than or equal to
``x > y``   Greater than
==========  ================

``x`` and ``y`` must be of the type :attr:`uint256`.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

* Arithmetic operations cannot be performed between different numeric types.
* The result of division is always truncated. For example, ``5 / 3`` returns ``1``.
* A transaction will revert if the result of an arithmetic operation would exceed the numeric bounds for the given type.
* A transaction will revert on an attempt to divide by zero or modulus zero.

===========================  ======================
Operator                     Description
===========================  ======================
``x + y``                    Addition
``x - y``                    Subtraction
``uint256_addmod(x, y, z)``  Addition modulo ``z``
``x * y``                    Multiplication
``uint256_mulmod(x, y, z)``  Multiplication modulo ``z``
``x / y``                    Division
``x**y``                     Exponentiation
``x % y``                    Modulo
``min(x, y)``                Minimum
``max(x, y)``                Maximum
===========================  ======================

Bitwise Operators
^^^^^^^^^^^^^^^^^

===================== =============
Operator              Description
===================== =============
``bitwise_and(x, y)`` AND
``bitwise_or(x, y)``  OR
``bitwise_xor(x, y)`` XOR
``bitwise_not(x)``    NOT
``shift(x, _shift)``  Bitwise Shift
===================== =============

``x`` and ``y`` must be of the type :attr:`uint256`. ``_shift`` must be of the type :attr:`int128`.

.. note::
    Positive ``_shift`` equals a left shift; negative ``_shift`` equals a right shift.
    Values shifted above/below the most/least significant bit get discarded.

Decimals
--------

.. py:attribute:: decimal

    A decimal is a type to store a decimal fixed point value.

    .. code-block:: python

        foo: decimal = 1.28

    :attr:`decimal` may contain any value between -2\ :sup:`127` and (2\ :sup:`127` - 1), inclusive, with a precision of up to 10 decimal places.

    Vyper does not allow implicit casting of integer literals to decimals. ``1`` must be written as ``1.0``.

Operators
*********

Comparisons
^^^^^^^^^^^

Comparisons return a :attr:`bool` value.

==========  ================
Operator    Description
==========  ================
``x < y``   Less than
``x <= y``  Less or equal
``x == y``  Equals
``x != y``  Does not equal
``x >= y``  Greater or equal
``x > y``   Greater than
==========  ================

``x`` and ``y`` must be of the type :attr:`decimal`.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

* Arithmetic operations cannot be performed between different numeric types.
* The result of division is always truncated at ten decimal places. For example, ``-5.0 / 3.0`` returns ``-1.6666666666``.
* A transaction will revert if the result of an arithmetic operation would exceed the numeric bounds for the given type.
* A transaction will revert on an attempt to divide by zero or modulus zero.
* Exponentiation is not possible on decimal values.

=============  ==========================================
Operator       Description
=============  ==========================================
``x + y``      Addition
``x - y``      Subtraction
``-x``         Unary minus/Negation
``x * y``      Multiplication
``x / y``      Division
``x % y``      Modulo
``min(x, y)``  Minimum
``max(x, y)``  Maximum
``floor(x)``   Largest integer <= ``x``. Returns :attr:`int128`.
``ceil(x)``    Smallest integer >= ``x``. Returns :attr:`int128`.
=============  ==========================================

``x`` and ``y`` must be of the type :attr:`decimal`.

.. _address:

Address
-------

.. py:attribute:: address

    The address type holds an Ethereum address.


    .. code-block:: python

        foo: address = 0x829BD824B016326A401d083B33D092293333A830

    :attr:`address` must be given as a `checksummed <https://eips.ethereum.org/EIPS/eip-55>`_ 20 byte hexadecimal value.

.. _members-of-addresses:

Members
*******

===============  =========================================================
Member           Description
===============  =========================================================
``balance``      Query the balance of an address. Returns :attr:`uint256`.
``codehash``     Returns the :attr:`bytes32` keccak of the code at an address, or ``EMPTY_BYTES32`` if the account does not currently have code.
``codesize``     Query the code size of an address. Returns :attr:`int128`.
``is_contract``  Query whether it is a contract address. Returns :attr:`bool`.
===============  =========================================================

Syntax as follows: ``_address.<member>``, where ``_address`` is of the type ``address`` and ``<member>`` is one of the above keywords.

.. note::

    Operations such as ``SELFDESTRUCT`` and ``CREATE2`` allow for the removal and replacement of bytecode at an address. Do not assume that values of address members will not change in the future.

32 Byte Fixed-Length Array
--------------------------

.. py:attribute:: bytes32

    A 32 byte fixed-length array that is otherwise similar to byte arrays.

    :attr:`bytes32` may be written in several ways:

    .. code-block:: python

        # 32 byte hexadecimal literal
        foo: bytes32 = 0x7468697274792074776f20636861726163746572206279746520737472696e67

        # 32 character byte string
        foo: bytes32 = b"thirty two character byte string"

        # 160 bit binary literal
        foo: bytes32 = 0b0111010001101000011010010111001001110100011110010010000001110100011101110110111100100000011000110110100001100001011100100110000101100011011101000110010101110010001000000110001001111001011101000110010100100000011100110111010001110010011010010110111001100111

Operators
*********

====================================  ============================================================
Keyword                               Description
====================================  ============================================================
``keccak256(x)``                      Return the keccak256 hash as :attr:`bytes32`.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================

Where ``x`` is a byte array and ``_start`` as well as ``_len`` are integer values.

Fixed-size Byte Arrays
----------------------

.. py:attribute:: bytes

    A byte array with a fixed size. Written as ``bytes[maxLen]``, where ``maxLen`` is an integer denoting the maximum number of bytes.

    :attr:`bytes` arrays may be written in several ways:

    .. code-block:: python

        # hexadecimal literal
        foo: bytes[5] = 0x010203

        # byte string
        foo: bytes[5] = b"\x01\x02\x03"

        # binary literal
        foo: bytes[5] = 0b10000001000000011

    On the ABI level the fixed-size bytes array is annotated as ``bytes``.

    :attr:`bytes32` and :attr:`bytes[32]<bytes>` both have a maximum length of 32 bytes. The difference is that a :attr:`bytes32` value is always exactly 32 bytes long, whereas a :attr:`bytes[32]<bytes>` value may be anywhere from 0-32 bytes long.

    .. code-block:: python

        foo: bytes[32] = b"hello"  # Valid, the literal is less than 32 bytes
        bar: bytes32 = b"hello"    # Invalid, the literal is not exactly 32 bytes long

Comparisons
***********

Comparisons return a :attr:`bool` value.

==========  ================
Operator    Description
==========  ================
``x == y``  Equals
``x != y``  Does not equal
==========  ================

It is possible to perform comparisons between bytes arrays with different maximum lengths. For example:

.. code-block:: python

    foo: bytes[5] = b"hello"
    bar: bytes[10] = b"hello"
    return foo == bar   # returns True

This is because although ``bar`` has a maximum length of 10, the size of the data in the array is only 5 bytes.

Assignments
***********

It is possible to assign values from a smaller length bytes array to a larger length one, but not in the other direction.

.. code-block:: python

    # Valid
    foo: bytes[5] = b"hello"
    bar: bytes[10] = foo

    # Invalid
    bar: bytes[10] = b"hello"
    foo: bytes[5] = bar

.. index:: !string

Fixed-size Strings
------------------

.. py:attribute:: string

    A string with a fixed size. Written as ``string[maxLen]``, where ``maxLen`` is an integer denoting the maximum number of characters.

    Fixed-size strings can hold strings with equal or fewer characters than the maximum length of the string.

    On the ABI level the Fixed-size string array is annotated as ``string``.

    .. code-block:: python

        foo: string[100] = "Test String"

Operators
*********

====================================  ============================================================
Keyword                               Description
====================================  ============================================================
``len(x)``                            Return the length as an integer.
``keccak256(x)``                      Return the keccak256 hash as :attr:`bytes32`.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================

Where ``x`` is a byte array or string while ``_start`` and ``_len`` are integers.
The ``len``, ``keccak256``, ``concat``, ``slice`` operators can be used with ``string`` and ``bytes`` types.

.. index:: !reference

Reference Types
===============

Reference types do not fit into 32 bytes. Because of this, copying their value is not as feasible as
with value types. Therefore only the location, i.e. the reference, of the data is passed.

.. index:: !arrays

Fixed-size Lists
----------------

Fixed-size lists hold a finite number of elements which belong to a specified type.

Lists are declared with ``_name: _ValueType[_Integer]``. Multidimensional lists are also possible.

**Example:**
::

  #Defining a list
  exampleList: int128[3]
  #Setting values
  exampleList = [10, 11, 12]
  exampleList[2] = 42
  #Returning a value
  return exampleList[0]

.. index:: !structs

Structs
=======

Structs are custom defined types that can group several variables.

Syntax
------

Structs can be accessed via ``struct.argname``.
**Example:**
::

  #Defining a struct
  struct MyStruct:
      value1: int128
      value2: decimal
  exampleStruct: MyStruct
  #Constructing a struct
  exampleStruct = MyStruct({value1: 1, value2: 2})
  #Accessing a value
  exampleStruct.value1 = 1


.. index:: !mapping

Mappings
========

Mappings in Vyper can be seen as `hash tables <https://en.wikipedia.org/wiki/Hash_table>`_ which are virtually initialized such that
every possible key exists and is mapped to a value whose byte-representation is
all zeros: a type's default value. The similarity ends here, though: The key data is not actually stored
in a mapping, only its ``keccak256`` hash used to look up the value. Because of this, mappings
do not have a length or a concept of a key or value being "set".

It is possible to mark mappings ``public`` and have Vyper create a getter.
The ``_KeyType`` will become a required parameter for the getter and it will
return ``_ValueType``.

.. note::
    Mappings are only allowed as state variables.

Syntax
------

Mapping types are declared as ``map(_KeyType, _ValueType)``.
Here ``_KeyType`` can be any base or bytes type. Mappings, contract or structs are not support as key types.
``_ValueType`` can actually be any type, including mappings.

**Example:**
::

   #Defining a mapping
   exampleMapping: map(int128, decimal)
   #Accessing a value
   exampleMapping[0] = 10.1

.. note::
    Mappings can only be accessed, not iterated over.

.. index:: !initial

.. _types-initial:

Initial Values
**************

In Vyper, there is no ``null`` option like most programming languages have. Thus, every variable type has a default value. In order to check if a variable is empty, you will need to compare it to its type's default value.
If you would like to reset a variable to its type's default value, use the built-in ``clear()`` function.

.. note::

    Memory variables must be assigned a value at the time they are declared. :ref:`types-constants` may be used to initialize memory variables with their default values.

Here you can find a list of all types and default values:

.. list-table:: Default Variable Values
   :header-rows: 1

   * - Type
     - Default Value
   * - ``bool``
     - ``False``
   * - ``int128``
     - ``0``
   * - ``uint256``
     - ``0``
   * - ``decimal``
     - ``0.0``
   * - ``address``
     - ``0x0000000000000000000000000000000000000000``
   * - ``bytes32``
     - ``'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'``

.. note::
    In ``bytes`` the array starts with the bytes all set to ``'\x00'``

.. note::
    In reference types all the type's members are set to their initial values.


.. _type_conversions:

Type Conversions
****************

All type conversions in Vyper must be made explicitly using the built-in ``convert(a, b)`` function. Currently, the following type conversions are supported:

.. list-table:: Basic Type Conversions
   :header-rows: 1

   * - Destination Type (b)
     - Input Type (a.type)
     - Allowed Inputs Values (a)
     - Additional Notes
   * - ``bool``
     - ``bool``
     - ``—``
     - Do not allow converting to/from the same type
   * - ``bool``
     - ``decimal``
     - ``MINNUM...MAXNUM``
     - Has the effective conversion logic of: ``return (a != 0.0)``
   * - ``bool``
     - ``int128``
     - ``MINNUM...MAXNUM``
     - Has the effective conversion logic of: ``return (a != 0)``
   * - ``bool``
     - ``uint256``
     - ``0...MAX_UINT256``
     - Has the effective conversion logic of: ``return (a != 0)``
   * - ``bool``
     - ``bytes32``
     - ``(0x00 * 32)...(0xFF * 32)``
     - Has the effective conversion logic of: ``return (a != 0x00)``
   * - ``bool``
     - ``bytes``
     - ``(0x00 * 1)...(0xFF * 32)``
     - Has the effective conversion logic of: ``return (a != 0x00)``
   * -
     -
     -
     -
   * - ``decimal``
     - ``bool``
     - ``True / False``
     - Result will be ``0.0`` or ``1.0``
   * - ``decimal``
     - ``decimal``
     - —
     - Do not allow converting to/from the same type
   * - ``decimal``
     - ``int128``
     - ``MINNUM...MAXNUM``
     -
   * - ``decimal``
     - ``uint256``
     - ``0...MAXDECIMAL``
     -
   * - ``decimal``
     - ``bytes32``
     - ``(0x00 * 32)...(0xFF * 32)``
     -
   * - ``decimal``
     - ``bytes``
     - ``(0x00 * 1)...(0xFF * 32)``
     -
   * -
     -
     -
     -
   * - ``int128``
     - ``bool``
     - ``True / False``
     - Result will be ``0`` or ``1``
   * - ``int128``
     - ``decimal``
     - ``MINNUM...MAXNUM``
     - Only allow input within ``int128`` supported range, truncates the decimal value
   * - ``int128``
     - ``int128``
     - —
     - Do not allow converting to/from the same type
   * - ``int128``
     - ``uint256``
     - ``0...MAXNUM``
     -
   * - ``int128``
     - ``bytes32``
     - ``(0x00 * 32)...(0xFF * 32)``
     -
   * - ``int128``
     - ``bytes``
     - ``(0x00 * 1)...(0xFF * 32)``
     -
   * -
     -
     -
     -
   * - ``uint256``
     - ``bool``
     - ``True / False``
     - Result will be ``0`` or ``1``
   * - ``uint256``
     - ``decimal``
     - ``0...MAXDECIMAL``
     - Truncates the ``decimal`` value
   * - ``uint256``
     - ``int128``
     - ``0...MAXNUM``
     -
   * - ``uint256``
     - ``uint256``
     - —
     - Do not allow converting to/from the same type
   * - ``uint256``
     - ``bytes32``
     - ``(0x00 * 32)...(0xFF * 32)``
     -
   * - ``uint256``
     - ``bytes``
     - ``(0x00 * 1)...(0xFF * 32)``
     -
   * -
     -
     -
     -
   * - ``bytes32``
     - ``bool``
     - ``True / False``
     - Result will be either ``(0x00 * 32)`` or ``(0x00 * 31 + 0x01)``
   * - ``bytes32``
     - ``decimal``
     - ``MINDECIMAL...MAXDECIMAL``
     - Has the effective behavior of multiplying the ``decimal`` value by the decimal divisor ``10000000000`` and then converting that signed *integer* value to a ``bytes32`` byte array
   * - ``bytes32``
     - ``int128``
     - ``MINNUM...MAXNUM``
     -
   * - ``bytes32``
     - ``uint256``
     - ``0...MAX_UINT256``
     -
   * - ``bytes32``
     - ``bytes32``
     - —
     - Do not allow converting to/from the same type
   * - ``bytes32``
     - ``bytes``
     - ``(0x00 * 1)...(0xFF * 32)``
     - Left-pad input ``bytes`` to size of ``32``


.. index:: !conversion
