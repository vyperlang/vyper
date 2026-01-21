.. index:: name registry

Name Registry
*************

.. _name_registry:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

A minimal name registry that maps names to addresses. Once a name is registered,
it cannot be changed.

.. literalinclude:: ../../examples/name_registry/name_registry.vy
  :language: vyper
  :linenos:

This pattern is useful for:

- ENS-like name services
- Service discovery
- Any first-come-first-served registration system

The ``assert self.registry[name] == empty(address)`` check ensures names cannot be overwritten.
