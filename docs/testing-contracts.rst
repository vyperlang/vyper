.. _testing-contracts:

Testing a Contract
##################

For testing Vyper contracts we recommend the use of `pytest <https://docs.pytest.org/en/latest/contents.html>`_ along with one of the following packages:

    * `Titanoboa <https://github.com/vyperlang/titanoboa>`_: A Vyper interpreter, pretty tracebacks, forking, debugging and deployment features. Maintained by the Vyper team. **(Recommended)**
    * `Brownie <https://github.com/eth-brownie/brownie>`_: A development and testing framework for smart contracts targeting the Ethereum Virtual Machine. **Note: Brownie is no longer actively maintained.**

Example usage for each package is provided in the sections listed below.

.. toctree::
    :maxdepth: 2

    testing-contracts-titanoboa.rst
    testing-contracts-brownie.rst
