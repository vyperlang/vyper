.. index:: type

.. _types:

Types
#####

Vyper is a statically typed language, which means that the type of each
variable (state and local) needs to be specified or at least known at
compile-time. Vyper provides several elementary types which can be combined
to form complex types.

In addition, types can interact with each other in expressions containing
operators.

.. index:: ! value

Value Types
***********

The following types are also called value types because variables of these
types will always be passed by value, i.e. they are always copied when they
are used as function arguments or in assignments.

.. index:: ! bool, ! true, ! false

Boolean
=======

**Keyword:** ``bool``

A boolean is a type to store a logical/truth value.

Values
------

The only possible values are the constants ``True`` and ``False``.

Operators
---------

====================  ===================
Operator              Description
====================  ===================
``x not y``           Logical negation
``x and y``           Logical conjunction
``x or y``            Logical disjunction
``x == y``            Equality
``x != y``            Inequality
====================  ===================

The operators ``or`` and ``and`` do not apply short-circuiting rules, i.e. both
``x`` and ``y`` will always be evaluated.

.. index:: ! int128, ! int, ! integer

Signed Integer (128 bit)
========================

**Keyword:** ``int128``

A signed integer (128 bit) is a type to store positive and negative integers.

Values
------

Signed integer values between -2\ :sup:`127` and (2\ :sup:`127` - 1), inclusive.

Operators
---------

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

``x`` and ``y`` must be of the type ``int128``.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

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

``x`` and ``y`` must be of the type ``int128``.

.. index:: ! unit, ! uint256

Unsigned Integer (256 bit)
==========================

**Keyword:** ``uint256``

An unsigned integer (256 bit) is a type to store non-negative integers.

Values
------

Integer values between 0 and (2\ :sup:`256`-1).

.. note::
    Integer literals are interpreted as ``int128`` by default. In cases where ``uint256`` is more appropriate, such as assignment, the literal might be interpreted as ``uint256``. Example: ``_variable: uint256 = _literal``. In order to explicitly cast a literal to a ``uint256`` use ``convert(_literal, uint256)``.

Operators
---------

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

``x`` and ``y`` must be of the type ``uint256``.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

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

``x``, ``y`` and ``z`` must be of the type ``uint256``.

Bitwise Operators
^^^^^^^^^^^^^^^^^

===================== =============
Operator              Description
===================== =============
``bitwise_and(x, y)`` AND
``bitwise_not(x, y)`` NOT
``bitwise_or(x, y)``  OR
``bitwise_xor(x, y)`` XOR
``shift(x, _shift)``  Bitwise Shift
===================== =============

``x`` and ``y`` must be of the type ``uint256``. ``_shift`` must be of the type ``int128``.

.. note::
    Positive ``_shift`` equals a left shift; negative ``_shift`` equals a right shift.
    Values shifted above/below the most/least significant bit get discarded.

Decimals
========

**Keyword:** ``decimal``

A decimal is a type to store a decimal fixed point value.

Values
------

A value with a precision of 10 decimal places between -2\ :sup:`127` and (2\ :sup:`127` - 1).

Operators
---------

Comparisons
^^^^^^^^^^^

Comparisons return a boolean value.

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

``x`` and ``y`` must be of the type ``decimal``.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

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
``floor(x)``   Largest integer <= ``x``. Returns ``int128``.
``ceil(x)``    Smallest integer >= ``x``. Returns ``int128``.
=============  ==========================================

``x`` and ``y`` must be of the type ``decimal``.

.. _address:

Address
=======

**Keyword:** ``address``

The address type holds an Ethereum address.

Values
------

An address type can hold an Ethereum address which equates to 20 bytes or 160 bits. It returns in hexadecimal notation with a leading ``0x``.

.. _members-of-addresses:

Members
^^^^^^^

===============  =========================================================
Member           Description
===============  =========================================================
``balance``      Query the balance of an address. Returns ``wei_value``.
``codesize``     Query the code size of an address. Returns ``int128``.
``is_contract``  Query whether it is a contract address. Returns ``bool``.
===============  =========================================================

