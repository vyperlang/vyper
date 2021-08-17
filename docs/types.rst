.. index:: type

.. _types:

Types
#####

Vyper is a statically typed language. The type of each variable (state and local) must be specified or at least known at compile-time. Vyper provides several elementary types which can be combined to form complex types.

In addition, types can interact with each other in expressions containing operators.

.. index:: ! value

Value Types
===========

The following types are also called value types because variables of these
types will always be passed by value, i.e. they are always copied when they
are used as function arguments or in assignments.

.. index:: ! bool, ! true, ! false

Boolean
-------

**Keyword:** ``bool``

A boolean is a type to store a logical/truth value.

Values
******

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

Short-circuiting of boolean operators (``or`` and ``and``) is consistent with
the behavior of Python.

.. index:: ! int256, ! int, ! integer

Signed Integer (256 bit)
------------------------

**Keyword:** ``int256``

A signed integer (256 bit) is a type to store positive and negative integers.

Values
******

Signed integer values between -2\ :sup:`255` and (2\ :sup:`255` - 1), inclusive.

Interger literals cannot have a decimal point even if the decimal value is zero. For example, ``2.0`` cannot be interpreted as an integer.

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

``x`` and ``y`` must be of the type ``int256``.

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
=============  ======================

``x`` and ``y`` must be of the type ``int256``.

.. index:: ! int128

Signed Integer (128 bit)
------------------------

**Keyword:** ``int128``

A signed integer (128 bit) is a type to store positive and negative integers.

Values
******

Signed integer values between -2\ :sup:`127` and (2\ :sup:`127` - 1), inclusive.

Interger literals cannot have a decimal point even if the decimal value is zero. For example, ``2.0`` cannot be interpreted as an integer.

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
=============  ======================

``x`` and ``y`` must be of the type ``int128``.

.. index:: ! unit, ! uint256

Unsigned Integer (256 bit)
--------------------------

**Keyword:** ``uint256``

An unsigned integer (256 bit) is a type to store non-negative integers.

Values
******

Integer values between 0 and (2\ :sup:`256`-1).

Interger literals cannot have a decimal point even if the decimal value is zero. For example, ``2.0`` cannot be interpreted as an integer.

.. note::
    Integer literals are interpreted as ``int128`` by default. In cases where ``uint256`` is more appropriate, such as assignment, the literal might be interpreted as ``uint256``. Example: ``_variable: uint256 = _literal``. In order to explicitly cast a literal to a ``uint256`` use ``convert(_literal, uint256)``.

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

``x`` and ``y`` must be of the type ``uint256``.

Arithmetic Operators
^^^^^^^^^^^^^^^^^^^^

===========================  ======================
Operator                     Description
===========================  ======================
``x + y``                    Addition
``x - y``                    Subtraction
``x * y``                    Multiplication
``x / y``                    Division
``x**y``                     Exponentiation
``x % y``                    Modulo
===========================  ======================

``x``, ``y`` and ``z`` must be of the type ``uint256``.

Decimals
--------

**Keyword:** ``decimal``

A decimal is a type to store a decimal fixed point value.

Values
******

A value with a precision of 10 decimal places between -2\ :sup:`127` and (2\ :sup:`127` - 1).

In order for a literal to be interpreted as ``decimal`` it must include a decimal point.

Operators
*********

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
=============  ==========================================

``x`` and ``y`` must be of the type ``decimal``.

.. _address:

Address
-------

**Keyword:** ``address``

The address type holds an Ethereum address.

Values
******

An address type can hold an Ethereum address which equates to 20 bytes or 160 bits. Address literals must be written in hexadecimal notation with a leading ``0x`` and must be `checksummed <https://github.com/ethereum/EIPs/blob/master/EIPS/eip-155.md>`_.

.. _members-of-addresses:

Members
^^^^^^^

