.. _compiler-exceptions:

Compiler Exceptions
###################

.. _exceptions-common:

Vyper raises one or more of the following exceptions when an issue is encountered while compiling a contract.

Whenever possible, exceptions include a source highlight displaying the location
of the error within the code:

.. code-block:: python

    vyper.exceptions.VariableDeclarationException: line 79:17 Persistent variable undeclared: highstBid
         78     # If bid is less than highest bid, bid fails
    ---> 79     if (value <= self.highstBid):
    -------------------------^
         80         return False

.. py:exception:: ArgumentException

    Raises when calling a function with invalid arguments, for example an incorrect number of positional arguments or an invalid keyword argument.

.. py:exception:: CallViolation

    Raises on an illegal function call, such as attempting to call between two external functions.

.. py:exception:: ArrayIndexException

    Raises when an array index is out of bounds.

.. py:exception:: EventDeclarationException

    Raises when an event declaration is invalid.

.. py:exception:: EvmVersionException

    Raises when a contract contains an action that cannot be performed with the active EVM ruleset.

.. py:exception:: FunctionDeclarationException

    Raises when a function declaration is invalid, for example because of incorrect or mismatched return values.

.. py:exception:: ImmutableViolation

    Raises when attempting to perform a change a variable, constant or definition that cannot be changed. For example, trying to update a constant, or trying to assign to a function definition.

.. py:exception:: InterfaceViolation

    Raises when an interface is not fully implemented.

.. py:exception:: InvalidAttribute

    Raises on a reference to an attribute that does not exist.

.. py:exception:: InvalidLiteral

    Raises when no valid type can be found for a literal value.

    .. code-block:: vyper

        @external
        def foo():
            bar: decimal = 3.123456789123456789

    This example raises ``InvalidLiteral`` because the given literal value has too many decimal places and so cannot be assigned any valid Vyper type.

.. py:exception:: InvalidOperation

    Raises when using an invalid operator for a given type.

    .. code-block:: vyper

        @external
        def foo():
            a: String[10] = "hello" * 2

    This example raises ``InvalidOperation`` because multiplication is not possible on string types.

.. py:exception:: InvalidReference

    Raises on an invalid reference to an existing definition.

    .. code-block:: vyper

        baz: int128

        @external
        def foo():
            bar: int128 = baz

    This example raises ``InvalidReference`` because ``baz`` is a storage variable. The reference to it should be written as ``self.baz``.

.. py:exception:: InvalidType

    Raises when using an invalid literal value for the given type.

    .. code-block:: vyper

        @external
        def foo():
            bar: int128 = 3.5

    This example raises ``InvalidType`` because ``3.5`` is a valid literal value, but cannot be cast as ``int128``.

.. py:exception:: IteratorException

   Raises when an iterator is constructed or used incorrectly.

.. py:exception:: JSONError

    Raises when the compiler JSON input is malformed.

.. py:exception:: NamespaceCollision

    Raises when attempting to assign a variable to a name that is already in use.

.. py:exception:: NatSpecSyntaxException

    Raises when a contract contains an invalid :ref:`NatSpec<natspec>` docstring.

    .. code-block:: python

        vyper.exceptions.SyntaxException: line 14:5 No description given for tag '@param'
             13     @dev the feet are sticky like rice
        ---> 14     @param
        -------------^
             15     @return always True

.. py:exception:: NonPayableViolation

    Raises when attempting to access ``msg.value`` from within a function that has not been marked as ``@payable``.

    .. code-block:: vyper

        @public
        def _foo():
            bar: uint256 = msg.value

.. py:exception:: OverflowException

    Raises when a numeric value is out of bounds for the given type.

.. py:exception:: StateAccessViolation

    Raises when attempting to perform a modifying action within view-only or stateless context. For example, writing to storage in a ``@view`` function, reading from storage in a ``@pure`` function.

.. py:exception:: StructureException

    Raises on syntax that is parsable, but invalid in some way.

    .. code-block:: python

        vyper.exceptions.StructureException: line 181:0 Invalid top-level statement
             180
        ---> 181 '''
        ---------^
             182

.. py:exception:: SyntaxException

    Raises on invalid syntax that cannot be parsed.

    .. code-block:: python

        vyper.exceptions.SyntaxException: line 4:20 invalid syntax
                3 struct Bid:
        ---> 4   blindedBid bytes32
        ---------------------------^
                5   deposit: uint256

.. py:exception:: TypeMismatch

    Raises when attempting to perform an action between two or more objects with known, dislike types.

    .. code-block:: vyper

        @external
        def foo(:
            bar: int128 = 3
            foo: decimal = 4.2

            if foo + bar > 4:
                pass

    ``foo`` has a type of ``int128`` and ``bar`` has a type of ``decimal``, so attempting to add them together  raises a ``TypeMismatch``.

.. py:exception:: UndeclaredDefinition

    Raises when attempting to access an object that has not been declared.

.. py:exception:: VariableDeclarationException

    Raises on an invalid variable declaration.

    .. code-block:: bash

        vyper.exceptions.VariableDeclarationException: line 79:17 Persistent variable undeclared: highstBid
             78     # If bid is less than highest bid, bid fails
        ---> 79     if (value <= self.highstBid):
        -------------------------^
             80         return False

.. py:exception:: VersionException

    Raises when a contract version string is malformed or incompatible with the current compiler version.

.. py:exception:: ZeroDivisionException

    Raises when a divide by zero or modulo zero situation arises.

CompilerPanic
=============

.. py:exception:: CompilerPanic

    .. code:: shell

        $ vyper v.vy
        Error compiling: v.vy
        vyper.exceptions.CompilerPanic: Number of times repeated
        must be a constant nonzero positive integer: 0 Please create an issue.

    A compiler panic error indicates that there is a problem internally to the compiler and an issue should be reported right
    away on the Vyper Github page.  Open an issue if you are experiencing this error. Please `Open an Issue <https://github.com/vyperlang/vyper/issues>`_
