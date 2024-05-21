.. _style-guide:

Style Guide
###########

This document outlines the code style, project structure and practices followed by the Vyper development team.

.. note::

    Portions of the current codebase do not adhere to this style guide. We are in the process of a large-scale refactor and this guide is intended to outline the structure and best practices *during and beyond* this refactor. Refactored code and added functionality **must** adhere to this guide. Bugfixes and modifications to existing functionality **may** adopt the same style as the related code.

Project Organization
====================

    * Each subdirectory within Vyper **should** be a self-contained package representing a single pass of the compiler or other logical component.
    * Functionality intended to be called from modules outside of a package **must** be exposed within the base ``__init__.py``. All other functionality is for internal use only.
    * It **should** be possible to remove any package and replace it with another that exposes the same API, without breaking functionality in other packages.

Code Style
==========

All code **must** conform to the `PEP 8 style guide <https://www.python.org/dev/peps/pep-0008>`_ with the following exceptions:

    * Maximum line length of 100

We handle code formatting with `black <https://github.com/psf/black>`_ with the line-length option set to 80. This ensures a consistent style across the project and saves time by not having to be opinionated.

Naming Conventions
------------------

Names **must** adhere to `PEP 8 naming conventions <https://www.python.org/dev/peps/pep-0008/#prescriptive-naming-conventions>`_:

    * **Modules** have short, all-lowercase names. Underscores can be used in the module name if it improves readability.
    * **Class names** use the CapWords convention.
    * **Exceptions** follow the same conventions as other classes.
    * **Function** names are lowercase, with words separated by underscores when it improves readability.
    * **Method** names and **instance** variables follow the same conventions as functions.
    * **Constants** use all capital letters with underscores separating words.

Leading Underscores
*******************

A single leading underscore marks an object as private.

    * Classes and functions with one leading underscore are only used in the module where they are declared. They **must not** be imported.
    * Class attributes and methods with one leading underscore **must** only be accessed by methods within the same class.

Booleans
********

    * Boolean values **should** be prefixed with ``is_``.
    * Booleans **must not** represent *negative* properties, (e.g. ``is_not_set``). This can result in double-negative evaluations which are not intuitive for readers.
    * Methods that return a single boolean **should** use the :py:class:`@property<property>` decorator.

Methods
*******

The following conventions **should** be used when naming functions or methods. Consistent naming provides logical consistency throughout the codebase and makes it easier for future readers to understand what a method does (and does not) do.

    * ``get_``: For simple data retrieval without any side effects.
    * ``fetch_``: For retreivals that may have some sort of side effect.
    * ``build_``: For creation of a new object that is derived from some other data.
    * ``set_``: For adding a new value or modifying an existing one within an object.
    * ``add_``: For adding a new attribute or other value to an object. Raises an exception if the value already exists.
    * ``replace_``: For mutating an object. Should return ``None`` on success or raise an exception if something is wrong.
    * ``compare_``: For comparing values. Returns ``True`` or ``False``, does not raise an exception.
    * ``validate_``: Returns ``None`` or raises an exception if something is wrong.
    * ``from_``: For class methods that instantiate an object based on the given input data.

For other functionality, choose names that clearly communicate intent without being overly verbose. Focus on *what* the method does, not on *how* the method does it.

Imports
-------

Import sequencing is handled with `isort <https://github.com/timothycrosley/isort>`_. We follow these additional rules:

Standard Library Imports
************************

Standard libraries **should** be imported absolutely and without aliasing. Importing the library aids readability, as other users may be familiar with that library.

    .. code-block:: python

        # Good
        import os
        os.stat('.')

        # Bad
        from os import stat
        stat('.')

Internal Imports
****************

Internal imports are those between two modules inside the same Vyper package.

    * Internal imports **may** use either ``import`` or ``from ..`` syntax. The imported value **should** be a module, not an object. Importing modules instead of objects avoids circular dependency issues.
    * Internal imports **may** be aliased where it aids readability.
    * Internal imports **must** use absolute paths. Relative imports cause issues when the module is moved.

    .. code-block:: python

        # Good
        import vyper.ast.nodes as nodes
        from vyper.ast import nodes

        # Bad, `get_node` is a function
        from vyper.ast.nodes import get_node

        # Bad, do not use relative import paths
        from . import nodes