=============== =========== ==========================================================================
Member          Type        Description
=============== =========== ==========================================================================
``balance``     ``uint256`` Balance of an address
``codehash``    ``bytes32`` Keccak of code at an address, ``EMPTY_BYTES32`` if no contract is deployed
``codesize``    ``uint256`` Size of code deployed an address, in bytes
``is_contract`` ``bool``    Boolean indicating if a contract is deployed at an address
=============== =========== ==========================================================================

Syntax as follows: ``_address.<member>``, where ``_address`` is of the type ``address`` and ``<member>`` is one of the above keywords.

.. note::

    Operations such as ``SELFDESTRUCT`` and ``CREATE2`` allow for the removal and replacement of bytecode at an address. You should never assume that values of address members will not change in the future.

32-bit-wide Byte Array
----------------------

**Keyword:** ``bytes32``
This is a 32-bit-wide byte array that is otherwise similar to byte arrays.

**Example:**
::

    # Declaration
    hash: bytes32
    # Assignment
    self.hash = _hash

Operators
*********

====================================  ============================================================
Keyword                               Description
====================================  ============================================================
``keccak256(x)``                      Return the keccak256 hash as bytes32.
``concat(x, ...)``                    Concatenate multiple inputs.
``slice(x, start=_start, len=_len)``  Return a slice of ``_len`` starting at ``_start``.
====================================  ============================================================

Where ``x`` is a byte array and ``_start`` as well as ``_len`` are integer values.

.. index:: !bytes

Byte Arrays
-----------

**Keyword:** ``Bytes``

A byte array with a fixed size.

The syntax being ``Bytes[maxLen]``, where ``maxLen`` is an integer which denotes the maximum number of bytes.
On the ABI level the Fixed-size bytes array is annotated as ``bytes``.

Bytes literals may be given as bytes strings, hexadecimal, or binary.

.. code-block:: python

    bytes_string: Bytes[100] = b"\x01"
    hex_bytes: Bytes[100] = 0x01
    binary_bytes: Bytes[100] = 0b00000001

.. index:: !string

Strings
-------

**Keyword:** ``String``

Fixed-size strings can hold strings with equal or fewer characters than the maximum length of the string.
On the ABI level the Fixed-size bytes array is annotated as ``string``.

.. code-block:: python

    example_str: String[100] = "Test String"

.. index:: !reference

Reference Types
===============

Reference types do not fit into 32 bytes. Because of this, copying their value is not as feasible as
with value types. Therefore only the location, i.e. the reference, of the data is passed.

.. index:: !arrays

Fixed-size Lists
----------------

Fixed-size lists hold a finite number of elements which belong to a specified type.

Lists can be declared with ``_name: _ValueType[_Integer]``.

.. code-block:: python

    # Defining a list
    exampleList: int128[3]

    # Setting values
    exampleList = [10, 11, 12]
    exampleList[2] = 42

    # Returning a value
    return exampleList[0]

Multidimensional lists are also possible. The notation for the declaration is reversed compared to some other languages, but the access notation is not reversed.

A two dimensional list can be declared with ``_name: _ValueType[inner_size][outer_size]``. Elements can be accessed with ``_name[outer_index][inner_index]``.

.. code-block:: python

    # Defining a list with 2 rows and 5 columns and set all values to 0
    exampleList2D: int128[5][2] = empty(int128[5][2])

    # Setting a value for row the first row (0) and last column (4)
    exampleList2D[0][4] = 42

    # Setting values
    exampleList2D = [[10, 11, 12, 13, 14], [16, 17, 18, 19, 20]]

    # Returning the value in row 0 column 4 (in this case 14)
    return exampleList2D[0][4]

.. _types-struct:

Structs
-------

Structs are custom defined types that can group several variables.

Struct types can be used inside mappings and arrays. Structs can contain arrays and other structs, but not mappings.

Struct members can be accessed via ``struct.argname``.

