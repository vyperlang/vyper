.. _release-notes:

Release Notes
#############

v0.1.0-beta.14
**************

Date released: 13-11-2019

Some of the bug and stability fixes:

- Mucho Documentation and Example cleanup!
- Python 3.8 support (`#1678 <https://github.com/ethereum/vyper/pull/1678>`_)
- Disallow scientific notation in literals, which previously parsed incorrectly (`#1681 <https://github.com/ethereum/vyper/pull/1681>`_)
- Add implicit rewrite rule for ``bytes[32]`` -> ``bytes32`` (`#1718 <https://github.com/ethereum/vyper/pull/1718>`_)
- Support ``bytes32`` in ``raw_log`` (`#1719 <https://github.com/ethereum/vyper/pull/1719>`_)
- Fixed EOF parsing bug (`#1720 <https://github.com/ethereum/vyper/pull/1720>`_)
- Cleaned up arithmetic expressions (`#1661 <https://github.com/ethereum/vyper/pull/1661>`_)
- Fixed off-by-one in check for homogeneous list element types (`#1673 <https://github.com/ethereum/vyper/pull/1673>`_)
- Fixed stack valency issues in if and for statements (`#1665 <https://github.com/ethereum/vyper/pull/1665>`_)
- Prevent overflow when using ``sqrt`` on certain datatypes (`#1679 <https://github.com/ethereum/vyper/pull/1679>`_)
- Prevent shadowing of internal variables (`#1601 <https://github.com/ethereum/vyper/pull/1601>`_)
- Reject unary substraction on unsigned types  (`#1638 <https://github.com/ethereum/vyper/pull/1638>`_)
- Disallow ``orelse`` syntax in ``for`` loops (`#1633 <https://github.com/ethereum/vyper/pull/1633>`_)
- Increased clarity and efficiency of zero-padding (`#1605 <https://github.com/ethereum/vyper/pull/1605>`_)

v0.1.0-beta.13
**************

Date released: 27-09-2019

The following VIPs were implemented for Beta 13:

- Add `vyper-json` compilation mode (VIP `#1520 <https://github.com/ethereum/vyper/issues/1520>`_)
- Environment variables and constants can now be used as default parameters (VIP `#1525 <https://github.com/ethereum/vyper/issues/1525>`_)
- Require unitialized memory be set on creation (VIP `#1493 <https://github.com/ethereum/vyper/issues/1493>`_)

Some of the bug and stability fixes:

- Type check for default params and arrays (`#1596 <https://github.com/ethereum/vyper/pull/1596>`_)
- Fixed bug when using assertions inside for loops (`#1619 <https://github.com/ethereum/vyper/pull/1619>`_)
- Fixed zero padding error for ABI encoder (`#1611 <https://github.com/ethereum/vyper/pull/1611>`_)
- Check `calldatasize` before `calldataload` for function selector (`#1606 <https://github.com/ethereum/vyper/pull/1606>`_)

v0.1.0-beta.12
**************

Date released: 27-08-2019

The following VIPs were implemented for Beta 12:

- Support for relative imports (VIP `#1367 <https://github.com/ethereum/vyper/issues/1367>`_)
- Restricted use of environment variables in private functions (VIP `#1199 <https://github.com/ethereum/vyper/issues/1199>`_)

Some of the bug and stability fixes:

- ``@nonreentrant``/``@constant`` logical inconsistency (`#1544 <https://github.com/ethereum/vyper/issues/1544>`_)
- Struct passthrough issue (`#1551 <https://github.com/ethereum/vyper/issues/1551>`_)
- Private underflow issue (`#1470 <https://github.com/ethereum/vyper/pull/1470>`_)
- Constancy check issue (`#1480 <https://github.com/ethereum/vyper/pull/1480>`_)
- Prevent use of conflicting method IDs (`#1530 <https://github.com/ethereum/vyper/pull/1530>`_)
- Missing arg check for private functions (`#1579 <https://github.com/ethereum/vyper/pull/1579>`_)
- Zero padding issue (`#1563 <https://github.com/ethereum/vyper/issues/1563>`_)
- ``vyper.cli`` rearchitecture of scripts (`#1574 <https://github.com/ethereum/vyper/issues/1574>`_)
- AST end offsets and Solidity-compatible compressed sourcemap (`#1580 <https://github.com/ethereum/vyper/pull/1580>`_)

Special thanks to (`@iamdefinitelyahuman <https://github.com/iamdefinitelyahuman>`_) for lots of updates this release!

v0.1.0-beta.11
**************

Date released: 23-07-2019

Beta 11 brings some performance and stability fixes.

- Using calldata instead of memory parameters. (`#1499 <https://github.com/ethereum/vyper/pull/1499>`_)
- Reducing of contract size, for large parameter functions. (`#1486 <https://github.com/ethereum/vyper/pull/1486>`_)
- Improvements for Windows users (`#1486 <https://github.com/ethereum/vyper/pull/1486>`_)  (`#1488 <https://github.com/ethereum/vyper/pull/1488>`_)
- Array copy optimisation (`#1487 <https://github.com/ethereum/vyper/pull/1487>`_)
- Fixing ``@nonreentrant`` decorator for return statements (`#1532 <https://github.com/ethereum/vyper/pull/1532>`_)
- `sha3` builtin function removed  (`#1328 <https://github.com/ethereum/vyper/issues/1328>`_)
- Disallow conflicting method IDs (`#1530 <https://github.com/ethereum/vyper/pull/1530>`_)
- Additional ``convert()`` supported types (`#1524 <https://github.com/ethereum/vyper/pull/1524>`_) (`#1500 <https://github.com/ethereum/vyper/pull/1500>`_)
- Equality operator for strings and bytes (`#1507 <https://github.com/ethereum/vyper/pull/1507>`_)
- Change in ``compile_codes`` interface function (`#1504 <https://github.com/ethereum/vyper/pull/1504>`_)

