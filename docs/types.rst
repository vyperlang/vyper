.. index:: type

.. _types:

#####
Types
#####

Viper is a statically typed language, which means that the type of each
variable (state and local) needs to be specified or at least known at
compile-time. Viper provides several elementary types which can be combined
to form complex types.

In addition, types can interact with each other in expressions containing
operators.

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

A Boolean is a type to store a logical/truth value.

Values
------
The only possible values are the constants ``true`` and ``false``.

Operators
---------

====================  ===================  
Operator              Description
====================  ===================  
``f(x) not g(y)``     Logical negation     
``f(x) and g(y)``     Logical conjunction  
``f(x) or g(y)``      Logical disjunction  
``f(x) == g(y)``      Equality             
``f(x) != g(y)``      Inequality
====================  ===================  

The operators ``or`` and ``and`` apply the common short-circuiting rules:
::
    #Short-circuiting
    return false and foo()
    #Returns false without calling foo() since it is not necessary for the result
    return true or bar()
    #Returns true without calling bar() since it is not necessary for the result 

.. index:: ! num, ! int, ! integer
Signed Integer (128 bit)
========================
**Keyword:** ``num``

A signed integer (128 bit) is a type to store positive and negative integers.

Values
------
Signed integer values between -2\ :sup:`127` and (2\ :sup:`127` - 1).

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
``x`` and ``y`` must be of the type ``num``.

Arithmetic operators
^^^^^^^^^^^^^^^^^^^^

=============  ======================
Operator       Description
=============  ======================
``x + y``      Addition
``x - y``      Subtraction
``-x``         Unary minus/Negation
``x * y``      Multiplication 
``x / y``      Divison
``x**y``       Exponentiation
``x % y``      Modulo
``min(x, y)``  Minimum
``max(x, y)``  Maximum
=============  ======================
``x`` and ``y`` must be of the type ``num``.

Conversion
----------
A ``num`` can be converted to a ``num256`` with the function ``as_num256(x)``, where ``x`` is of the type ``num``.
Conversly, a ``num256`` can be converted to a ``num`` with the function ``as_num128(x)``, where ``x`` is of the type ``num256``.

.. index:: ! unit, ! num256
Unsigned Integer (256 bit)
==========================
**Keyword:** ``num256``

An unsigned integer (256 bit) is a type to store non-negative integers. 

Values
------
Integer values between 0 and (2\ :sup:`257`-1).

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
``num256_le(x, y)``  Less or equal
``x == y``           Equals
``x != y``           Does not equal
``num256_ge(x, y)``  Greater or equal
``num256_gt(x, y)``  Greater than
===================  ================
``x`` and ``y`` must be of the type ``num256``.

Arithmetic operators
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

Bitwise operators 
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

Conversion
----------
A ``num256`` can be converted to a ``num`` with the function ``as_num128(x)``, where ``x`` is of the type ``num256``.
Conversly, a ``num`` can be converted to a ``num256`` with the function ``as_num256(x)``, where ``x`` is of the type ``num``.
     
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

Arithmetic operators
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
An Address type can hold an Ethereum address which equates to 20 bytes/160 bits. Returns in hexadecimal notation with a leading ``0x``.

.. _members-of-addresses:
Members
^^^^^^^

============  ===================================================
Member        Description
============  ===================================================
``balance``   Query balance of an address. Returns ``wei_value``.
``codesize``  Query the code size of an address. Returns ``num``.
============  ===================================================
Syntax as follows: ``_address.<member>``, where ``_address`` is of the type ``address`` and ``<member>`` is one of the above keywords.

Unit Types
==========
Viper allows the definition of types with a discrete unit such as e.g. meters, seconds, wei, ... . These types may only be based on either ``num`` or ``decimal``.
Viper has multiple unit types built in, which are the following:

=============  =====  =========  ==========================
Time
-----------------------------------------------------------
Keyword        Unit   Base type  Description
=============  =====  =========  ==========================
``timestamp``  1 sec  ``num``    Represents a point in time
``timedelta``  1 sec  ``num``    A number of seconds 
=============  =====  =========  ==========================

.. note::
    Two ``timedelta`` can be added together, as can a ``timedelta`` and a ``timestamp``, but not two ``timestamps``.

===================  ===========  =========  ====================================================================================
Currency
---------------------------------------------------------------------------------------------------------------------------------
Keyword              Unit         Base type  Description
===================  ===========  =========  ====================================================================================
``wei_value``        1 wei        ``num``    An amount of `Ether <http://ethdocs.org/en/latest/ether.html#denominations>`_ in wei
``currency_value``   1 currency   ``num``    An amount of currency
``currency1_value``  1 currency1  ``num``    An amount of currency1
``currency2_value``  1 currency2  ``num``    An amount of currency2
===================  ===========  =========  ====================================================================================

Conversion
----------
The unit of a unit type may be stripped with the function ``as_unitless_number(_unitType)``, where ``_unitType`` is a unit type. The returned value is then either a ``num``
or a ``decimal``, depending on the base type.

#################
TODO from here on
#################
Todo: bytes32 and reference types; revist conversion between num/num256/bytes32

.. index:: byte array, bytes32


Fixed-size byte arrays
----------------------

``bytes32``: 32 bytes

::

    # Declaration
    hash: bytes32

    # Assignment
    self.hash = _hash

``bytes <= maxlen``: a byte array with the given maximum length

::

    # Declaration
    name: bytes <= 5

    # Assignment
    self.name = _name

``type[length]``: finite list

::

    # Declaration
    numbers: num[3]

    # Assignment
    self.numbers[0] = _num1


.. index:: !structs

Structs
-------

Structs are custom defined types that can group several variables.  They can be accessed via ``struct.argname``.

::

    # Information about voters
    voters: public({
        # weight is accumulated by delegation
        weight: num,
        # if true, that person already voted
        voted: bool,
        # person delegated to
        delegate: address,
        # index of the voted proposal
        vote: num
    })


.. index:: !mapping

Mappings
========

Mapping types are declared as ``_ValueType[_KeyType]``.
Here ``_KeyType`` can be almost any type except for mappings, a contract, or a struct.
``_ValueType`` can actually be any type, including mappings.

Mappings can be seen as `hash tables <https://en.wikipedia.org/wiki/Hash_table>`_ which are virtually initialized such that
every possible key exists and is mapped to a value whose byte-representation is
all zeros: a type's :ref:`default value <default-value>`. The similarity ends here, though: The key data is not actually stored
in a mapping, only its ``keccak256`` hash used to look up the value.

Because of this, mappings do not have a length or a concept of a key or value being "set".

Mappings are only allowed as state variables.

It is possible to mark mappings ``public`` and have Viper create a :ref:`getter <visibility-and-getters>`.
The ``_KeyType`` will become a required parameter for the getter and it will
return ``_ValueType``.

.. note::
    Mappings can only be accessed, not iterated over.