.. code-block:: python

    # Defining a struct
    struct MyStruct:
        value1: int128
        value2: decimal

    # Declaring a struct variable
    exampleStruct: MyStruct = MyStruct({value1: 1, value2: 2.0})

    # Accessing a value
    exampleStruct.value1 = 1

.. index:: !mapping

Mappings
--------

Mappings are `hash tables <https://en.wikipedia.org/wiki/Hash_table>`_ that are virtually initialized such that every possible key exists and is mapped to a value whose byte-representation is all zeros: a type's :ref:`default value <types-initial>`.

The key data is not stored in a mapping, instead its ``keccak256`` hash used to look up a value. For this reason mappings do not have a length or a concept of a key or value being "set".

Mapping types are declared as ``HashMap[_KeyType, _ValueType]``.

* ``_KeyType`` can be any base or bytes type. Mappings, interfaces or structs are not support as key types.
* ``_ValueType`` can actually be any type, including mappings.

.. note::
    Mappings are only allowed as state variables.

.. code-block:: python

   # Defining a mapping
   exampleMapping: HashMap[int128, decimal]

   # Accessing a value
   exampleMapping[0] = 10.1

.. note::

    Mappings have no concept of length and so cannot be iterated over.

.. index:: !initial

.. _types-initial:

Initial Values
==============

Unlike most programming languages, Vyper does not have a concept of ``null``. Instead, every variable type has a default value. To check if a variable is empty, you must compare it to the default value for it's given type.

To reset a variable to it's default value, assign to it the built-in ``empty()`` function which constructs a zero value for that type.

.. note::

    Memory variables must be assigned a value at the time they are declared.

Here you can find a list of all types and default values:

=========== ======================================================================
Type        Default Value
=========== ======================================================================
``address`` ``0x0000000000000000000000000000000000000000``
``bool``    ``False``
``bytes32`` ``0x0000000000000000000000000000000000000000000000000000000000000000``
``decimal`` ``0.0``
``int128``  ``0``
``uint256`` ``0``
=========== ======================================================================

.. note::
    In ``Bytes`` the array starts with the bytes all set to ``'\x00'``

.. note::
    In reference types all the type's members are set to their initial values.


.. _type_conversions:

Type Conversions
================

All type conversions in Vyper must be made explicitly using the built-in ``convert(a: atype, btype)`` function. Currently, the following type conversions are supported:

================ ================== ============================== =================================
In (``atype``)   Out (``btype``)    Allowable Values               Additional Notes
================ ================== ============================== =================================
``bool``         ``decimal``        All                            ``0.0`` or ``1.0``
``bool``         ``int128``         All                            ``0`` or ``1``
``bool``         ``uint256``        All                            ``0`` or ``1``
``bool``         ``bytes32``        All                            ``0x00`` or ``0x01``
``bool``         ``Bytes``          All
``decimal``      ``bool``           All                            Returns ``a != 0.0``
``decimal``      ``int128``         All                            Value is truncated
``decimal``      ``uint256``        ``a >= 0.0``                   Value is truncated
``decimal``      ``bytes32``        All
``decimal``      ``Bytes``          All
``int128``       ``bool``           All                            Returns ``a != 0``
``int128``       ``decimal``        All
``int128``       ``uint256``        ``a >= 0``                     Cannot convert negative values
``int128``       ``bytes32``        All
``int128``       ``Bytes``          All
``uint256``      ``bool``           All                            Returns ``a != 0``
``uint256``      ``decimal``        ``a <= MAX_DECIMAL``
``uint256``      ``int128``         ``a <= MAX_INT128``
``uint256``      ``bytes32``        All
``uint256``      ``Bytes``          All
``bytes32``      ``bool``           All                            ``True`` if ``a`` is not empty
``bytes32``      ``decimal``        All
``bytes32``      ``int128``         All
``bytes32``      ``uint256``        All
``bytes32``      ``Bytes``          All
================ ================== ============================== =================================
