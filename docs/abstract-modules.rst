.. _abstract-modules:

Abstract Modules
################

An abstract module is a special kind of :ref:`module <modules>` which offers points at which its logic can be customized.
This takes the form of **abstract methods**, methods decorated with ``@abstract``.
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

As you can see in the example above, what makes a module "abstract" is only the presence of abstract methods.
Furthermore, that is the only difference, everything that can be done in a concrete (i.e. non-abstract) module can also be done in an abstract module.

Abstract methods
================

An abstract method is an :ref:internal method decorated with ``@abstract``.
Its body must consist of an Ellipsis literal (``...``) potentially preceded by a docstring and comments.

.. code-block:: vyper

    @abstract
    def an_abstract_method(x: uint256) -> uint256:
        """This is a docstring"""
        ...

There are no other restrictions on abstract methods, they can have any signature, can take any decorator, and be called like concrete methods:

.. code-block:: vyper

    @pure
    @abstract
    def name() -> String[10]:
        ...

    @payable
    @nonreentrant
    @abstract
    def foo(bar: DynArray[Bytes[20], 10]) -> DynArray[String[15], 38]:
        ...

    def concrete_calls():
        _name: String[10] = self.name()
        complex_expression: String[15] = self.foo([]).pop()

Overriding an abstract module
=============================

As abstract modules are by essence incomplete, it is necessary for another module to complete them, by providing implementations for its abstract methods.

For module M1 to override module M2:
1. M1 must initialize M2 TODO: add ref to initializes
2. M1 must override each abstract method of M2 TODO: add ref to initializes

TODO: Example here ?

Note in particular that abstract modules can override other abstract modules:

TODO: Example here

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

The override must be callable in all the same ways the abstract method is:

.. code-block:: vyper

    # abstract_m.vy
    @pure
    @abstract
    def compute(x: uint256) -> uint256: ...

.. code-block:: vyper

    import abstract_m
    initializes: abstract_m

    # Valid: signature matches exactly
    @pure
    @override(abstract_m)
    def compute(x: uint256) -> uint256:
        return x + 1

.. code-block:: vyper

    import abstract_m
    initializes: abstract_m

    # Invalid: parameter and return type don't match the ones in abstract_m.compute
    @pure
    @override(abstract_m)
    def compute(y: uint8) -> uint8:
        return y + 1

.. code-block:: vyper

    import abstract_m
    initializes: abstract_m

    # Invalid: parameter name doesn't match
    @pure
    @override(abstract_m)
    def compute(y: uint256) -> uint256:
        return y + 1

.. code-block:: vyper

    import abstract_m
    initializes: abstract_m

    # Invalid: Has looser mutability: nonpayable vs the original which is view
    @nonpayable
    @override(abstract_m)
    def compute(y: uint256) -> uint256:
        return y + 1

A good heuristic is the following:
- The override must have the same parameters as the abstract method: same name, same type, and same default value.
- The override must have the same return type as the abstract method.
- The override must have the same decorators as the abstract method, except ``@override`` and ``@abstract``.

Following the rules above will always result in a valid override.
However these might prove too restrictive in your use-case, for this reason the actual rules are more flexible:

- Each parameter of the abstract method must appear in the override at the same position, with the same name.
- If the abstract method defines a default argument for a parameter, the value of the default argument must match in the override. Any value matches an ellipsis (``...``).
- The override may add extra parameter to the right, as long as they have default values.
- The override may add a default value to a parameter that was mandatory in the abstract method (making the override more permissive).
- Each parameter type in the override must be the same (or more general) than the corresponding parameter type in the abstract method.
- The return type of the override must be the same (or more precise) than the abstract method's return type.
- The override's :ref:`mutability <function-mutability>` must the same (or stricter) than the abstract's.
- The override's :ref:`reentrancy <reentrancy>` must match exactly the one of the abstract method.

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