Cross-Package Imports
*********************

Cross-package imports are imports between one Vyper package and another.

    * Cross-package imports **must not** request anything beyond the root namespace of the target package.
    * Cross-package imports **may** be aliased where it aids readability.
    * Cross-package imports **may** use ``from [module] import [package]`` syntax.

    .. code-block:: python

        # Good
        from vyper.ast import fold
        from vyper import ast as vy_ast

        # Bad, do not import beyond the root namespace
        from vyper.ast.annotation import annotate_python_ast

Exceptions
----------

We use :ref:`custom exception classes <compiler-exceptions>` to indicate what has gone wrong during compilation.

    * All raised exceptions **must** use an exception class that appropriately describes what has gone wrong. When none fits, or when using a single exception class for an overly broad range of errors, consider creating a new class.
    * Builtin Python exceptions **must not** be raised intentionally. An unhandled builtin exception indicates a bug in the codebase.
    * Use :func:`CompilerPanic<CompilerPanic>` for errors that are not caused by the user.

Strings
-------

Strings substitutions **should** be performed via `formatted string literals <https://docs.python.org/3/reference/lexical_analysis.html#formatted-string-literals>`_ rather than the ``str.format`` method or other techniques.

Type Annotations
----------------

    * All publicly exposed classes and methods **should** include `PEP 484 <https://www.python.org/dev/peps/pep-0484/>`_ annotations for all arguments and return values.
    * Type annotations **should** be included directly in the source. `Stub files <https://www.python.org/dev/peps/pep-0484/#stub-files>`_ **may** be used where there is a valid reason. Source files using stubs **must** still be annotated to aid readability.
    * Internal methods **should** include type annotations.

Tests
=====

We use the `pytest <https://docs.pytest.org/en/latest/>`_ framework for testing, and :ref:`eth-tester<testing-contracts-ethtester>` for our local development chain.

Best Practices
--------------

    * ``pytest`` functionality **should not** be imported with ``from ...`` style syntax, particularly :func:`pytest.raises<pytest.raises>`. Importing the library itself aids readability.
    * Tests **must not** be interdependent. We use ``xdist`` to execute tests in parallel. You **cannot** rely on which order tests will execute in, or that two tests will execute in the same process.
    * Test cases **should** be designed with a minimalistic approach. Each test should verify a single behavior. A good test is one with few assertions, and where it is immediately obvious exactly what is being tested.
    * Where logical, tests **should** be `parametrized <https://docs.pytest.org/en/latest/parametrize.html>`_ or use `property-based <https://hypothesis.works/>`_ testing.
    * Tests **must not** involve mocking.

Directory Structure
-------------------

Where possible, the test suite **should** copy the structure of main Vyper package. For example, test cases for ``vyper/context/types/`` should exist at ``tests/context/types/``.

Filenames
---------

Test files **must** use the following naming conventions:

    * ``test_[module].py``: When all tests for a module are contained in a single file.
    * ``test_[module]_[functionality].py``: When tests for a module are split across multiple files.

Fixtures
--------

    * Fixtures **should** be stored in ``conftest.py`` rather than the test file itself.
    * ``conftest.py`` files **must not** exist more than one subdirectory beyond the initial ``tests/`` directory.
    * The functionality of a fixture **must** be fully documented, either via docstrings or comments.

Documentation
=============

It is important to maintain comprehensive and up-to-date documentation for the Vyper language.

    * Documentation **must** accurately reflect the current state of the master branch on Github.
    * New functionality **must not** be added without corresponding documentation updates.

Writing Style
-------------

We use imperative, present tense to describe APIs: “return” not “returns”. One way to test if we have it right is to complete the following sentence:

    "If we call this API it will: ..."

For narrative style documentation, we prefer the use of first-person "we" form over second-person "you" form.

Additionally, we **recommend** the following best practices when writing documentation:

    * Use terms consistently.
    * Avoid ambiguous pronouns.
    * Eliminate unneeded words.
    * Establish key points at the start of a document.
    * Focus each paragraph on a single topic.
    * Focus each sentence on a single idea.
    * Use a numbered list when order is important and a bulleted list when order is irrelevant.
    * Introduce lists and tables appropriately.

Google's `technical writing courses <https://developers.google.com/tech-writing>`_ are a valuable resource. We recommend reviewing them before any significant documentation work.

