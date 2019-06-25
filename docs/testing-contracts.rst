.. index:: testing;testing;

.. _testing:

******************
Testing a Contract
******************

This documentation recommends the use of the `pytest <https://docs.pytest.org/en/latest/contents.html>`_ framework with the `ethereum-tester <https://github.com/ethereum/ethereum-tester>`_ package.
Prior to testing, the vyper specific contract conversion and the blockchain related fixtures need to be set up. These fixtures will be used in every test file and should therefore be defined in `conftest.py <https://docs.pytest.org/en/latest/fixture.html#conftest-py-sharing-fixture-functions>`_.

=================================
Vyper Contract and Basic Fixtures
=================================

.. code-block:: python

  import pytest
  from eth_tester import EthereumTester
  from vyper import compiler

  from web3 import Web3
  from web3.contract import (
      Contract,
      mk_collision_prop,
  )
  from web3.providers.eth_tester import EthereumTesterProvider

  from eth_utils.toolz import compose


  class VyperMethod:
      ALLOWED_MODIFIERS = {'call', 'estimateGas', 'transact', 'buildTransaction'}

      def __init__(self, function, normalizers=None):
          self._function = function
          self._function._return_data_normalizers = normalizers

      def __call__(self, *args, **kwargs):
          return self.__prepared_function(*args, **kwargs)

      def __prepared_function(self, *args, **kwargs):
          if not kwargs:
              modifier, modifier_dict = 'call', {}
              fn_abi = [
                  x
                  for x
                  in self._function.contract_abi
                  if x.get('name') == self._function.function_identifier
              ].pop()
              # To make tests faster just supply some high gas value.
              modifier_dict.update({'gas': fn_abi.get('gas', 0) + 50000})
          elif len(kwargs) == 1:
              modifier, modifier_dict = kwargs.popitem()
              if modifier not in self.ALLOWED_MODIFIERS:
                  raise TypeError(
                      "The only allowed keyword arguments are: %s" % self.ALLOWED_MODIFIERS)
          else:
              raise TypeError("Use up to one keyword argument, one of: %s" % self.ALLOWED_MODIFIERS)

          return getattr(self._function(*args), modifier)(modifier_dict)


  class VyperContract:

      """
      An alternative Contract Factory which invokes all methods as `call()`,
      unless you add a keyword argument. The keyword argument assigns the prep method.

      This call

      > contract.withdraw(amount, transact={'from': eth.accounts[1], 'gas': 100000, ...})

      is equivalent to this call in the classic contract:

      > contract.functions.withdraw(amount).transact({'from': eth.accounts[1], 'gas': 100000, ...})
      """
      def __init__(self, classic_contract, method_class=VyperMethod):

          classic_contract._return_data_normalizers += CONCISE_NORMALIZERS
          self._classic_contract = classic_contract
          self.address = self._classic_contract.address

          protected_fn_names = [fn for fn in dir(self) if not fn.endswith('__')]

          for fn_name in self._classic_contract.functions:

              # Override namespace collisions
              if fn_name in protected_fn_names:
                  _concise_method = mk_collision_prop(fn_name)

              else:
                  _classic_method = getattr(
                      self._classic_contract.functions,
                      fn_name)

                  _concise_method = method_class(
                      _classic_method,
                      self._classic_contract._return_data_normalizers
                  )

              setattr(self, fn_name, _concise_method)

      @classmethod
      def factory(cls, *args, **kwargs):
          return compose(cls, Contract.factory(*args, **kwargs))


  def _none_addr(datatype, data):
      if datatype == 'address' and int(data, base=16) == 0:
          return (datatype, None)
      else:
          return (datatype, data)


  CONCISE_NORMALIZERS = (_none_addr, )


  @pytest.fixture
  def tester():
      t = EthereumTester()
      return t


  def zero_gas_price_strategy(web3, transaction_params=None):
      return 0  # zero gas price makes testing simpler.


  @pytest.fixture
  def w3(tester):
      w3 = Web3(EthereumTesterProvider(tester))
      w3.eth.setGasPriceStrategy(zero_gas_price_strategy)
      return w3


  def _get_contract(w3, source_code, *args, **kwargs):
      out = compiler.compile_code(
          source_code,
          ['abi', 'bytecode'],
          interface_codes=kwargs.pop('interface_codes', None),
      )
      abi = out['abi']
      bytecode = out['bytecode']

      value = kwargs.pop('value_in_eth', 0) * 10**18  # Handle deploying with an eth value.

      c = w3.eth.contract(abi=abi, bytecode=bytecode)
      deploy_transaction = c.constructor(*args)
      tx_info = {
          'from': w3.eth.accounts[0],
          'value': value,
          'gasPrice': 0,
      }
      tx_info.update(kwargs)
      tx_hash = deploy_transaction.transact(tx_info)
      address = w3.eth.getTransactionReceipt(tx_hash)['contractAddress']
      contract = w3.eth.contract(
          address,
          abi=abi,
          bytecode=bytecode,
          ContractFactoryClass=VyperContract,
      )
      return contract


  @pytest.fixture
  def get_contract(w3):
      def get_contract(source_code, *args, **kwargs):
          return _get_contract(w3, source_code, *args, **kwargs)
      return get_contract

This is the minimum requirement to load a vyper contract and start testing. More fixtures and functions will be introduced later.
The rest of this chapter assumes, that you have this code set up in your ``conftest.py`` file.

.. note::
    Since the testing is done in the pytest framework, you can make use of `pytest.ini, tox.ini and setup.cfg <https://docs.pytest.org/en/latest/customize.html>`_ and you can use most IDEs' pytest plugins.

=============================
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

==============================
Events and Failed Transactions
==============================

To test events and failed transactions we expand our simple storage contract to include an event and two conditions for a failed transaction: ``advanced_storage.vy``

.. literalinclude:: ../examples/storage/advanced_storage.vy
  :language: python

Next, we add two new fixtures to ``conftest.py`` that will allow us to read the event logs and to check for failed transactions.


.. code-block:: python

  from eth_tester.exceptions import TransactionFailed

  @pytest.fixture
  def get_logs(w3):
      def get_logs(tx_hash, c, event_name):
          tx_receipt = w3.eth.getTransactionReceipt(tx_hash)
          logs = c._classic_contract.events[event_name]().processReceipt(tx_receipt)
          return logs
      return get_logs

  @pytest.fixture
  def assert_tx_failed(tester):
      def assert_tx_failed(function_to_test, exception=TransactionFailed, exc_text=None):
          snapshot_id = tester.take_snapshot()
          with pytest.raises(exception) as excinfo:
              function_to_test()
          tester.revert_to_snapshot(snapshot_id)
          if exc_text:
              assert exc_text in str(excinfo.value)
      return assert_tx_failed

The fixture to assert failed transactions defaults to check for a ``TransactionFailed`` exception, but can be used to check for different exceptions too, as shown below.
Also note that the chain gets reverted to the state before the failed transaction.

Finally, we create a new file ``test_advanced_storage.py`` where we use the new fixtures to test failed transactions and events.

.. literalinclude:: ../tests/examples/storage/test_advanced_storage.py
  :language: python


