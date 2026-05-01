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

    @external
    def transfer(recipient: address, amount: uint256):
        # and used here
        self._before_transfer(msg.sender, recipient, amount)
        self.balances[msg.sender] -= amount
        self.balances[recipient] += amount

The ``base_token`` module defines a transfer hook, ``_before_transfer()``, as an abstract method. It is called during every transfer, but has no implementation — that is left to whoever initializes this module. This lets this module focus on *where* custom logic runs, while the overriding module decide *what* it does.

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


Now every call to ``base_token.transfer()`` will check the pause flag before moving tokens. The override is resolved at compile time — there is no runtime dispatch or inheritance involved.

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

As abstract modules are by essence incomplete, it is necessary for another module to complete them, by providing implementations for its abstract methods:

.. code-block:: vyper

    import base_token

    initializes: base_token

    @override(base_token)
    def before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"

For module M1 to override module M2:

1. M1 must :ref:`initialize <initializing-module>` M2
2. M1 must override each abstract method of M2, see :ref:`Overriding abstract methods <overriding-abstract-methods>`

.. note::
    So there is no choice to be made about which override to choose, abstract modules can only be overridden once. This is guaranteed by the initialization system.

.. _overriding-abstract-methods:

Overriding abstract methods
===========================

To override abstract method ``_before_transfer`` of module ``base_token``, the overriding module must define an internal method ``_before_transfer`` with an ``@override(my_abstract_module)`` decorator:

.. code-block:: vyper

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"

Since any call to ``base_token._before_transfer`` will be replaced at compile-time to a call to the overriding ``_before_transfer``, it is necessary that any call to the former is a valid call to the latter:

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
    def compute(x: uint8) -> uint8:
        return x + 1

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

A good heuristic is the following; the override must have:

- The same parameters as the abstract method: same name, same type, and same default value.
- The same return type as the abstract method.
- The same decorators as the abstract method, except ``@override`` and ``@abstract``.

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

Abstract methods are called in the same way concrete methods are.
Additionally, calling the abstract methods of another module requires :ref:`using <uses-statement>` it.

.. code-block:: vyper

    # base_token.vy

    @abstract
    def _before_transfer(sender: address, recipient: address, amount: uint256): ...

    @external
    def transfer(recipient: address, amount: uint256):
        # call to abstract method in same module
        self._before_transfer(msg.sender, recipient, amount)
        self.balances[msg.sender] -= amount
        self.balances[recipient] += amount

.. code-block:: vyper

    import base_token

    # required by the call below
    uses: base_token

    def simulate_transfer(sender: address, recipient: address, amount: uint256):
        # call to abstract method in different module
        base_token._before_transfer(sender, recipient, amount)

All calls to abstract methods are resolved at compile time to the concrete override: there is no runtime dispatch.

When a module overrides an abstract method, the compiler requires callers to use the most concrete path available.
In particular, if ``self._before_transfer`` overrides ``base_token._before_transfer``, any call within that module must go through ``self``, not through ``base_token``:

.. code-block:: vyper

    import base_token

    initializes: base_token

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        assert not self.paused, "transfers are paused"

    def foo():
        # Valid: uses the override directly
        self._before_transfer(msg.sender, msg.sender, 0)

        # Invalid: base_token._before_transfer is overridden by
        # self._before_transfer, call that instead.
        base_token._before_transfer(msg.sender, msg.sender, 0)


Advanced Uses
=============

In this section we will explain consequences of the above specification which might not jump to mind, and are useful in advanced contexts.

Abstract overriding modules
---------------------------

An overriding module can itself be abstract.
In other words, ``@abstract`` and ``@override`` can co-exist in the same module (and even :ref:`on the same method <deferring_overriding>`):

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

Overriding multiple modules
---------------------------

A single module can initialize more than one abstract module, providing overrides for each independently.
This is how you compose unrelated concerns, for instance combining transfer validation from one module with fee configuration from another.

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
    # `minter.get_role` which does not have that parameter, and
    # `authentication_provider.get_role` which has it as a mandatory parameter

    @override(minter)
    @override(authentication_provider)
    def get_role(user: address, default: my_roles.ROLE = empty(my_roles.ROLE)) -> my_roles.ROLE:
        role: my_roles.ROLE = self.roles[user]
        if role == empty(my_roles.ROLE):
            return default
        return role


.. _deferring_overriding:

Deferring overriding
--------------------

In some cases a module might not want to override every method of another, if such is the case, ``@abstract`` and ``@override`` can be combined to defer providing an implementation:

.. code-block:: vyper

    # base.vy

    @abstract
    def method_a() -> uint256: ...

    @abstract
    def method_b() -> uint256: ...

.. code-block:: vyper

    # middle.vy
    import base

    initializes: base
    
    # Concrete override
    @override(base)
    def method_a() -> uint256:
        return 0

    # Delegates
    @abstract
    @override(base)
    def method_b() -> uint256: ...

.. code-block:: vyper

    # top.vy
    import middle

    initializes: middle

    @override(middle)
    def method_b() -> uint256:
        return 42

Any call to ``base.method_b`` resolves to a call to the concrete implementation: ``top.method_b``.

Default Implementation
----------------------

It's sometimes desirable to provide a default implementation for an abstract method, this can be done by defining a separate method which holds this logic:

.. code-block:: vyper

    # base_token.vy

    @abstract
    def _before_transfer(sender: address, recipient: address, amount: uint256): ...

    def _before_transfer_default(sender: address, recipient: address, amount: uint256):
        assert sender != empty(address), "transfer from zero address"
        assert recipient != empty(address), "transfer to zero address"

This allows accepting the default implementation downstream as:

.. code-block:: vyper

    # simple_token.vy

    import base_token

    initializes: base_token

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):
        base_token._before_transfer_default(sender, recipient, amount)

And even allows using the default implementation while adding extra logic:

.. code-block:: vyper

    # pausable_token.vy

    import base_token

    initializes: base_token

    paused: bool

    @override(base_token)
    def _before_transfer(sender: address, recipient: address, amount: uint256):

        # Use default check
        base_token._before_transfer_default(sender, recipient, amount)

        # Add custom logic
        assert not self.paused, "transfers are paused"

Recommendations:

1. The default implementation should have the same name as the abstract method followed by ``_default``.
2. The default implementation should not be called anywhere (except in the override), as this defeats the purpose of making the method abstract in the first place.
