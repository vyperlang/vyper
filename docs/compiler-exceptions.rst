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

.. py:exception:: ArrayIndexException

    Raises when an array index is out of bounds.

.. py:exception:: ConstancyViolationException

    Raises when attempting to modify state from inside a function marked as constant.

.. py:exception:: EventDeclarationException

    Raises when an event declaration is invalid.

.. py:exception:: EMVVersionException

    Raises when a contract contains an action that cannot be performed with the active EVM ruleset.

.. py:exception:: FunctionDeclarationException

    Raises when a function declaration is invalid.

.. py:exception:: InvalidLiteralException

    Raises when attempting to use a literal value where the type is correct, but the value is still invalid in some way. For example, an address that is not check-summed.

    .. code-block:: python3

        @public
        def foo():
            bar: address = 0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef

.. py:exception:: InvalidTypeException

    Raises when attempting to assign to an invalid type, or perform an action on a variable of the wrong type.

    .. code-block:: python3

        bids: map(address, Bid[128])
        bidCounts: map(addres, int128)

    In the above example, the variable type ``address`` is misspelled.  Any word that is not a reserved word, and declares a variable type will
    return this error.

    .. code-block:: bash

        $ vyper blind_auction.vy
        Error compiling: blind.auction.vy /usr/lib/python3/dist-packages/apport/report.py:13:
        vyper.exceptions.InvalidTypeException: line 28:15 Invalid base type: addres
                 27 bids: map(address, Bid[128])
            ---> 28 bidCounts: map(addres, int128)
            -----------------------^
                 29

.. py:exception:: JSONError

    Raises when the compiler JSON input is malformed.

.. py:exception:: NamespaceCollision

    Raises when attempting to assign a variable to a name that is already in use.

.. py:exception:: NonPayableViolationException

    Raises when attempting to access ``msg.value`` from within a private function.

    .. code-block:: python3

        @private
        def _foo():
            bar: uint256 = msg.value

.. py:exception:: OverflowException

    Raises when a numeric value is out of bounds for the given type.

.. py:exception:: StructureException

    Raises on syntax that is parsable, but invalid in some way.

    .. code-block:: bash

        vyper.exceptions.StructureException: line 181:0 Invalid top-level statement
             180
        ---> 181 '''
        ---------^
             182

.. py:exception:: SyntaxException

    Raises on invalid syntax that cannot be parsed.

    .. code-block:: bash

        $ vyper blind_auction.vy
        vyper.exceptions.SyntaxException: line 4:20 invalid syntax
                3 struct Bid:
        ---> 4   blindedBid bytes32
        ---------------------------^
                5   deposit: wei_value

.. py:exception:: TypeMismatchException

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

    .. code-block:: python3

        $ vyper v.vy
        Error compiling: v.vy
        vyper.exceptions.CompilerPanic: Number of times repeated
        must be a constant nonzero positive integer: 0 Please create an issue.

    A compiler panic error indicates that there is a problem internally to the compiler and an issue should be reported right
    away on the Vyper Github page.  Open an issue if you are experiencing this error. Please `Open an Issue <https://github.com/vyperlang/vyper/issues>`_
