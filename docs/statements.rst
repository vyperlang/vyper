.. _statements:

Statements
##########

Vyper's statements are syntactically similar to Python, with some notable exceptions.

Control Flow
============

break
-----

The ``break`` statement terminates the nearest enclosing ``for`` loop.

.. code-block:: vyper

    for i in [1, 2, 3, 4, 5]:
        if i == a:
            break

In the above example, the ``for`` loop terminates if ``i == a``.

continue
--------

The ``continue`` statement begins the next cycle of the nearest enclosing ``for`` loop.

.. code-block:: vyper

    for i in [1, 2, 3, 4, 5]:
        if i != a:
            continue
        ...

In the above example, the ``for`` loop begins the next cycle immediately whenever ``i != a``.

pass
----

``pass`` is a null operation — when it is executed, nothing happens. It is useful as a placeholder when a statement is required syntactically, but no code needs to be executed:

.. code-block:: vyper

    # this function does nothing (yet!)

    @external
    def foo():
        pass

return
------

``return`` leaves the current function call with the expression list (or None) as a return value.

.. code-block:: vyper

    return RETURN_VALUE

If a function has no return type, it is allowed to omit the ``return`` statement, otherwise, the function must end with a ``return`` statement, or another terminating action such as ``raise``.

It is not allowed to have additional, unreachable statements after a ``return`` statement.

Event Logging
=============

log
---

The ``log`` statement is used to log an event:

.. code-block:: vyper

    log MyEvent(...)

The event must have been previously declared.

See :ref:`Event Logging<event-logging>` for more information on events.

Assertions and Exceptions
=========================

Vyper uses state-reverting exceptions to handle errors. Exceptions trigger the ``REVERT`` opcode (``0xFD``) with the provided reason given as the error message. When an exception is raised the code stops operation, the contract's state is reverted to the state before the transaction took place and the remaining gas is returned to the transaction's sender. When an exception happen in a sub-call, it “bubbles up” (i.e., exceptions are rethrown) automatically.

If the reason string is set to ``UNREACHABLE``, an ``INVALID`` opcode (``0xFE``) is used instead of ``REVERT``. In this case, calls that revert do not receive a gas refund. This is not a recommended practice for general usage, but is available for interoperability with various tools that use the ``INVALID`` opcode to perform dynamic analysis.

raise
-----

The ``raise`` statement triggers an exception and reverts the current call.

.. code-block:: vyper

    raise "something went wrong"

The error string is not required. If it is provided, it is limited to 1024 bytes.

assert
------

The ``assert`` statement makes an assertion about a given condition. If the condition evaluates falsely, the transaction is reverted.

.. code-block:: vyper

    assert x > 5, "value too low"

The error string is not required. If it is provided, it is limited to 1024 bytes.

This method's behavior is equivalent to:

.. code-block:: vyper

    if not cond:
        raise "reason"
