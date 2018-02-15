
*************
Event logging
*************

Like Solidity and other EVM languages, Vyper can log events to be caught and displayed by user interfaces.

Example of Logging
==================

This example is taken from the sample ERC20 contract and shows the basic flow of event logging.
::
    # Events of the token.
    Transfer: __log__({_from: indexed(address), _to: indexed(address), _value: num256})
    Approval: __log__({_owner: indexed(address), _spender: indexed(address), _value: num256})

    # Transfer some tokens from message sender to another address
    def transfer(_to: address, _amount: num(num256)) -> bool:

       ... Logic here to do the real work ...

       # All done, log the event for listeners
       log.Transfer(msg.sender, _to, convert(_amount, 'num256'))
::

Let's look at what this is doing. First, we declare two event types to log. The two events are similar in that they contain 
two indexed address fields. Indexed fields do not make up part of the event data itself, but can be searched by clients that
want to catch the event. Also, each event contains one single data field, in each case called _value. 
Because they are 