Thanks to all the contributors!

v0.1.0-beta.10
**************

Date released: 24-05-2019

- Lots of linting and refactoring!
- Bugfix with regards to using arrays as parameters to private functions (`#1418 <https://github.com/ethereum/vyper/issues/1418>`_). Please check your contracts, and upgrade to latest version, if you do use this.
- Slight shrinking in init produced bytecode. (`#1399 <https://github.com/ethereum/vyper/issues/1399>`_)
- Additional constancy protection in the ``for .. range`` expression. (`#1397 <https://github.com/ethereum/vyper/issues/1397>`_)
- Improved bug report (`#1394 <https://github.com/ethereum/vyper/issues/1394>`_)
- Fix returning of External Contract from functions (`#1376 <https://github.com/ethereum/vyper/issues/1376>`_)
- Interface unit fix (`#1303 <https://github.com/ethereum/vyper/issues/1303>`_)
- Not Equal (!=) optimisation (`#1303 <https://github.com/ethereum/vyper/issues/1303>`_) 1386
- New ``assert <condition>, UNREACHABLE`` statement. (`#711 <https://github.com/ethereum/vyper/issues/711>`_)

Special thanks to (`Charles Cooper <https://github.com/charles-cooper>`_), for some excellent contributions this release.

v0.1.0-beta.9
*************

Date released: 12-03-2019

- Add support for list constants (`#1211 <https://github.com/ethereum/vyper/issues/1211>`_)
- Add sha256 function (`#1327 <https://github.com/ethereum/vyper/issues/1327>`_)
- Renamed create_with_code_of to create_forwarder_to (`#1177 <https://github.com/ethereum/vyper/issues/1177>`_)
- @nonreentrant Decorator  (`#1204 <https://github.com/ethereum/vyper/issues/1204>`_)
- Add opcodes and opcodes_runtime flags to compiler (`#1255 <https://github.com/ethereum/vyper/pull/1255>`_)
- Improved External contract call interfaces (`#885 <https://github.com/ethereum/vyper/issues/885>`_)

Prior to v0.1.0-beta.9
**********************

Prior to this release, we managed our change log in a different fashion.
Here is the old changelog:

* **2019.04.05**: Add stricter checking of unbalanced return statements. (`#590 <https://github.com/ethereum/vyper/issues/590>`_)
* **2019.03.04**: ``create_with_code_of`` has been renamed to ``create_forwarder_to``. (`#1177 <https://github.com/ethereum/vyper/issues/1177>`_)
* **2019.02.14**: Assigning a persistent contract address can only be done using the ``bar_contact = ERC20(<address>)`` syntax.
* **2019.02.12**: ERC20 interface has to be imported using ``from vyper.interfaces import ERC20`` to use.
* **2019.01.30**: Byte array literals need to be annoted using ``b""``, strings are represented as `""`.
* **2018.12.12**: Disallow use of ``None``, disallow use of ``del``, implemented ``clear()`` built-in function.
* **2018.11.19**: Change mapping syntax to use ``map()``. (`VIP564 <https://github.com/ethereum/vyper/issues/564>`_)
* **2018.10.02**: Change the convert style to use types instead of string. (`VIP1026 <https://github.com/ethereum/vyper/issues/1026>`_)
* **2018.09.24**: Add support for custom constants.
* **2018.08.09**: Add support for default parameters.
* **2018.06.08**: Tagged first beta.
* **2018.05.23**: Changed ``wei_value`` to be ``uint256``.
* **2018.04.03**: Changed bytes declaration from ``bytes <= n`` to ``bytes[n]``.
* **2018.03.27**: Renaming ``signed256`` to ``int256``.
* **2018.03.22**: Add modifiable and static keywords for external contract calls.
* **2018.03.20**: Renaming ``__log__`` to ``event``.
* **2018.02.22**: Renaming num to int128, and num256 to uint256.
* **2018.02.13**: Ban functions with payable and constant decorators.
* **2018.02.12**: Division by num returns decimal type.
* **2018.02.09**: Standardize type conversions.
* **2018.02.01**: Functions cannot have the same name as globals.
* **2018.01.27**: Change getter from get_var to var.
* **2018.01.11**: Change version from 0.0.2 to 0.0.3
* **2018.01.04**: Types need to be specified on assignment (`VIP545 <https://github.com/ethereum/vyper/issues/545>`_).
* **2017.01.02** Change ``as_wei_value`` to use quotes for units.
* **2017.12.25**: Change name from Viper to Vyper.
* **2017.12.22**: Add ``continue`` for loops
* **2017.11.29**: ``@internal`` renamed to ``@private``.
* **2017.11.15**: Functions require either ``@internal`` or ``@public`` decorators.
* **2017.07.25**: The ``def foo() -> num(const): ...`` syntax no longer works; you now need to do ``def foo() -> num: ...`` with a ``@constant`` decorator on the previous line.
* **2017.07.25**: Functions without a ``@payable`` decorator now fail when called with nonzero wei.
* **2017.07.25**: A function can only call functions that are declared above it (that is, A can call B only if B appears earlier in the code than A does). This was introduced
