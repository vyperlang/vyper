.. _event-logging:

Event Logging
#############

Vyper can log events to be caught and displayed by user interfaces.

Example of Logging
==================

This example is taken from the `sample ERC20 contract <https://github.com/vyperlang/vyper/blob/master/examples/tokens/ERC20.vy>`_ and shows the basic flow of event logging:

.. code-block:: python

    # Events of the token.
    event Transfer:
        sender: indexed(address)
        receiver: indexed(address)
        amount: uint256

    event Approval:
        owner: indexed(address)
        spender: indexed(address)
        amount: uint256

    # Transfer some tokens from message sender to another address
    def transfer(receiver: address, amount: uint256) -> bool:

       ... Logic here to do the real work ...

       # All done, log the event for listeners
       log Transfer(msg.sender, receiver, amount)

Let's look at what this is doing.

    1. We declare two event types to log. The two events are similar in that they contain two indexed address fields. Indexed fields do not make up part of the event data itself, but can be searched by clients that want to catch the event. Also, each event contains a data field that contains abi-encoded unindexed arguments. Events can contain several arguments with any names desired.
    2. In the ``transfer`` function, after we do whatever work is necessary, we log the event. We pass three arguments, corresponding with the three arguments of the ``Transfer`` event declaration.

Clients listening to the events can handle the events they are interested in using a `library such as ape <https://docs.apeworx.io/ape/stable/methoddocs/contracts.html#ape.contracts.base.ContractEvent>`_:

.. code-block:: python

    token = project.Token.at("0x1234...ab67")

    for log in token.Transfer.range(chain.blocks.height):
        print(log.event_arguments)


Declaring Events
================

Let's look at an event declaration in more detail.

.. code-block:: python

    event Transfer:
        sender: indexed(address)
        receiver: indexed(address)
        value: uint256

Event declarations look similar to struct declarations, containing one or more arguments that are passed to the event. Typical events will contain two kinds of arguments:

    * **Indexed** arguments, which can be searched for by listeners. Each indexed argument is identified by the ``indexed`` keyword.  Here, each indexed argument is an address. You can have any number of indexed arguments, but indexed arguments are not passed directly to listeners, although some of this information (such as the sender) may be available in the listener's `results` object.
    * **Value** arguments, which are passed through to listeners. You can have any number of value arguments and they can have arbitrary names, but each is limited by the EVM to be no more than 32 bytes.

It is also possible to create an event with no arguments. In this case, use the ``pass`` statement:

.. code-block:: python

    event Foo: pass

Logging Events
==============

Once an event is declared, you can log (emit) events. You can emit events as many times as you want to. Please note that events do not take state storage and thus cost less gas: this makes events a good way to make information more available to clients. It's a good practice to emit an event for every state change.

Logging events is done using the ``log`` statement:

.. code-block:: python

   log Transfer(msg.sender, receiver, amount)

The order and types of arguments given must match the order of arguments used when declaring the event.

Listening for Events
====================

You can filter by the indexed topics to narrow down your search when listening to events.

.. code-block:: python

    for log in token.Approval.range(chain.blocks.height, search_topics={"spender": user}):
        print(log.event_arguments)
