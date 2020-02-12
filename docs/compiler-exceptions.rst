.. index:: compiling, compiler, InvalidTypeException, common, exceptions, StructureException, ConstancyViolationException,
NonPayableViolationException, InvalidLiteralException, TypeMismatchException, EventDeclarationException, VersionException
SyntaxException, ArrayIndexException, ZeroDivisionException, EvmVersionException, CompilerPanic, VariableDeclarationException

Compiler Exceptions
*******************

.. _exceptions-common::

Common Compiler Exceptions
==========================

These are examples of the more common compiling exception errors that you could see when
compiling a ``vyper`` file for deployment on the Ethereum Virtual Machine.

.. _exceptions-InvalidExceptionType::

InvalidTypeException
********************

.. code-block:: python3

    bids: map(address, Bid[128])
    bidCounts: map(adddress, int128)

The variable type ''address'' is misspelled.  Any word that is not a reserved word, and declares a variable type will 
return this error.

.. code-block:: bash

    $ vyper blind_auction.vy 
    Error compiling: blind.auction.vy 
    /usr/lib/python3/dist-packages/apport/report.py:13: DeprecationWarning: the imp module is deprecated in favour of importlib; see the module's documentation for alternative uses
    import fnmatch, glob, traceback, errno, sys, atexit, locale, imp
    vyper.exceptions.InvalidTypeException: line 28:15 Invalid base type: adddress
         27 bids: map(address, Bid[128])
    ---> 28 bidCounts: map(adddress, int128)
-----------------------^
         29

The terminal returns a compiling error warning.  Reading the entire warning is critical to understanding exacly what
is causing the error.  The message displays the line numbers that contain the error.  In this example ''map(_KeyType, _ValueType)''
cannot compile because the type ''address'' is mispelled.

.. _exceptions-variableDeclaration::

VariableDeclarationException
****************************

.. code-block:: python3

    # Final auction state
    highestBid: public(wei_value)
    highestBidder: public(address)
    .
    .
    @private
    def placeBid(bidder: address, value: wei_value) -> bool:
    # If bid is less than highest bid, bid fails
    **if (value <= self.highstBid):**
        return False

''VariableDeclarationException'' is a compiling error in which a variable is being used that has not been declared.

.. code-block:: bash

    $ vyper blind_auction.vy
    Error compiling: blind_auction.vy
    /usr/lib/python3/dist-packages/apport/report.py:13: DeprecationWarning: the imp module is deprecated in favour of importlib; see the module's documentation for alternative uses
    import fnmatch, glob, traceback, errno, sys, atexit, locale, imp
    vyper.exceptions.VariableDeclarationException: line 79:17 Persistent variable undeclared: highstBid
         78     # If bid is less than highest bid, bid fails
    **---> 79     if (value <= self.highstBid):**
    ------------------------^
         80         return False

''self.highestBid'' is using a misspelled modified version of the public variable ''highestBidder''.

.. _exceptions-functionDeclaration::

FunctionDeclarationException
****************************

:: code-block:: python3

    struct Bid:
      blindedBid: bytes32
      deposit: wei_value
    .
    .
    .
    @public
    @payable
    **def pendingReturns(_blindedBid: bytes32):**
    # Check if bidding period is still open
    assert block.timestamp < self.biddingEnd

    # Check that payer hasn't already placed maximum number of bids
    numBids: int128 = self.bidCounts[msg.sender]
    assert numBids < MAX_BIDS

    # Add bid to mapping of all bids
        self.bids[msg.sender][numBids] = Bid({
        blindedBid: _blindedBid,
        deposit: msg.value
        })
        self.bidCounts[msg.sender] += 1
    .
    .
    .
    **pendingReturns: map(address, wei_value)**

''FunctionDeclarationException'' happens when a function name is used for two different functions or when a reserved word 
is used to name a function.

