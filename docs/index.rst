.. Viper documentation master file, created by
   sphinx-quickstart on Wed Jul 26 11:18:29 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Viper's documentation!
=================================
Viper is an experimental programming language that aims to provide the following features:

* Bounds and overflow checking, both on array accesses and on arithmetic
* Support for signed integers and decimal fixed point numbers
* Decidability - it's possible to compute a precise upper bound on the gas consumption of any function call
* Strong typing, including support for units (eg. timestamp, timedelta, seconds, wei, wei per second, meters per second squared)
* Maximally small and understandable compiler code size
* Limited support for pure functions - anything marked constant is NOT allowed to change the state

Compatibility-breaking change log

* **2017.07.25**: the `def foo() -> num(const): ...` syntax no longer works; you now need to do `def foo() -> num: ...` with a `@constant` decorator on the previous line.
* **2017.07.25**: functions without a `@payable` decorator now fail when called with nonzero wei.
* **2017.07.25**: a function can only call functions that are declared above it (that is, A can call B only if B appears earlier in the code than A does). This was introduced to prevent infinite looping through recursion.


.. toctree::
    :maxdepth: 2

    installing-viper.rst
    viper-in-depth.rst
    contributing.rst
    frequently-asked-questions.rst

