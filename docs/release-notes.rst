.. _release-notes:

Release Notes
#############
v0.1.0-beta.12
**************

Date released: TBD

The following VIPs were implemented for Beta 12:

- Support for relative imports (VIP `#1367 <https://github.com/ethereum/vyper/issues/1367>`_)
- Restricted use of environment variables in private functions (VIP `#1199 <https://github.com/ethereum/vyper/issues/1199>`_)

Some of the bug and stability fixes:

- ``@nonreentrant``/``@constant`` logical inconsistency (`#1544 <https://github.com/ethereum/vyper/issues/1544>`_)
- Struct passthrough issue (`#1551 <https://github.com/ethereum/vyper/issues/1551>`_)
- Private underflow issue (`#1470 <https://github.com/ethereum/vyper/issues/1470>`_)
- Constancy check issue (`#1480 <https://github.com/ethereum/vyper/pull/1480>`_)
- Prevent use of conflicting method IDs (`#1530 <https://github.com/ethereum/vyper/pull/1530>`_)
- Missing arg check for private functions (`#1579 <https://github.com/ethereum/vyper/pull/1579>`_)
- Zero padding issue (`#1563 <https://github.com/ethereum/vyper/issues/1563>`_)
- ``vyper.cli`` rearchicture of scripts (`#1574 <https://github.com/ethereum/vyper/issues/1574>`_)
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
- Fixing `@nonreentrant` decorator for return statements (`#1532 <https://github.com/ethereum/vyper/pull/1532>`_)
- `sha3` builtin function removed  (`#1328 <https://github.com/ethereum/vyper/issues/1328>`_)
- Disallow conflicting method IDs (`#1530 <https://github.com/ethereum/vyper/pull/1530>`_)
- Additional `convert()` supported types (`#1524 <https://github.com/ethereum/vyper/pull/1524>`_) (`#1500 <https://github.com/ethereum/vyper/pull/1500>`_)
- Equality operator for strings and bytes (`#1507 <https://github.com/ethereum/vyper/pull/1507>`_)
- Change in `compile_codes` interface function (`#1504 <https://github.com/ethereum/vyper/pull/1504>`_)

Thanks to all the contributors!

v0.1.0-beta.10
**************

Date released: 24-05-2019

- Lots of linting and refactoring!
- Bugfix with regards to using arrays as parameters to private functions (`#1418 <https://github.com/ethereum/vyper/issues/1418>`_). Please check your contracts, and upgrade to latest version, if you do use this.
- Slight shrinking in init produced bytecode. (`#1399 <https://github.com/ethereum/vyper/issues/1399>`_)
- Additional constancy protection in the `for .. range` expression. (`#1397 <https://github.com/ethereum/vyper/issues/1397>`_)
- Improved bug report (`#1394 <https://github.com/ethereum/vyper/issues/1394>`_)
- Fix returning of External Contract from functions (`#1376 <https://github.com/ethereum/vyper/issues/1376>`_)
- Interface unit fix (`#1303 <https://github.com/ethereum/vyper/issues/1303>`_)
- Not Equal (!=) optimisation (`#1303 <https://github.com/ethereum/vyper/issues/1303>`_) 1386
- New `assert <condition>, UNREACHABLE` statement. (`#711 <https://github.com/ethereum/vyper/issues/711>`_)

Special thanks to (`Charles Cooper <https://github.com/charles-cooper>`_), for some excellent contributions this release.

v0.1.0-beta.9
*************

Date released: 12-03-2019

- Add support for list constants (`#1211 <https://github.com/ethereum/vyper/issues/1211>`_)
- Add sha256 function (`#1327 <https://github.com/ethereum/vyper/issues/1327>`_)
- Renamed create_with_code_of to create_forwarder_to (`#1177 <https://github.com/ethereum/vyper/issues/1177>`_)
- @nonreentrant Decorator  (`#1204 <https://github.com/ethereum/vyper/issues/1204>`_)
- Add opcodes and opcodes_runtime flags to compiler (`#1255 <https://github.com/ethereum/vyper/issues/1255>`_)
- Improved External contract call interfaces (`#885 <https://github.com/ethereum/vyper/issues/885>`_)
