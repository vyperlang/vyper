.. index:: testing;testing;

.. _testing:

Testing a Contract
******************

This documentation recommends the use of the `pytest <https://docs.pytest.org/en/latest/contents.html>`_ framework with
the `ethereum-tester <https://github.com/ethereum/ethereum-tester>`_ package.
Prior to testing, the vyper specific contract conversion and the blockchain related fixtures need to be set up.
These fixtures will be used in every test file and should therefore be defined in
`conftest.py <https://docs.pytest.org/en/latest/fixture.html#conftest-py-sharing-fixture-functions>`_.

.. note::
    Since the testing is done in the pytest framework, you can make use of
    `pytest.ini, tox.ini and setup.cfg <https://docs.pytest.org/en/latest/customize.html>`_ and you can use most IDEs'
    pytest plugins.

Vyper Contract and Basic Fixtures
=================================

.. literalinclude:: ../tests/base_conftest.py
    :language: python
    :linenos:

This is the base requirement to load a vyper contract and start testing. The last two fixtures are optional and will be
discussed later. The rest of this chapter assumes, that you have this code set up in your ``conftest.py`` file.
Alternatively, you can import the fixtures to ``conftest.py`` or use
`pytest_plugins <https://docs.pytest.org/en/latest/plugins.html>`_.

Load Contract and Basic Tests
=============================

Assume the following simple contract ``storage.vy``. It has a single integer variable and a function to set that value.

.. literalinclude:: ../examples/storage/storage.vy
  :language: python

We create a test file ``test_storage.py`` where we write our tests in pytest style.

.. literalinclude:: ../tests/examples/storage/test_storage.py
  :language: python

First we create a fixture for the contract which will compile our contract and set up a Web3 contract object.
We then use this fixture for our test functions to interact with the contract.

.. note::
    To run the tests, call ``pytest`` or ``python -m pytest`` from your project directory.

Events and Failed Transactions
==============================

To test events and failed transactions we expand our simple storage contract to include an event and two conditions for a failed transaction: ``advanced_storage.vy``

.. literalinclude:: ../examples/storage/advanced_storage.vy
  :language: python

Next, we take a look at the two fixtures that will allow us to read the event logs and to check for failed transactions.

.. literalinclude:: ../tests/base_conftest.py
    :language: python
    :pyobject: assert_tx_failed

The fixture to assert failed transactions defaults to check for a ``TransactionFailed`` exception, but can be used to check for different exceptions too, as shown below.
Also note that the chain gets reverted to the state before the failed transaction.


.. literalinclude:: ../tests/base_conftest.py
    :language: python
    :pyobject: get_logs

This fixture will return a tuple with all the logs for a certain event and transaction. The length of the tuple equals the number of events (of the specified type) logged and should be checked first.


Finally, we create a new file ``test_advanced_storage.py`` where we use the new fixtures to test failed transactions and events.

.. literalinclude:: ../tests/examples/storage/test_advanced_storage.py
  :language: python


