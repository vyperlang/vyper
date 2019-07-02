.. _release-notes:

Release Notes
#############

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
