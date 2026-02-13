.. index:: voting, ballot

Voting
******

.. _voting:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

In this contract, we will implement a system for participants to vote on a list
of proposals. The chairperson of the contract will be able to give each
participant the right to vote, and each participant may choose to vote, or
delegate their vote to another voter. Finally, a winning proposal will be
determined upon calling the ``winningProposal()`` method, which iterates through
all the proposals and returns the one with the greatest number of votes.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :linenos:

As we can see, this is the contract of moderate length which we will dissect
section by section. Let's begin!

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 3
  :lines: 3-28

The variable ``voters`` is initialized as a mapping where the key is
the voter's public address and the value is a struct describing the
voter's properties: ``weight``, ``voted``, ``delegate``, and ``vote``, along
with their respective data types.

Similarly, the ``proposals`` variable is initialized as a ``public`` mapping
with ``int128`` as the key's datatype and a struct to represent each proposal
with the properties ``name`` and ``voteCount``. Like our last example, we can
access any value by key'ing into the mapping with a number just as one would
with an index in an array.

Then, ``voterCount`` and ``chairperson`` are initialized as ``public`` with
their respective datatypes.

Let's move onto the constructor.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 54
  :lines: 54-64

In the constructor, we hard-coded the contract to accept an
array argument of exactly two proposal names of type ``bytes32`` for the contracts
initialization. Because upon initialization, the ``__init__()`` method is called
by the contract creator, we have access to the contract creator's address with
``msg.sender`` and store it in the contract variable ``self.chairperson``. We
also initialize the contract variable ``self.voterCount`` to zero to initially
represent the number of votes allowed. This value will be incremented as each
participant in the contract is given the right to vote by the method
``giveRightToVote()``, which we will explore next. We loop through the two
proposals from the argument and insert them into ``proposals`` mapping with
their respective index in the original array as its key.

Now that the initial setup is done, let's take a look at the functionality.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 66
  :lines: 66-77

.. note:: Throughout this contract, we use a pattern where ``@external`` functions return data from ``@internal`` functions that have the same name prepended with an underscore. This is because Vyper does not allow calls between external functions within the same contract. The internal function handles the logic and allows internal access, while the external function acts as a getter to allow external viewing.

We need a way to control who has the ability to vote. The method
``giveRightToVote()`` is a method callable by only the chairperson by taking
a voter address and granting it the right to vote by setting the voter's
``weight`` property. We sequentially check for 3 conditions using ``assert``.
The ``assert not`` statement will check for falsy boolean values -
in this case, we want to know that the voter has not already voted. To represent
voting power, we will set their ``weight`` to ``1`` and we will keep track of the
total number of voters by incrementing ``voterCount``.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 121
  :lines: 121-137

In the method ``delegate``, firstly, we check to see that ``msg.sender`` has not
already voted and secondly, that the target delegate and the ``msg.sender`` are
not the same. Voters shouldn't be able to delegate votes to themselves. We then
mark the ``msg.sender`` as having voted and record the delegate address. Finally,
we call ``_forwardWeight()`` which handles following the chain of delegation and
transferring voting weight appropriately.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 139
  :lines: 139-153

Now, let's take a look at the logic inside the ``vote()`` method, which is
surprisingly simple. The method takes the key of the proposal in the ``proposals``
mapping as an argument, check that the method caller had not already voted,
sets the voter's ``vote`` property to the proposal key, and increments the
proposals ``voteCount`` by the voter's ``weight``.

With all the basic functionality complete, what's left is simply returning
the winning proposal. To do this, we have two methods: ``winningProposal()``,
which returns the key of the proposal, and ``winnerName()``, returning the
name of the proposal. Notice the ``@view`` decorator on these two methods.
The ``@view`` decorator indicates that these functions only read contract state
and do not modify it. When called externally (not as part of a transaction),
view functions do not cost gas.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 155
  :lines: 155-171

The ``_winningProposal()`` method returns the key of proposal in the ``proposals``
mapping. We will keep track of greatest number of votes and the winning
proposal with the variables ``winningVoteCount`` and ``winningProposal``,
respectively by looping through all the proposals.

``winningProposal()`` is an external function allowing access to ``_winningProposal()``.

.. literalinclude:: ../../examples/voting/ballot.vy
  :language: vyper
  :lineno-start: 174
  :lines: 174-180

And finally, the ``winnerName()`` method returns the name of the proposal by
key'ing into the ``proposals`` mapping with the return result of the
``winningProposal()`` method.

And there you have it - a voting contract. Currently, many transactions
are needed to assign the rights to vote to all participants. As an exercise,
can we try to optimize this?
