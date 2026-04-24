.. _abstract-modules:

Abstract Modules
################

An abstract module is a special kind of :ref:`module <modules>` which offers points at which its logic can be customized.
This takes the form of methods decorated with ``@abstract``, and which do not have a body.
These methods can then be overridden to supply the custom logic.
Here is an example:

.. code-block:: vyper

    # base_token.vy
    # This is the abstract module

    balances: HashMap[address, uint256]

    # Abstract method is declared here
    @abstract
    def _before_transfer(sender: address, recipient: address, amount: uint256): ...

    def _transfer(sender: address, recipient: address, amount: uint256):
        # and used here
        self._before_transfer(sender, recipient, amount)
        self.balances[sender] -= amount
        self.balances[recipient] += amount

    @external
    def transfer(recipient: address, amount: uint256):
        self._transfer(msg.sender, recipient, amount)

The ``base_token`` module defines a transfer hook, ``_before_transfer()``, as an abstract method. It is called during every transfer, but has no implementation — that is left to whoever initializes this module. This lets library authors define *where* custom logic runs, while users decide *what* it does.

To supply an implementation, a module imports and ``initializes`` the abstract module, then provides an ``@override`` for each abstract method:

.. code-block:: vyper

    # pausable_token.vy

    import base_token

    initializes: base_token

    exports: base_token.transfer

    paused: bool

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"


Now every call to ``base_token._transfer()`` will check the pause flag before moving tokens. The override is resolved at compile time — there is no runtime dispatch or inheritance involved.

Rules for ``@abstract``
=======================

- ``@abstract`` can only be applied to **internal** functions. It cannot be used on ``@external`` or ``@deploy`` functions.
- The body of an abstract method must be ``...`` (the Ellipsis literal). A docstring may precede the ``...``:

  .. code-block:: vyper

      @abstract
      def _hook(x: uint256) -> uint256:
          """Called before every transfer."""
          ...

- ``@abstract`` can be combined with mutability decorators (``@view``, ``@pure``, ``@payable``, ``@nonpayable``) and ``@nonreentrant``.
- An abstract module can freely call its own abstract methods. Those calls are resolved to the concrete override at compile time.
- The top-level compilation target (i.e., the contract) cannot be an abstract module. All abstract methods reachable from it must have been overridden.

Overriding abstract methods
===========================

An override is declared with the ``@override(module_name)`` decorator, where ``module_name`` is the module containing the abstract method to override:

.. code-block:: vyper

    import base_token

    initializes: base_token

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"

Requirements:

- The overriding module must ``initializes`` the abstract module. A ``uses`` clause is not sufficient for overriding.
- The override must have the **same name** as the abstract method.
- Every abstract method in an initialized abstract module must be overridden.

Signature rules
---------------

The override's signature must be compatible with the abstract method's. Specifically:

- Each parameter of the abstract method must appear in the override at the same position, with the same name.
- The override **may add extra parameters** to the right, as long as they have default values.
- The override **may add a default value** to a parameter that was mandatory in the abstract method (making the override more permissive).
- Each parameter type in the override must be a **supertype** of the corresponding abstract parameter type (contravariance).
- The return type of the override must be a **subtype** of the abstract method's return type (covariance).
- The override's state mutability must be **at least as strict** as the abstract's. From least to most strict: ``payable``, ``nonpayable`` (the default), ``view``, ``pure``.
- ``@nonreentrant`` must match exactly — an override cannot add or remove it.
- All other decorators (besides ``@abstract``, ``@override``, and mutability) must be identical.

.. code-block:: vyper

    # abstract_m.vy

    @abstract
    def compute(x: uint256) -> uint256: ...

.. code-block:: vyper

    # override_module.vy

    import abstract_m

    initializes: abstract_m

    # Valid: adds an extra parameter with a default
    @override(abstract_m)
    def compute(x: uint256, y: uint256 = 0) -> uint256:
        return x + y

Overriding multiple abstract methods
-------------------------------------

A single function can override abstract methods from multiple modules by stacking ``@override`` decorators. The function's signature must be compatible with every abstract method it overrides.

.. code-block:: vyper

    import module_a
    import module_b

    initializes: module_a
    initializes: module_b

    @override(module_a)
    @override(module_b)
    def common_method() -> uint256:
        return 100

Abstract overrides (chaining)
-----------------------------

An overriding method can itself be marked ``@abstract``, deferring the final implementation to a module further down the initialization chain:

.. code-block:: vyper

    # base.vy
    @abstract
    def hook() -> uint256: ...

.. code-block:: vyper

    # middle.vy
    import base

    initializes: base

    @abstract
    @override(base)
    def hook() -> uint256: ...

.. code-block:: vyper

    # top.vy
    import middle

    initializes: middle

    @override(middle)
    def hook() -> uint256:
        return 42

The call chain is resolved at compile time: any call to ``base.hook()`` ultimately dispatches to the concrete implementation in ``top.vy``.

Default parameter values
========================

Abstract methods can use ``...`` as a default value for a parameter. This means "any default is acceptable in the override":

.. code-block:: vyper

    # abstract_m.vy

    @abstract
    def foo(x: uint256, y: uint256 = ...): ...

.. code-block:: vyper

    import abstract_m

    initializes: abstract_m

    # Valid: any default for y is accepted
    @override(abstract_m)
    def foo(x: uint256, y: uint256 = 10):
        pass

If the abstract method uses a concrete default value (e.g., ``y: uint256 = 10``), the override must use a **structurally equivalent** expression. For example, ``10`` must be overridden by ``10`` — not by ``5 + 5``.

Calling abstract methods
========================

**Within the abstract module itself**, abstract methods are called with ``self``, just like any other internal function:

.. code-block:: vyper

    # abstract_m.vy

    @abstract
    def _hook() -> uint256: ...

    def use_hook() -> uint256:
        return self._hook()

**From another module**, abstract methods are called through the module name. The calling module must declare ``uses`` for the abstract module:

.. code-block:: vyper

    import abstract_m

    uses: abstract_m

    def call_it() -> uint256:
        return abstract_m._hook()

All calls to abstract methods are resolved at compile time to the concrete override — there is no runtime dispatch.

.. note::

    A module that ``initializes`` an abstract module must override its methods, and should call the override directly. The compiler will error if you try to call the abstract method when a more concrete path exists, directing you to call the override instead.

Interaction with ``uses`` and ``initializes``
=============================================

- ``initializes`` is **required** to override abstract methods. It declares the module's storage location and creates the obligation to override all its abstract methods.
- ``uses`` allows a module to **call** an abstract module's methods (the calls resolve to the concrete override at compile time), but does **not** allow overriding.
- A module with only a ``uses`` clause cannot provide overrides for the abstract module.

.. code-block:: vyper

    # library.vy — uses the abstract module, does not override
    import abstract_m

    uses: abstract_m

    def helper() -> uint256:
        return abstract_m.foo()

.. code-block:: vyper

    # contract.vy — initializes and overrides
    import abstract_m
    import library

    initializes: abstract_m
    initializes: library[abstract_m := abstract_m]

    @override(abstract_m)
    def foo() -> uint256:
        return 42

Re-overriding is not allowed
=============================

Each abstract method can be overridden **exactly once** in the compilation tree. If two modules in the same compilation target both try to override the same abstract method, the compiler will raise an error. This prevents ambiguity about which implementation should be used.
