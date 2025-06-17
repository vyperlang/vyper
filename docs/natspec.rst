.. _natspec:

NatSpec Metadata
################

Vyper contracts can use a special form of docstring to provide rich documentation for functions, return variables and more. This special form is named the Ethereum Natural Language Specification Format (NatSpec).

This documentation is segmented into developer-focused messages and end-user-facing messages. These messages may be shown to the end user (the human) at the time that they will interact with the contract (i.e. sign a transaction).

Example
=======

Vyper supports structured documentation for contracts and external functions using the doxygen notation format.

.. note::

    The compiler does not parse docstrings of internal functions. You are welcome to NatSpec in comments for internal functions, however they are not processed or included in the compiler output.


.. code-block:: vyper

    """
    @title A simulator for Bug Bunny, the most famous Rabbit
    @license MIT
    @author Warned Bros
    @notice You can use this contract for only the most basic simulation
    @dev
        Simply chewing a carrot does not count, carrots must pass
        the throat to be considered eaten
    """

    @external
    @payable
    def doesEat(food: string[30], qty: uint256) -> bool:
        """
        @notice Determine if Bugs will accept `qty` of `food` to eat
        @dev Compares the entire string and does not rely on a hash
        @param food The name of a food to evaluate (in English)
        @param qty The number of food items to evaluate
        @return True if Bugs will eat it, False otherwise
        """

Tags
====

All tags are optional. The following table explains the purpose of each NatSpec tag and where it may be used:

=============== ============================================ ==================
Tag             Description                                  Context
=============== ============================================ ==================
``@title``      Title that describes the contract            contract
``@license``    License of the contract                      contract
``@author``     Name of the author                           contract, function
``@notice``     Explain to an end user what this does        contract, function
``@dev``        Explain to a developer any extra details     contract, function
``@param``      Documents a single parameter                 function
``@return``     Documents one or all return variable(s)      function
``@custom:...`` Custom tag, semantics is application-defined contract, function
=============== ============================================ ==================

Some rules / restrictions:

1. A single tag description may span multiple lines. All whitespace between lines is interpreted as a single space.
2. If a docstring is included with no NatSpec tags, it is interpreted as a ``@notice``.
3. Each use of ``@param`` must be followed by the name of an input argument. Including invalid or duplicate argument names raises a :func:`NatSpecSyntaxException<NatSpecSyntaxException>`.
4. The preferred use of ``@return`` is one entry for each output value, however you may also use it once for all outputs. Including more ``@return`` values than output values raises a :func:`NatSpecSyntaxException<NatSpecSyntaxException>`.

Documentation Output
====================

When parsed by the compiler, documentation such as the one from the above example will produce two different JSON outputs. One is meant to be consumed by the end user as a notice when a function is executed and the other to be used by the developer.

If the above contract is saved as ``carrots.vy`` then you can generate the documentation using:

.. code:: shell

   $ vyper -f userdoc,devdoc carrots.vy

User Documentation
------------------

The above documentation will produce the following user documentation JSON as output:

.. code-block:: json

    {
      "methods": {
        "doesEat(string,uint256)": {
          "notice": "Determine if Bugs will accept `qty` of `food` to eat"
        }
      },
      "notice": "You can use this contract for only the most basic simulation"
    }

Note that the key by which to find the methods is the function's
canonical signature as defined in the contract ABI, not simply the function's
name.

Developer Documentation
-----------------------

Apart from the user documentation file, a developer documentation JSON
file should also be produced and should look like this:

.. code-block:: json

    {
      "author": "Warned Bros",
      "license": "MIT",
      "details": "Simply chewing a carrot does not count, carrots must pass the throat to be considered eaten",
      "methods": {
        "doesEat(string,uint256)": {
          "details" : "Compares the entire string and does not rely on a hash",
          "params": {
            "food": "The name of a food to evaluate (in English)",
            "qty": "The number of food items to evaluate"
          },
          "returns": {
            "_0": "True if Bugs will eat it, False otherwise"
          }
        }
      },
      "title" : "A simulator for Bug Bunny, the most famous Rabbit"
    }
