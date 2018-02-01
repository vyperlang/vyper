.. index:: type

.. _types:

#####
Types
#####

Vyper is a statically typed language, which means that the type of each
variable (state and local) needs to be specified or at least known at
compile-time. Vyper provides several elementary types which can be combined
to form complex types.

In addition, types can interact with each other in expressions containing
operators.


.. index:: ! value

***********
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
The only possible values are the constants ``true`` and ``false``.

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

The operators ``or`` and ``and`` apply the common short-circuiting rules.

.. index:: ! num, ! int, ! integer
Signed Integer (128 bit)
========================
**Keyword:** ``num``

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
``x`` and ``y`` must be of the type ``num``.

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
``x`` and ``y`` must be of the type ``num``.

.. index:: ! unit, ! num256
Unsigned Integer (256 bit)
==========================
**Keyword:** ``num256``

An unsigned integer (256 bit) is a type to store non-negative integers.

Values
------
Integer values between 0 and (2\ :sup:`256`-1).

.. note::
    Integer literals are always interpreted as ``num``. In order to assign a literal to a ``num256`` use ``as_num256(_literal)``.

Operators
---------
Comparisons
^^^^^^^^^^^
Comparisons return a boolean value.

===================  ================
Operator             Description
===================  ================
``num256_lt(x, y)``  Less than
``num256_le(x, y)``  Less than or equal to
``x == y``           Equals
``x != y``           Does not equal
``num256_ge(x, y)``  Greater than or equal to
``num256_gt(x, y)``  Greater than
===================  ================
``x`` and ``y`` must be of the type ``num256``.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

=======================  ======================
Operator                 Description
=======================  ======================
``num256_add(x, y)``     Addition
``num256_sub(x, y)``     Subtraction
``num256_addmod(x, y)``  Modular addition
``num256_mul(x, y)``     Multiplication
``num256_mulmod(x, y)``  Modular multiplication
``num256_div(x, y)``     Divison
``num256_exp(x, y)``     Exponentiation
``num256_mod(x, y)``     Modulo
``min(x, y)``            Minimum
``max(x, y)``            Maximum
=======================  ======================
``x`` and ``y`` must be of the type ``num256``.

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
``x`` and ``y`` must be of the type ``num256``. ``_shift`` must be of the type ``num``.

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
``x / y``      Divison
``x % y``      Modulo
``min(x, y)``  Minimum
``max(x, y)``  Maximum
``floor(x)``   Largest integer <= ``x``. Returns ``num``.
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

============  ===================================================
Member        Description
============  ===================================================
``balance``   Query the balance of an address. Returns ``wei_value``.
``codesize``  Query the code size of an address. Returns ``num``.
============  ===================================================
Syntax as follows: ``_address.<member>``, where ``_address`` is of the type ``address`` and ``<member>`` is one of the above keywords.

Unit Types
==========
Vyper allows the definition of types with discrete units e.g. meters, seconds, wei, ... . These types may only be based on either ``num`` or ``decimal``.
Vyper has multiple unit types built in, which are the following:

=============  =====  =========  ==========================
Time
-----------------------------------------------------------
Keyword        Unit   Base type  Description
=============  =====  =========  ==========================
``timestamp``  1 sec  ``num``    This represents a point in time.
``timedelta``  1 sec  ``num``    This is a number of seconds.
=============  =====  =========  ==========================

.. note::
    Two ``timedelta`` can be added together, as can a ``timedelta`` and a ``timestamp``, but not two ``timestamps``.

===================  ===========  =========  ====================================================================================
Currency
---------------------------------------------------------------------------------------------------------------------------------
Keyword              Unit         Base type  Description
===================  ===========  =========  ====================================================================================
``wei_value``        1 wei        ``num``    This is an amount of `Ether <http://ethdocs.org/en/latest/ether.html#denominations>`_ in wei.
``currency1_value``  1 currency1  ``num``    This is an amount of currency1.
``currency2_value``  1 currency2  ``num``    This is an amount of currency2.
===================  ===========  =========  ====================================================================================

.. index:: !bytes32
32-bit-wide Byte Array
======================
**Keyword:** ``bytes32``
This is a 32-bit-wide byte array that is otherwise similiar to byte arrays.

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
``len(x)``                            Return the length as an integer.
``sha3(x)``                           Return the sha3 hash as bytes32.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================
Where ``x`` is a byte array and ``_start`` as well as ``_len`` are integer values.

.. index:: !bytes
Fixed-size Byte Arrays
======================
**Keyword:** ``bytes``

A byte array with a fixed size.
The syntax being ``bytes <= maxLen``, where ``maxLen`` is an integer which denotes the maximum number of bits.

.. index:: !string
Strings
-------
Fixed-size byte arrays can hold strings with equal or fewer characters than the maximum length of the byte array.

**Example:**
::
    exampleString = "Test String"

Operators
---------
====================================  ============================================================
Keyword                               Description
====================================  ============================================================
``len(x)``                            Return the length as an integer.
``sha3(x)``                           Return the sha3 hash as bytes32.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================
Where ``x`` is a byte array while ``_start`` and ``_len`` are integers.

.. index:: !reference

***************
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
    exampleList: num[3]
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
    exampleStruct: {
        value1: num,
        value2: decimal,
    }
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

Mapping types are declared as ``_ValueType[_KeyType]``.
Here ``_KeyType`` can be almost any type except for mappings, a contract, or a struct.
``_ValueType`` can actually be any type, including mappings.

**Example:**
::
   #Defining a mapping
   exampleMapping: decimal[num]
   #Accessing a value
   exampleMapping[0] = 10.1

.. note::
    Mappings can only be accessed, not iterated over.

.. index:: !conversion

**********
Conversion
**********
The following conversions are possible.

===========================  =====================================================================================================================  =============
Keyword                      Input                                                                                                                  Output
===========================  =====================================================================================================================  =============
``as_num128(x)``             ``num256``, ``address``, ``bytes32``                                                                                   ``num``
``as_num256(x)``             ``num`` , ``address``, ``bytes32``                                                                                     ``num256``
``as_bytes32(x)``            ``num``, ``num256``, ``address``                                                                                       ``bytes32``
``bytes_to_num(x)``          ``bytes``                                                                                                              ``num``
``as_wei_value(x, denom)``   ``num`` , ``decimal``; `denomination <http://ethdocs.org/en/latest/ether.html#denominations>`_ literal                 ``wei_value``
===========================  =====================================================================================================================  =============
