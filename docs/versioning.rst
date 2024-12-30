.. _versioning:

Vyper Versioning Guideline
##########################

Motivation
==========

Vyper has different groups that are considered "users":

- Smart Contract Developers (Developers)
- Package Integrators (Integrators)
- Security Professionals (Auditors)

Each set of users must understand which changes to the compiler may require their
attention, and how these changes may impact their use of the compiler.
This guide defines what scope each compiler change may have and its potential impact based
on the type of user, so that users can stay informed about the progress of Vyper.

+-------------+----------------------------------------------+
|    Group    |             How they use Vyper               |
+=============+==============================================+
| Developers  | Write smart contracts in Vyper               |
+-------------+----------------------------------------------+
| Integrators | Integrating Vyper package or CLI into tools  |
+-------------+----------------------------------------------+
| Auditors    | Aware of Vyper features and security issues  |
+-------------+----------------------------------------------+

A big part of Vyper's "public API" is the language grammar.
The syntax of the language is the main touchpoint all parties have with Vyper,
so it's important to discuss changes to the language from the viewpoint of dependability.
Users expect that all contracts written in an earlier version of Vyper will work seamlessly
with later versions, or that they will be reasonably informed when this isn't possible.
The Vyper package itself and its CLI utilities also has a fairly well-defined public API,
which consists of the available features in Vyper's
`exported package <https://github.com/vyperlang/vyper/blob/master/vyper/__init__.py>`_,
the top level modules under the package, and all CLI scripts.

Version Types
=============

This guide was adapted from `semantic versioning <https://semver.org/>`_.
It defines a format for version numbers that looks like ``MAJOR.MINOR.PATCH[-STAGE.DEVNUM]``.
We will periodically release updates according to this format, with the release decided via
the following guidelines.

Major Release ``X.0.0``
-----------------------

Changes to the grammar cannot be made in a backwards incompatible way without changing Major
versions (e.g. ``v1.x`` -> ``v2.x``).
It is to be expected that breaking changes to many features will occur when updating to a new Major release,
primarily for Developers that use Vyper to compile their contracts.
Major releases will have an audit performed prior to release (e.g. ``x.0.0`` releases) and all
``moderate`` or ``severe`` vulnerabilities will be addressed that are reported in the audit report.
``minor`` or ``informational`` vulnerabilities *should* be addressed as well, although this may be
left up to the maintainers of Vyper to decide.

+-------------+----------------------------------+
| Group       |               Look For           |
+=============+==================================+
| Developers  | Syntax deprecation, new features |
+-------------+----------------------------------+
| Integrators | No changes                       |
+-------------+----------------------------------+
| Auditors    | Audit report w/ resolved changes |
+-------------+----------------------------------+

Minor Release ``x.Y.0``
-----------------------

Minor version updates may add new features or fix a ``moderate`` or ``severe`` vulnerability,
and these will be detailed in the Release Notes for that release.
Minor releases may change the features or functionality offered by the package and CLI scripts in a
backwards-incompatible way that requires attention from an integrator.
Minor releases are required to fix a ``moderate`` or ``severe`` vulnerability,
but a ``minor`` or ``informational`` vulnerability can be fixed in Patch releases,
alongside documentation updates.

+-------------+------------------------------------+
| Group       |             Look For               |
+=============+====================================+
| Developers  | New features, security bug fixes   |
+-------------+------------------------------------+
| Integrators | Changes to external API            |
+-------------+------------------------------------+
| Auditors    | ``moderate`` or ``severe`` patches |
+-------------+------------------------------------+

Patch Release ``x.y.Z``
-----------------------

Patch version releases will be released to fix documentation issues, usage bugs,
and ``minor`` or ``informational`` vulnerabilities found in Vyper.
Patch releases should only update error messages and documentation issues
relating to its external API.

+-------------+----------------------------------------------+
| Group       |               Look For                       |
+=============+==============================================+
| Developers  | Doc updates, usage bug fixes, error messages |
+-------------+----------------------------------------------+
| Integrators | Doc updates, usage bug fixes, error messages |
+-------------+----------------------------------------------+
| Auditors    | ``minor`` or ``informational`` patches       |
+-------------+----------------------------------------------+

Vyper Security
--------------

As Vyper develops, it is very likely that we will encounter inconsistencies in how certain
language features can be used, and software bugs in the code the compiler generates.
Some of them may be quite serious, and can render a user's compiled contract vulnerable to
exploitation for financial gain.
As we become aware of these vulnerabilities, we will work according to our
`security policy <https://github.com/vyperlang/vyper/security/policy>`_ to resolve these issues,
and eventually will publish the details of all reported vulnerabilities
`here <https://github.com/vyperlang/vyper/security/advisories?state=published>`_.
Fixes for these issues will also be noted in the :ref:`Release Notes<release-notes>`.

Vyper *Next*
------------

There may be multiple Major versions in the process of development.
Work on new features that break compatibility with the existing grammar can
be maintained on a separate branch called ``next`` and represents the next
Major release of Vyper (provided in an unaudited state without Release Notes).
The work on the current branch will remain on the ``master`` branch with periodic
new releases using the process as mentioned above.

Any other branches of work outside of what is being tracked via ``master``
will use the ``-alpha.[release #]`` (Alpha) to denote WIP updates,
and ``-beta.[release #]`` (Beta) to describe work that is eventually intended for release.
``-rc.[release #]`` (Release Candidate) will only be used to denote candidate builds
prior to a Major release. An audit will be solicited for ``-rc.1`` builds,
and subsequent releases *may* incorporate feedback during the audit.
The last Release Candidate will become the next Major release,
and will be made available alongside the full audit report summarizing the findings.

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
