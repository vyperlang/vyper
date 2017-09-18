.. index:: type

.. _types:

*****
Types
*****

Viper is a statically typed language, which means that the type of each
variable (state and local) needs to be specified or at least known at
compile-time. Viper provides several elementary types which can be combined
to form complex types.

In addition, types can interact with each other in expressions containing
operators.

Value Types
===========

The following types are also called value types because variables of these
types will always be passed by value, i.e. they are always copied when they
are used as function arguments or in assignments.

.. index:: ! bool, ! true, ! false

Booleans
--------

``bool``: The possible values are constants ``true`` and ``false``.

Operators:

*  ``not`` (logical negation)
*  ``and`` (logical conjunction, "&&")
*  ``or`` (logical disjunction, "||")
*  ``==`` (equality)
*  ``not ... == ... ``, ``!=`` (inequality)

The operators ``or`` and ``and`` apply the common short-circuiting rules. This means that in the expression ``f(x) or g(y)``, if ``f(x)`` evaluates to ``true``, ``g(y)`` will not be evaluated even if it may have side-effects.

.. index:: ! uint, ! int, ! integer


Integers
--------

``num``:  equivalent to``int128``, a signed integer strictly between -2\*\*127 and 2\*\*127-1.

Operators:

* Comparisons: ``<=``, ``<``, ``==``, ``!=``, ``>=``, ``>`` (evaluate to ``bool``)
* Arithmetic operators: ``+``, ``-``, unary ``-``, unary ``+``, ``*``, ``/``, ``%`` (remainder)


Decimals
--------
``decimal``:  a decimal fixed point value with the integer component represented as a ``num`` and the fractional component supporting up to ten decimal places.


Time
-----
``timestamp``:  a timestamp value with a base unit of one second, represented as a ``num``.

``timedelta``:  a number of seconds (note: two timedeltas can be added together, as can a timedelta and a timestamp, but not two timestamps), represented as a ``num``.


Value
------
``wei_value``:  an amount of `ether <http://ethdocs.org/en/latest/ether.html#denominations>`_ with a base unit of one wei, represented as a ``num``.

``currency_value``:  represents an amount of currency and should be used to represent assets where ether is traded for value, represented as a ``num``.



.. _address:

Address
-------

``address``: Holds an Ethereum address (20 byte value).


.. _members-of-addresses:

Members of Addresses
^^^^^^^^^^^^^^^^^^^^

* ``balance`` and ``send``

It is possible to query the balance of an address using the property ``balance``
and to send Ether (in units of wei) to an address using the ``send`` function:

::

    x: address

    def foo(x: adress):
        if (x.balance < 10 and self.balance >= 10):
            x.send(10)


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
