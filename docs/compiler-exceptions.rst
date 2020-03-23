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

    Raises on an illegal function call, such as attempting to call between two public functions.

.. py:exception:: ArrayIndexException

    Raises when an array index is out of bounds.

.. py:exception:: ConstancyViolation

    Raises when attempting to perform a modifying action within a constant context. For example, writing to storage in a ``@constant`` function or modifying a constant variable.

.. py:exception:: EventDeclarationException

    Raises when an event declaration is invalid.

.. py:exception:: EMVVersionException

    Raises when a contract contains an action that cannot be performed with the active EVM ruleset.

.. py:exception:: FunctionDeclarationException

    Raises when a function declaration is invalid.

.. py:exception:: InterfaceViolation

    Raises when an interface is not fully implemented.

.. py:exception:: InvalidAttribute

    Raises on a reference to an attribute that does not exist.

.. py:exception:: InvalidLiteral

    Raises when attempting to use a literal value where the type is correct, but the value is still invalid in some way. For example, an address that is not check-summed.

    .. code-block:: python

        @public
        def foo():
            bar: address = 0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef

.. py:exception:: InvalidOperation

    Raises when using an invalid operator for a given type.

    .. code-block:: python

        @public
        def foo():
            a: string[10] = "hello" * 2

    This example raises ``InvalidOperation`` because multiplication is not possible on string types.

.. py:exception:: InvalidReference

    Raises on an invalid reference to an existing definition.

    .. code-block:: python

        baz: int128

        @public
        def foo():
            bar: int128 = baz

    This example raises ``InvalidReference`` because ``baz`` is a storage variable. The reference to it should be written as ``self.baz``.

.. py:exception:: InvalidType

    Raises when attempting to assign to an invalid type, or perform an action on a variable of the wrong type.

    .. code-block:: python

        bids: map(address, Bid[128])
        bidCounts: map(addres, int128)

    In the above example, the variable type ``address`` is misspelled.  Any word that is not a reserved word, and declares a variable type will
    return this error.

    .. code-block:: python

        vyper.exceptions.InvalidTypeException: line 28:15 Invalid base type: addres
                 27 bids: map(address, Bid[128])
            ---> 28 bidCounts: map(addres, int128)
            -----------------------^
                 29

.. py:exception:: JSONError

    Raises when the compiler JSON input is malformed.

.. py:exception:: NamespaceCollision

    Raises when attempting to assign a variable to a name that is already in use.

.. py:exception:: NatSpecSyntaxException

    Raises when a contract contains an invalid :ref:`NatSpec<structure-metadata>` docstring.

    .. code-block:: python

        vyper.exceptions.SyntaxException: line 14:5 No description given for tag '@param'
             13     @dev the feet are sticky like rice
        ---> 14     @param
        -------------^
             15     @return always True


.. py:exception:: NonPayableViolation

    Raises when attempting to access ``msg.value`` from within a private function.

    .. code-block:: python

        @private
        def _foo():
            bar: uint256 = msg.value

.. py:exception:: OverflowException

    Raises when a numeric value is out of bounds for the given type.

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
                5   deposit: wei_value

.. py:exception:: TypeMismatch

    Raises when attempting to perform an action between multiple objects of incompatible types.

    .. code-block:: bash

        vyper.exceptions.TypeMismatchException: line 4:4 Invalid type, expected: bytes32
             3     a: uint256 = 1
        ---> 4     b: bytes32 = a
        -----------^

    ``b`` has been set as type ``bytes32`` but the assignment is to ``a`` which is ``uint256``.

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

    ::

        $ vyper v.vy
        Error compiling: v.vy
        vyper.exceptions.CompilerPanic: Number of times repeated
        must be a constant nonzero positive integer: 0 Please create an issue.

    A compiler panic error indicates that there is a problem internally to the compiler and an issue should be reported right
    away on the Vyper Github page.  Open an issue if you are experiencing this error. Please `Open an Issue <https://github.com/vyperlang/vyper/issues>`_
