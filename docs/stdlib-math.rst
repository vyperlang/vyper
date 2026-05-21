.. index:: module, stdlib, math;

.. _stdlib-math:

Math Module
###########

The ``math`` module is a standard library module that provides mathematical functions. Import it with:

.. code-block:: vyper

    import math

Functions are then called as ``math.isqrt(x)``, ``math.sqrt(d)``, etc.

.. note::

    ``import math`` always refers to the standard library module. To import a local file named ``math.vy``, use a relative import: ``from . import math``.

Functions
=========

.. py:function:: sqrt(d: decimal) -> decimal

    Return the square root of the provided decimal number, using the Babylonian square root algorithm. The rounding mode is to round down to the nearest epsilon. For instance, ``math.sqrt(0.9999999998) == 0.9999999998``.

    .. code-block:: vyper

        import math

        @external
        @view
        def foo(d: decimal) -> decimal:
            return math.sqrt(d)

    .. code-block:: vyper

        >>> ExampleContract.foo(9.0)
        3.0

.. py:function:: isqrt(x: uint256) -> uint256

    Return the (integer) square root of the provided integer number, using the Babylonian square root algorithm. The rounding mode is to round down to the nearest integer. For instance, ``math.isqrt(101) == 10``.

    .. code-block:: vyper

        import math

        @external
        @view
        def foo(x: uint256) -> uint256:
            return math.isqrt(x)

    .. code-block:: vyper

        >>> ExampleContract.foo(101)
        10