.. index:: factory pattern

Factory Pattern
***************

.. _factory:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

The factory pattern deploys and registers multiple contract instances.
This example shows a factory that registers exchanges and routes trades between them.

Factory Contract
================

.. literalinclude:: ../../examples/factory/Factory.vy
  :language: vyper
  :linenos:

Exchange Contract
=================

.. literalinclude:: ../../examples/factory/Exchange.vy
  :language: vyper
  :linenos:

How the pattern works:

1. Deploy the Exchange code and record its ``codehash``
2. Deploy the Factory with the exchange codehash
3. Deploy Exchange instances (one per token)
4. Each Exchange calls ``factory.register()`` to register itself
5. The Factory verifies the caller's codehash matches the expected exchange code
6. Users can now trade between any registered tokens via ``factory.trade()``

The ``msg.sender.codehash`` check ensures only legitimate exchange contracts can register.
