.. _testing-contracts-brownie:

Testing with Brownie
####################

`Brownie <https://github.com/iamdefinitelyahuman/brownie>`_ is a Python-based development and testing framework for smart contracts. It includes a pytest plugin with fixtures that simplify testing your contract.

This section provides a quick overview of testing with Brownie. To learn more, you can view the Brownie documentation on `writing unit tests <https://eth-brownie.readthedocs.io/en/stable/tests-pytest-intro.html>`_ or join the `Ethereum Python Dev Discord <https://discord.gg/abJEARdx3Q>`_ ``#brownie`` channel.

Getting Started
===============

In order to use Brownie for testing you must first `initialize a new project <https://eth-brownie.readthedocs.io/en/stable/init.html>`_. Create a new directory for the project, and from within that directory type:

.. code:: shell

    $ brownie init

This will create an empty `project structure <https://eth-brownie.readthedocs.io/en/stable/structure.html#structure>`_ within the directory. Store your contract sources within the project's ``contracts/`` directory and your tests within ``tests/``.

Writing a Basic Test
====================

Assume the following simple contract ``Storage.vy``. It has a single integer variable and a function to set that value.

.. literalinclude:: ../examples/storage/storage.vy
    :caption: storage.vy
    :language: vyper
    :linenos:

We create a test file ``tests/test_storage.py`` where we write our tests in pytest style.

.. code-block:: python
    :caption: test_storage.py
    :linenos:

    import pytest

    INITIAL_VALUE = 4


    @pytest.fixture
    def storage_contract(Storage, accounts):
        # deploy the contract with the initial value as a constructor argument
        yield Storage.deploy(INITIAL_VALUE, {'from': accounts[0]})


    def test_initial_state(storage_contract):
        # Check if the constructor of the contract is set up properly
        assert storage_contract.storedData() == INITIAL_VALUE


    def test_set(storage_contract, accounts):
        # set the value to 10
        storage_contract.set(10, {'from': accounts[0]})
        assert storage_contract.storedData() == 10  # Directly access storedData

        # set the value to -5
        storage_contract.set(-5, {'from': accounts[0]})
        assert storage_contract.storedData() == -5


In this example we are using two fixtures which are provided by Brownie:

* ``accounts`` provides access to the :py:class:`Accounts <brownie.network.account.Accounts>` container, containing all of your local accounts
* ``Storage`` is a dynamically named fixture that provides access to a :py:class:`ContractContainer <brownie.network.contract.ContractContainer>` object, used to deploy your contract

.. note::

    To run the tests, use the ``brownie test`` command from the root directory of your project.

Testing Events
==============

For the remaining examples, we expand our simple storage contract to include an event and two conditions for a failed transaction: ``advanced_storage.vy``

.. literalinclude:: ../examples/storage/advanced_storage.vy
    :caption: advanced_storage.vy
    :linenos:
    :language: python

To test events, we examine the :py:class:`TransactionReceipt <brownie.network.transaction.TransactionReceipt>` object which is returned after each successful transaction. It contains an :py:class:`events <brownie.network.event.EventDict>` member with information about events that fired.

.. code-block:: python
    :linenos:

    import brownie

    INITIAL_VALUE = 4


    @pytest.fixture
    def adv_storage_contract(AdvancedStorage, accounts):
        yield AdvancedStorage.deploy(INITIAL_VALUE, {'from': accounts[0]})

    def test_events(adv_storage_contract, accounts):
        tx1 = adv_storage_contract.set(10, {'from': accounts[0]})
        tx2 = adv_storage_contract.set(20, {'from': accounts[1]})
        tx3 = adv_storage_contract.reset({'from': accounts[0]})

        # Check log contents
        assert len(tx1.events) == 1
        assert tx1.events[0]['value'] == 10

        assert len(tx2.events) == 1
        assert tx2.events[0]['setter'] == accounts[1]

        assert not tx3.events   # tx3 does not generate a log


Handling Reverted Transactions
==============================

Transactions that revert raise a :py:class:`VirtualMachineError <brownie.exceptions.VirtualMachineError>` exception. To write assertions around this you can use :py:class:`brownie.reverts <brownie.test.plugin.RevertContextManager>` as a context manager. It functions very similarly to :py:func:`pytest.raises <pytest.raises>`.

:py:class:`brownie.reverts <brownie.test.plugin.RevertContextManager>` optionally accepts a string as an argument. If given, the error string returned by the transaction must match it in order for the test to pass.


.. code-block:: python
    :linenos:

    import brownie

    INITIAL_VALUE = 4


    @pytest.fixture
    def adv_storage_contract(AdvancedStorage, accounts):
        yield AdvancedStorage.deploy(INITIAL_VALUE, {'from': accounts[0]})


    def test_failed_transactions(adv_storage_contract, accounts):
        # Try to set the storage to a negative amount
        with brownie.reverts("No negative values"):
            adv_storage_contract.set(-10, {"from": accounts[1]})

        # Lock the contract by storing more than 100. Then try to change the value

        adv_storage_contract.set(150, {"from": accounts[1]})
        with brownie.reverts("Storage is locked when 100 or more is stored"):
            adv_storage_contract.set(10, {"from": accounts[1]})

        # Reset the contract and try to change the value
        adv_storage_contract.reset({"from": accounts[1]})
        adv_storage_contract.set(10, {"from": accounts[1]})
        assert adv_storage_contract.storedData() == 10