.. code-block:: bash

    $ vyper blind_auction.vy
    Error compiling: blind_auction.vy
    /usr/lib/python3/dist-packages/apport/report.py:13: DeprecationWarning: the imp module is deprecated in favour of importlib; see the module's documentation for alternative uses
    import fnmatch, glob, traceback, errno, sys, atexit, locale, imp
    vyper.exceptions.FunctionDeclarationException: Function name shadowing a variable name: pendingReturns

The warning generated in the terminal does not specify any line numbers.  ''pendingReturns'' is named as the identifier
used incorrectly to declare the function throwing the error.  

.. exceptions-StructureException::

StructureException
******************

.. code-block:: python3

    # Transfer funds to beneficiary
    send(self.beneficiary, self.highestBid)

    ,,,

The inclusion of punctuation that is syntactically incorrect and not a part of the normal vyper flow will throw a 
''StructureException''.

.. code-block:: bash

    vyper.exceptions.StructureException: line 181:0 Invalid top-level statement
         180
    ---> 181 '''
    ---------^
         182  
The terminal displays the line number and points directly to the problem.

.. exceptions-ConstancyViolationException::

ConstancyViolationException
***************************

This exception occurs when a variable or function that is returning a constant has another instance that is trying
to change the value.


.. exceptions-TypeMismatchException::

TypeMismatchException
*********************

.. code-block:: python3

    chain.id='hello':

''chain.id'' is of the uint256 type but this assignment is a string, therefore a type mismatch.  The terminal output
will point out the line of code containing the error.

.. exceptions-EventDeclarationException::

EventDeclarationException
*************************

This exception will occur when the identifier used to declare an event is in conflict with a reserved word
or previously declared structure with the same name.  The terminal output will state the line which contains the error.


.. exceptions-VersionException::

VersionException
****************

.. code-block:: python3

    @version 0.1.0b13

This exception will happen when a version pragma is being compiled with a future compiler.  Version pragma
declaration should be the first line of the file.


.. exceptions-SyntaxException::

SyntaxException
***************

.. code-block:: python3

    struct Bid:
        blindedBid bytes32
        deposit: wei_value

    A syntax error is thrown in the declaration of this ''struct'' variable.

.. code-block:: bash

 $ vyper blind_auction.vy
    vyper.exceptions.PythonSyntaxException: line 4:20 SyntaxError: invalid syntax
         3 struct Bid:
    ---> 4   blindedBid bytes32
    ---------------------------^
         5   deposit: wei_value

The terminal output of a sytnax error will generally show exactly where it happened.  In this case there is a semi
colon missing after ''blindedBid'' in the declaration of the struct.

.. exceptions-ArrayIndexException::

ArrayIndexException
*******************

This exception will occur when an invalid index number of an array is referenced.  The terminal will point out the line 
which contains the error.


.. exceptions-ZeroDivisionException::

ZeroDivisionException
*********************

This exception will occur when a divide by zero or ''modulo'' zero situation arises.  The terminal will point out the line 
which contains the error.


.. exceptions-EMVVersionException::

EvmVersionException
*******************

.. code-block:: python3

    {
        "settings": {
            "evmVersion": "[VERSION]"
        }
    }

Default version is ''istanbul''.  Other version choices include ''byzantium'', ''constantinople'', and ''petersburg''.  This
exception will occur when the compiler version is not compatible with the EVM version declared in the code.


.. exceptions-CompilerPanicException::

CompilerPanic
*************

.. code-block:: python3

    $ vyper v.vy 
    Error compiling: v.vy
    vyper.exceptions.CompilerPanic: Number of times repeated must be a constant nonzero positive integer: 0 Please create an issue.
A compiler panic error indicates that there is a problem internally to the compiler and an issue should be reported right 
away on the Vyper Github page.  Follow this link and open a new issue if you are experiencing this error 
'<https://github.com/vyperlang/vyper/issues>'_

.. exceptions-contributing::

Contributing
************

Documentation is one of the places where the community can benefit the most from past mistakes and failure.  
If an error is encountered that is rare or is not included within these exception, taking a moment to document
it here will help many others down the road.  You can find more information about 'Contributing'_ here
