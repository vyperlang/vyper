.. index:: stock;company, company stock

Company Stock
*************

.. _company_stock:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

This contract is just a tad bit more thorough than the ones we've previously
encountered. In this example, we are going to look at a comprehensive contract
that manages the holdings of all shares of a company. The contract allows for
a person to buy, sell and transfer shares of a company as well as allowing for
the company to pay a person in ether. The company, upon initialization of the
contract, holds all shares of the company at first but can sell them all.

Let's get started.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :linenos:

.. note:: Throughout this contract, we use a pattern where ``@external`` functions return data from ``@internal`` functions that have the same name prepended with an underscore. This is because Vyper does not allow calls between external functions within the same contract. The internal function handles the logic, while the external function acts as a getter to allow viewing.

The contract contains a number of methods that modify the contract state as
well as a few 'getter' methods to read it. We first declare several events
that the contract logs. We then declare our global variables, followed by
function definitions.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 3
  :lines: 3-29

We initiate the ``company`` variable to be of type ``address`` that's public.
The ``totalShares`` variable is of type ``uint256``, which in this case
represents the total available shares of the company. The ``price`` variable
represents the wei value of a share and ``holdings`` is a mapping that maps an
address to the number of shares the address owns.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 31
  :lines: 31-42

In the constructor, we set up the contract to check for valid inputs during
the initialization of the contract via the two ``assert`` statements. If the
inputs are valid, the contract variables are set accordingly and the
company's address is initialized to hold all shares of the company in the
``holdings`` mapping.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 44
  :lines: 44-48

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 148
  :lines: 148-152

We will be seeing a few ``@view`` decorators in this contract—which is
used to decorate methods that simply read the contract state or return a simple
calculation on the contract state without modifying it. When called externally
(not as part of a transaction), view functions do not cost gas. Since Vyper is a statically typed
language, we see an arrow following the definition of the ``_stockAvailable()``
method, which simply represents the data type which the function is expected
to return. In the method, we simply key into ``self.holdings`` with the
company's address and check its holdings.  Because ``_stockAvailable()`` is an
internal method, we also include the ``stockAvailable()`` method to allow
external access.

Now, let's take a look at a method that lets a person buy stock from the
company's holding.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 50
  :lines: 50-66

The ``buyStock()`` method takes an amount of
ether sent and calculates the ``buyOrder`` (the stock value equivalence at
the time of call). The number of shares is deducted from the company's holdings
and transferred to the sender's in the ``holdings`` mapping.

Now that people can buy shares, how do we check someone's holdings?

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 67
  :lines: 67-71

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 154
  :lines: 154-158

The ``_getHolding()`` is another ``@view`` method that takes an ``address``
and returns its corresponding stock holdings by keying into ``self.holdings``.
Again, an external function ``getHolding()`` is included to allow access.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 73
  :lines: 73-77

To check the ether balance of the company, we can simply call the getter method
``cash()``.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 79
  :lines: 79-96

To sell a stock, we have the ``sellStock()`` method which takes a number of
stocks a person wishes to sell, and sends the equivalent value in ether to the
seller's address. We first ``assert`` that the number of stocks the person
wishes to sell is a value greater than ``0``. We also ``assert`` to see that
the user can only sell as much as the user owns and that the company has enough
ether to complete the sale. If all conditions are met, the holdings are deducted
from the seller and given to the company. The ethers are then sent to the seller.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 98
  :lines: 98-111

A stockholder can also transfer their stock to another stockholder with the
``transferStock()`` method. The method takes a receiver address and the number
of shares to send. It first ``asserts`` that the amount being sent is greater
than ``0`` and ``asserts`` whether the sender has enough stocks to send. If
both conditions are satisfied, the transfer is made.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 113
  :lines: 113-125

The company is also allowed to pay out an amount in ether to an address by
calling the ``payBill()`` method. This method should only be callable by the
company and thus first checks whether the method caller's address matches that
of the company. Another important condition to check is that the company has
enough funds to pay the amount. If both conditions satisfy, the contract
sends its ether to an address.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 128
  :lines: 128-132

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 142
  :lines: 142-146

We can also check how much the company has raised by multiplying the number of
shares the company has sold and the price of each share. Internally, we get
this value by calling the ``_debt()`` method. Externally it is accessed via ``debt()``.

.. literalinclude:: ../../examples/stock/company.vy
  :language: vyper
  :lineno-start: 134
  :lines: 134-140

Finally, in this ``worth()`` method, we can check the worth of a company by
subtracting its debt from its ether balance.

This contract has been the most thorough example so far in terms of its
functionality and features. Yet despite the thoroughness of such a contract, the
logic remained simple. Hopefully, by now, the Vyper language has convinced you
of its capabilities and readability in writing smart contracts.