API Directives
--------------

    * All API documentation **must** use standard Python `directives <https://www.sphinx-doc.org/en/master/usage/restructuredtext/domains.html#the-python-domain>`_.
    * Where possible, references to syntax **should** use appropriate `Python roles <https://www.sphinx-doc.org/en/master/usage/restructuredtext/domains.html#cross-referencing-syntax>`_.
    * External references **may** use `intersphinx roles <https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html>`_.

Headers
-------

    * Each documentation section **must** begin with a `label <https://www.sphinx-doc.org/en/stable/usage/restructuredtext/roles.html#cross-referencing-arbitrary-locations>`_ of the same name as the filename for that section. For example, this section's filename is ``style-guide.rst``, so the RST opens with a label ``_style-guide``.
    * Section headers **should** use the following sequence, from top to bottom: ``#``, ``=``, ``-``, ``*``, ``^``.

Internal Documentation
======================

Internal documentation is vital to aid other contributors in understanding the layout of the Vyper codebase.

We handle internal documentation in the following ways:

    * A ``README.md`` **must** be included in each first-level subdirectory of the Vyper package. The readme explain the purpose, organization and control flow of the subdirectory.
    * All publicly exposed classes and methods **must** include detailed docstrings.
    * Internal methods **should** include docstrings, or at minimum comments.
    * Any code that may be considered "clever" or "magic" **must** include comments explaining exactly what is happening.

Docstrings **should** be formatted according to the `NumPy docstring style <https://numpydoc.readthedocs.io/en/latest/format.html>`_.

Commit Messages
===============

Contributors **should** adhere to the following standards and best practices when making commits to be merged into the Vyper codebase.

Maintainers  **may** request a rebase, or choose to squash merge pull requests that do not follow these standards.

Conventional Commits
--------------------

Commit messages **should** adhere to the `Conventional Commits <https://www.conventionalcommits.org/>`_ standard. A conventional commit message is structured as follows:

::

    <type>[optional scope]: <description>

    [optional body]

    [optional footer]

The commit contains the following elements, to communicate intent to the consumers of your library:

    * **fix**: a commit of the *type* ``fix`` patches a bug in your codebase (this correlates with ``PATCH`` in semantic versioning).
    * **feat**: a commit of the *type* ``feat`` introduces a new feature to the codebase (this correlates with ``MINOR`` in semantic versioning).
    * **BREAKING CHANGE**: a commit that has the text ``BREAKING CHANGE:`` at the beginning of its optional body or footer section introduces a breaking API change (correlating with ``MAJOR`` in semantic versioning). A BREAKING CHANGE can be part of commits of any *type*.

The use of commit types other than ``fix:`` and ``feat:`` is recommended. For example: ``docs:``, ``style:``, ``refactor:``, ``test:``, ``chore:``, or ``improvement:``. These tags are not mandated by the specification and have no implicit effect in semantic versioning.

Best Practices
--------------

We **recommend** the following best practices for commit messages (taken from `How To Write a Commit Message <https://chris.beams.io/posts/git-commit/>`_):

    * Limit the subject line to 50 characters.
    * Use imperative, present tense in the subject line.
    * Capitalize the subject line.
    * Do not end the subject line with a period.
    * Separate the subject from the body with a blank line.
    * Wrap the body at 72 characters.
    * Use the body to explain what and why vs. how.

Here's an example commit message adhering to the above practices::

    Summarize changes in around 50 characters or less

    More detailed explanatory text, if necessary. Wrap it to about 72
    characters or so. In some contexts, the first line is treated as the
    subject of the commit and the rest of the text as the body. The
    blank line separating the summary from the body is critical (unless
    you omit the body entirely); various tools like `log`, `shortlog`
    and `rebase` can get confused if you run the two together.

    Explain the problem that this commit is solving. Focus on why you
    are making this change as opposed to how (the code explains that).
    Are there side effects or other unintuitive consequences of this
    change? Here's the place to explain them.

    Further paragraphs come after blank lines.

     - Bullet points are okay, too

     - Typically a hyphen or asterisk is used for the bullet, preceded
       by a single space, with blank lines in between, but conventions
       vary here

    If you use an issue tracker, put references to them at the bottom,
    like this:

    Resolves: #XXX
    See also: #XXY, #XXXZ
