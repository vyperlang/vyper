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

An abstract method is an :ref:`internal method <structure-functions-internal>` decorated with ``@abstract``.
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

1. M1 must :ref:`initialize <initializing-module>` M2
2. M1 must override each abstract method of M2, see :ref:`Overriding abstract methods <overriding-abstract-methods>`

.. code-block:: vyper

    import base_token

    initializes: base_token

    @override(base_token)
    def before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"

Note in particular that an overriding module can itself be abstract.
In other words, ``@abstract`` and ``@override`` can co-exist in the same module:

.. code-block:: vyper

    # checked_token.vy

    import base_token

    initializes: base_token

    @override(base_token)
    def before_transfer(sender: address, recipient: address, amount: uint256):
        assert self.check_address(sender), "Invalid sender"
        assert self.check_address(recipient), "Invalid recipient"
        assert self.check_cap(amount), "Invalid amount"

    @abstract
    def check_cap(amount: uint256) -> bool:
        ...

    @abstract
    def check_address(addr: address) -> bool:
        ...

Here ``checked_token`` provides a concrete ``_before_transfer`` for ``base_token``, but it is itself an abstract module because it introduces ``check_cap`` and ``check_address``. A final module completes the chain by overriding those:

.. code-block:: vyper

    # my_token.vy
    import checked_token

    initializes: checked_token

    MAX_AMOUNT: constant(uint256) = 10**24
    total_supply: uint256

    @override(checked_token)
    def check_cap(amount: uint256) -> bool:
        return 0 < amount <= MAX_AMOUNT

    @override(checked_token)
    def check_address(addr: address) -> bool:
        return addr != empty(address)

See also :ref:`Abstract overrides (chaining) <abstract-overrides-chaining>`.

.. _overriding-abstract-methods:

Overriding abstract methods
===========================

To override abstract method ``_before_transfer`` of module ``base_token``, the overriding module must define an internal method ``_before_transfer`` with an ``@override(my_abstract_module)`` decorator:

.. code-block:: vyper

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"

Since any call to ``base_token._before_transfer`` will be replaced at compile-time to a call to the overriding ``_before_transfer``, it is necessary that any call to the former is a valid call to the latter:


Signature rules
---------------

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
- The override may add extra parameters to the right, as long as they have default values.
- The override may add a default value to a parameter that was mandatory in the abstract method.
- Each parameter type in the override must be a super-type of the corresponding parameter type in the abstract method.
- The return type of the override must be a sub-type of the abstract method's return type.
- The override's :ref:`mutability <function-mutability>` must the same (or stricter) than the abstract's.
- The override's :ref:`reentrancy <reentrancy>` must match exactly the one of the abstract method.


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


Advanced Uses
=============

In this section we will explain consequences of the above specification which might not jump to mind, and are only useful in advanced contexts.

Overriding multiple modules
---------------------------

A single module can initialize more than one abstract module, providing overrides for each independently.
This is how you compose unrelated concerns — for instance, combining transfer validation from one module with fee configuration from another.

Using ``base_token`` from the :ref:`earlier example <abstract-modules>`, consider a second abstract module that manages access control:

.. code-block:: vyper

    # access_control.vy

    @abstract
    def _is_allowed(user: address) -> bool: ...

    def check_allowed(user: address):
        assert self._is_allowed(user), "access denied"

A contract can initialize both modules and override each abstract method:

.. code-block:: vyper

    # my_token.vy

    import base_token
    import access_control

    initializes: base_token
    initializes: access_control

    exports: base_token.transfer

    allowed: HashMap[address, bool]

    @override(access_control)
    def _is_allowed(user: address) -> bool:
        return self.allowed[user]

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        access_control.check_allowed(sender)

The overriding module weaves both concerns together: ``_before_transfer`` delegates to the access control module to gate who can send tokens.

Overriding multiple abstract methods
------------------------------------

When a module overrides multiple others, it might happen that the abstract modules share a method name.
To handle this case, it is possible for a single method to override multiple, by adding multiple ``@override`` decorators.
Note however that the method must be a :ref:`valid override <overriding-abstract-methods>` for every abstract method:

.. code-block:: vyper

    # minter.vy

    import my_roles

    @abstract
    def get_role(user: address) -> my_roles.ROLE: ...

.. code-block:: vyper

    # authentication_provider.vy

    import my_roles

    @abstract
    def get_role(user: address, default: my_roles.ROLE) -> my_roles.ROLE: ...

.. code-block:: vyper

    import minter
    import authentication_provider

    initializes: minter
    initializes: authentication_provider

    roles: HashMap[address, my_roles.ROLE]

    # By having `default` as an optional parameter, it's a valid override of both
    # `minter.get_role` which does not have that parameter
    # `authentication_provider.get_role` which has it as a mandatory parameter

    @override(minter)
    @override(authentication_provider)
    def get_role(user: address, default: my_roles.ROLE = empty(my_roles.ROLE)) -> my_roles.ROLE:
        role: my_roles.ROLE = self.roles[user]
        if role == empty(my_roles.ROLE):
            return default
        return role


.. _abstract-overrides-chaining:

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