Syntax as follows: ``_address.<member>``, where ``_address`` is of the type ``address`` and ``<member>`` is one of the above keywords.

Unit Types
==========

Vyper allows the definition of types with discrete units e.g. meters, seconds, wei, ... . These types may only be based on either ``uint256``, ``int128`` or ``decimal``.
Vyper has 3 unit types built in, which are the following:

Time
----

=============  =====  ===========  ==========================
Keyword        Unit   Base type    Description
=============  =====  ===========  ==========================
``timestamp``  1 sec  ``uint256``  This represents a point in time.
``timedelta``  1 sec  ``uint256``  This is a number of seconds.
=============  =====  ===========  ==========================

.. note::
    Two ``timedelta`` can be added together, as can a ``timedelta`` and a ``timestamp``, but not two ``timestamps``.

Wei
---

===================  ===========  ===========  ====================================================================================
Keyword              Unit         Base type    Description
===================  ===========  ===========  ====================================================================================
``wei_value``        1 wei        ``uint256``    This is an amount of `Ether <http://ethdocs.org/en/latest/ether.html#denominations>`_ in wei.
===================  ===========  ===========  ====================================================================================

Custom Unit Types
=================

Vyper allows you to add additional not-provided unit label to either ``uint256``, ``int128`` or ``decimal``.

**Custom units example:**
::

  # specify units used in the contract.
  units: {
      cm: "centimeter",
      km: "kilometer"
  }

Having defined the units they can be defined on variables as follows.

**Custom units usage:**
::

    a: int128(cm)
    b: uint256(km)

.. index:: !bytes32

32-bit-wide Byte Array
======================

**Keyword:** ``bytes32``
This is a 32-bit-wide byte array that is otherwise similar to byte arrays.

**Example:**
::

    # Declaration
    hash: bytes32
    # Assignment
    self.hash = _hash

Operators
---------

====================================  ============================================================
Keyword                               Description
====================================  ============================================================
``keccak256(x)``                      Return the keccak256 hash as bytes32.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================

Where ``x`` is a byte array and ``_start`` as well as ``_len`` are integer values.

.. index:: !bytes

Fixed-size Byte Arrays
======================

**Keyword:** ``bytes``

A byte array with a fixed size.
The syntax being ``bytes[maxLen]``, where ``maxLen`` is an integer which denotes the maximum number of bytes.
On the ABI level the Fixed-size bytes array is annotated as ``bytes``.

**Example:**
::

    example_bytes: bytes[100] = b"\x01\x02\x03"

.. index:: !string

Fixed-size Strings
==================

**Keyword:** ``string``
Fixed-size strings can hold strings with equal or fewer characters than the maximum length of the string.
On the ABI level the Fixed-size bytes array is annotated as ``string``.

**Example:**
::

    example_str: string[100] = "Test String"

Operators
---------

====================================  ============================================================
Keyword                               Description
====================================  ============================================================
``len(x)``                            Return the length as an integer.
``keccak256(x)``                      Return the keccak256 hash as bytes32.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================

Where ``x`` is a byte array or string while ``_start`` and ``_len`` are integers.
The ``len``, ``keccak256``, ``concat``, ``slice`` operators can be used with ``string`` and ``bytes`` types.

.. index:: !reference

Reference Types
***************

Reference types do not fit into 32 bytes. Because of this, copying their value is not as feasible as
with value types. Therefore only the location, i.e. the reference, of the data is passed.

.. index:: !arrays

Fixed-size Lists
================

Fixed-size lists hold a finite number of elements which belong to a specified type.

Syntax
------

Lists can be declared with ``_name: _ValueType[_Integer]``. Multidimensional lists are also possible.

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

Initial Values
**************

In Vyper, there is no ``null`` option like most programming languages have. Thus, every variable type has a default value. In order to check if a variable is empty, you will need to compare it to its type's default value.
If you would like to reset a variable to its type's default value, use the built-in ``clear()`` function.

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
