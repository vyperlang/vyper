.. _versioning:

Vyper Versioning Guideline
##########################

Motivation
==========

Vyper has different groups that are considered "users":

- Smart Contract Developers (using Vyper to write smart contracts)
- Package Integrators (integerating Vyper package or CLI into their tools)
- Security Professionals (aware of the status of various Vyper features and security issues)

Each set of users must understand which changes to the compiler may require their
involvement, and how these changes may impact their use of the compiler.
This guide defines what scope each compiler change may have, it's potential impact based
on the type of user, so that users can stay informed about the progress of Vyper.

This guide was adapted from `semantic versioning <https://semver.org/>`_.

Smart Contract Developers
-------------------------

Vyper's "public API" for developers is the language grammar.
Changes to the grammar cannot be made in a backwards incompatible way without changing Major
versions (e.g. 1.x -> 2.x).
Minor version updates may add new features or fix a ``moderate`` or ``severe`` vulnerability,
and these will be detailed in the Release Notes for that release.
Patch version releases will be released to fix documentation issues, usage bugs,
and ``minor`` or ``informational`` vulnerabilities found in Vyper.

Package Integrators
-------------------

The Vyper package and CLI utilities has a fairly well-defined public API, which is contained of
exported features in Vyper's `exported package <https://github.com/vyperlang/vyper/blob/master/vyper/__init__.py>`_,
top level modules under the package, and all CLI scripts.
Major releases of Vyper have no special meaning to package integrators,
and should be considered similar to a Minor release.
Minor releases may change the features or functionality offered by the package and CLI scripts in a
backwards-incompatible way that requires attention from the integrator.
Patch releases should only update error messages and documentation issues.

Security Professionals
----------------------

Security professionals broadly have similar needs to Smart Contract Developers as they work
closely with them, but they have additional needs that should be accommodated.
Major releases will have an audit performed prior to release (e.g. ``x.0.0`` releases) and all
``moderate`` or ``severe`` vulnerabilities will be addressed that are reported in the audit report.
``minor`` or ``informational`` vulnerabilities *should* be addressed as well, although this may be
left up to the maintainers of Vyper to decide.
Minor releases are required to fix a ``moderate`` or ``severe`` vulnerability,
but a ``minor`` or ``informational`` vulnerability can be fixed in Patch releases,
alongside documentation updates.
The details of all reported vulnerabilities will be published
`here <https://github.com/vyperlang/vyper/security/advisories?state=published>`_
alongside their corresponding fix in the :ref:`Release Notes<release-notes>`.

Vyper *Next*
============

There can multiple branches of Major versions in process (often just 2),
and they represent fundamental breaking changes to the grammar,
requiring Developers to change their contracts to be compatible with the next version.
Work on new features that break compatibility with the existing grammar can be maintained on a
separate branch called ``next`` and represents the next Major release of Vyper
(provided in an unaudited state without Release Notes).
The work on the current branch will remain on the ``master`` branch with periodic new releases
using the process as mentioned above.
Any other branches of work outside of what is being tracked via ``master`` will use the
``-alpha.[release #]`` to denote WIP updates,
and ``-beta.[release #]`` to describe work that is eventually intended for release.
``-rc.[release #]`` will only be used to denote candidate builds prior to a Major release
(alongside a final audit report).
An audit will be solicited for ``-rc.1`` builds,
and subsequent releases *may* incorporate feedback during the audit.

Pull Requests
=============

Pull Requests can be opened against either ``master`` or ``next`` branch, depending on their content.
Changes that would increment a Minor or Patch release should target ``master``,
whereas changes to syntax (as detailed above) should be opened against ``next``.
The ``next`` branch will be periodically rebased against the ``master`` branch to pull in changes made
that were added to the latest supported version of Vyper.

Communication
=============

Major and Minor versions should be communicated on appropriate communications channels to end users,
and Patch updates will usually not be discussed, unless there is a relevant reason to do so.
