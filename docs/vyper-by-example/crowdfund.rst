.. index:: crowdfund

Crowdfund
*********

.. _crowdfund:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

Now, let's explore a straightforward example for a crowdfunding contract where
prospective participants can contribute funds to a campaign. If the total
contribution to the campaign reaches or surpasses a predetermined funding goal,
the funds will be sent to the  beneficiary at the end of the campaign deadline.
Participants will be refunded their respective contributions if the total
funding does not reach its target goal.

.. literalinclude:: ../../examples/crowdfund.vy
  :language: vyper
  :linenos:

Most of this code should be relatively straightforward after going through our
previous examples. Let's dive right in.

.. literalinclude:: ../../examples/crowdfund.vy
  :language: vyper
  :lineno-start: 9
  :lines: 9-14

Like other examples, we begin by initiating our variables. Some variables like
``deadline``, ``goal`` and ``timelimit`` are declared with the ``public`` function,
making them readable by external callers. Variables without ``public`` are, by
default, private.

.. note::
  Unlike the existence of the function ``public()``, there is no equivalent
  ``private()`` function. Variables simply default to private if initiated
  without the ``public()`` function.

The ``funders`` variable is initiated as a mapping where the key is an address,
and the value is a number representing the contribution of each participant.
The ``beneficiary`` will be the final receiver of the funds
once the crowdfunding period is over—as determined by the ``deadline`` and
``timelimit`` variables. The ``goal`` variable is the target total contribution
of all participants.

.. literalinclude:: ../../examples/crowdfund.vy
  :language: vyper
  :lineno-start: 16
  :lines: 16-23

Our constructor function takes 3 arguments: the beneficiary's address, the goal
in wei value, and the difference in time from start to finish of the
crowdfunding. We initialize the arguments as contract variables with their
corresponding names. Additionally, a ``self.deadline`` is initialized to set
a definitive end time for the crowdfunding period.

Now let's take a look at how a person can participate in the crowdfund.

.. literalinclude:: ../../examples/crowdfund.vy
  :language: vyper
  :lineno-start: 25
  :lines: 25-32

Once again, we see the ``@payable`` decorator on a method, which allows a
person to send some ether along with a call to the method. In this case,
the ``participate()`` method accesses the sender's address with ``msg.sender``
and the corresponding amount sent with ``msg.value``. The contribution is added
to the ``funders`` HashMap, which maps each participant's address to their
total contribution amount.

.. literalinclude:: ../../examples/crowdfund.vy
  :language: vyper
  :lineno-start: 34
  :lines: 34-42

The ``finalize()`` method is used to complete the crowdfunding process. However,
to complete the crowdfunding, the method first checks to see if the crowdfunding
period is over and that the balance has reached/passed its set goal. If those
two conditions pass, the contract sends the collected funds to the beneficiary.

.. note::
  Notice that we have access to the total amount sent to the contract by
  calling ``self.balance``, a variable we never explicitly set. Similar to ``msg``
  and ``block``, ``self.balance`` is a built-in variable that's available in all
  Vyper contracts.

We can finalize the campaign if all goes well, but what happens if the
crowdfunding campaign isn't successful? We're going to need a way to refund
all the participants.

.. literalinclude:: ../../examples/crowdfund.vy
  :language: vyper
  :lineno-start: 44
  :lines: 44-54

In the ``refund()`` method, we first check that the crowdfunding period is
indeed over and that the total collected balance is less than the ``goal`` with
the  ``assert`` statement . If those two conditions pass, we let users get their
funds back using the withdraw pattern.
