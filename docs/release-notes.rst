.. _release-notes:

Release Notes
#############

..
    vim regexes:
    first convert all single backticks to double backticks:
    :'<,'>s/`/``/g
    to convert links to nice rst links:
    :'<,'>s/\v(https:\/\/github.com\/vyperlang\/vyper\/pull\/)(\d+)/(`#\2 <\1\2>`_)/g
    ex. in: https://github.com/vyperlang/vyper/pull/3373
    ex. out: (`#3373 <https://github.com/vyperlang/vyper/pull/3373>`_)
    for advisory links:
    :'<,'>s/\v(https:\/\/github.com\/vyperlang\/vyper\/security\/advisories\/)([-A-Za-z0-9]+)/(`\2 <\1\2>`_)/g

v0.4.0b1 ("Nagini")
*******************

Date released: TBD
==================

v0.4.0 represents a major overhaul to the Vyper language. Notably, it overhauls the import system and adds support for code reuse. It also adds a new, experimental backend to Vyper which lays the foundation for improved analysis, optimization and integration with third party tools.

v0.3.10 ("Black Adder")
***********************

Date released: 2023-10-04
=========================

v0.3.10 is a performance focused release that additionally ships numerous bugfixes. It adds a ``codesize`` optimization mode (`#3493 <https://github.com/vyperlang/vyper/pull/3493>`_), adds new vyper-specific ``#pragma`` directives  (`#3493 <https://github.com/vyperlang/vyper/pull/3493>`_), uses Cancun's ``MCOPY`` opcode for some compiler generated code (`#3483 <https://github.com/vyperlang/vyper/pull/3483>`_), and generates selector tables which now feature O(1) performance (`#3496 <https://github.com/vyperlang/vyper/pull/3496>`_).

Breaking changes:
-----------------

- add runtime code layout to initcode (`#3584 <https://github.com/vyperlang/vyper/pull/3584>`_)
- drop evm versions through istanbul (`#3470 <https://github.com/vyperlang/vyper/pull/3470>`_)
- remove vyper signature from runtime (`#3471 <https://github.com/vyperlang/vyper/pull/3471>`_)
- only allow valid identifiers to be nonreentrant keys (`#3605 <https://github.com/vyperlang/vyper/pull/3605>`_)

Non-breaking changes and improvements:
--------------------------------------

- O(1) selector tables (`#3496 <https://github.com/vyperlang/vyper/pull/3496>`_)
- implement bound= in ranges (`#3537 <https://github.com/vyperlang/vyper/pull/3537>`_, `#3551 <https://github.com/vyperlang/vyper/pull/3551>`_)
- add optimization mode to vyper compiler (`#3493 <https://github.com/vyperlang/vyper/pull/3493>`_)
- improve batch copy performance (`#3483 <https://github.com/vyperlang/vyper/pull/3483>`_, `#3499 <https://github.com/vyperlang/vyper/pull/3499>`_, `#3525 <https://github.com/vyperlang/vyper/pull/3525>`_)

Notable fixes:
--------------

- fix ``ecrecover()`` behavior when signature is invalid (`GHSA-f5x6-7qgp-jhf3 <https://github.com/vyperlang/vyper/security/advisories/GHSA-f5x6-7qgp-jhf3>`_, `#3586 <https://github.com/vyperlang/vyper/pull/3586>`_)
- fix: order of evaluation for some builtins (`#3583 <https://github.com/vyperlang/vyper/pull/3583>`_, `#3587 <https://github.com/vyperlang/vyper/pull/3587>`_)
- fix: memory allocation in certain builtins using ``msize`` (`#3610 <https://github.com/vyperlang/vyper/pull/3610>`_)
- fix: ``_abi_decode()`` input validation in certain complex expressions (`#3626 <https://github.com/vyperlang/vyper/pull/3626>`_)
- fix: pycryptodome for arm builds (`#3485 <https://github.com/vyperlang/vyper/pull/3485>`_)
- let params of internal functions be mutable (`#3473 <https://github.com/vyperlang/vyper/pull/3473>`_)
- typechecking of folded builtins in (`#3490 <https://github.com/vyperlang/vyper/pull/3490>`_)
- update tload/tstore opcodes per latest 1153 EIP spec (`#3484 <https://github.com/vyperlang/vyper/pull/3484>`_)
- fix: raw_call type when max_outsize=0 is set (`#3572 <https://github.com/vyperlang/vyper/pull/3572>`_)
- fix: implements check for indexed event arguments (`#3570 <https://github.com/vyperlang/vyper/pull/3570>`_)
- fix: type-checking for ``_abi_decode()`` arguments (`#3626 <https://github.com/vyperlang/vyper/pull/3623>`__)

Other docs updates, chores and fixes:
-------------------------------------

- relax restrictions on internal function signatures (`#3573 <https://github.com/vyperlang/vyper/pull/3573>`_)
- note on security advisory in release notes for versions ``0.2.15``, ``0.2.16``, and ``0.3.0`` (`#3553 <https://github.com/vyperlang/vyper/pull/3553>`_)
- fix: yanked version in release notes (`#3545 <https://github.com/vyperlang/vyper/pull/3545>`_)
- update release notes on yanked versions (`#3547 <https://github.com/vyperlang/vyper/pull/3547>`_)
- improve error message for conflicting methods IDs (`#3491 <https://github.com/vyperlang/vyper/pull/3491>`_)
- document epsilon builtin (`#3552 <https://github.com/vyperlang/vyper/pull/3552>`_)
- relax version pragma parsing (`#3511 <https://github.com/vyperlang/vyper/pull/3511>`_)
- fix: issue with finding installed packages in editable mode (`#3510 <https://github.com/vyperlang/vyper/pull/3510>`_)
- add note on security advisory for ``ecrecover`` in docs (`#3539 <https://github.com/vyperlang/vyper/pull/3539>`_)
- add ``asm`` option to cli help (`#3585 <https://github.com/vyperlang/vyper/pull/3585>`_)
- add message to error map for repeat range check (`#3542 <https://github.com/vyperlang/vyper/pull/3542>`_)
- fix: public constant arrays (`#3536 <https://github.com/vyperlang/vyper/pull/3536>`_)


v0.3.9 ("Common Adder")
***********************

Date released: 2023-05-29

This is a patch release fix for v0.3.8. @bout3fiddy discovered a codesize regression for blueprint contracts in v0.3.8 which is fixed in this release. @bout3fiddy also discovered a runtime performance (gas) regression for default functions in v0.3.8 which is fixed in this release.

Fixes:

- initcode codesize blowup (`#3450 <https://github.com/vyperlang/vyper/pull/3450>`_)
- add back global calldatasize check for contracts with default fn (`#3463 <https://github.com/vyperlang/vyper/pull/3463>`_)


v0.3.8
******

Date released: 2023-05-23

Non-breaking changes and improvements:

- ``transient`` storage keyword (`#3373 <https://github.com/vyperlang/vyper/pull/3373>`_)
- ternary operators (`#3398 <https://github.com/vyperlang/vyper/pull/3398>`_)
- ``raw_revert()`` builtin (`#3136 <https://github.com/vyperlang/vyper/pull/3136>`_)
- shift operators (`#3019 <https://github.com/vyperlang/vyper/pull/3019>`_)
- make ``send()`` gas stipend configurable (`#3158 <https://github.com/vyperlang/vyper/pull/3158>`_)
- use new ``push0`` opcode (`#3361 <https://github.com/vyperlang/vyper/pull/3361>`_)
- python 3.11 support (`#3129 <https://github.com/vyperlang/vyper/pull/3129>`_)
- drop support for python 3.8 and 3.9 (`#3325 <https://github.com/vyperlang/vyper/pull/3325>`_)
- build for ``aarch64`` (`#2687 <https://github.com/vyperlang/vyper/pull/2687>`_)

Note that with the addition of ``push0`` opcode, ``shanghai`` is now the default compilation target for vyper. When deploying to a chain which does not support ``shanghai``, it is recommended to set ``--evm-version`` to ``paris``, otherwise it could result in hard-to-debug errors.

Major refactoring PRs:

- refactor front-end type system (`#2974 <https://github.com/vyperlang/vyper/pull/2974>`_)
- merge front-end and codegen type systems (`#3182 <https://github.com/vyperlang/vyper/pull/3182>`_)
- simplify ``GlobalContext`` (`#3209 <https://github.com/vyperlang/vyper/pull/3209>`_)
- remove ``FunctionSignature`` (`#3390 <https://github.com/vyperlang/vyper/pull/3390>`_)

Notable fixes:

- assignment when rhs is complex type and references lhs (`#3410 <https://github.com/vyperlang/vyper/pull/3410>`_)
- uninitialized immutable values (`#3409 <https://github.com/vyperlang/vyper/pull/3409>`_)
- success value when mixing ``max_outsize=0`` and ``revert_on_failure=False`` (`GHSA-w9g2-3w7p-72g9 <https://github.com/vyperlang/vyper/security/advisories/GHSA-w9g2-3w7p-72g9>`_)
- block certain kinds of storage allocator overflows (`GHSA-mgv8-gggw-mrg6 <https://github.com/vyperlang/vyper/security/advisories/GHSA-mgv8-gggw-mrg6>`_) 
- store-before-load when a dynarray appears on both sides of an assignment (`GHSA-3p37-3636-q8wv <https://github.com/vyperlang/vyper/security/advisories/GHSA-3p37-3636-q8wv>`_)
- bounds check for loops of the form ``for i in range(x, x+N)`` (`GHSA-6r8q-pfpv-7cgj <https://github.com/vyperlang/vyper/security/advisories/GHSA-6r8q-pfpv-7cgj>`_)
- alignment of call-site posargs and kwargs for internal functions (`GHSA-ph9x-4vc9-m39g <https://github.com/vyperlang/vyper/security/advisories/GHSA-ph9x-4vc9-m39g>`_)
- batch nonpayable check for default functions calldatasize < 4 (`#3104 <https://github.com/vyperlang/vyper/pull/3104>`_, `#3408 <https://github.com/vyperlang/vyper/pull/3408>`_, cf. `GHSA-vxmm-cwh2-q762 <https://github.com/vyperlang/vyper/security/advisories/GHSA-vxmm-cwh2-q762>`_)

Other docs updates, chores and fixes:

- call graph stability (`#3370 <https://github.com/vyperlang/vyper/pull/3370>`_)
- fix ``vyper-serve`` output (`#3338 <https://github.com/vyperlang/vyper/pull/3338>`_)
- add ``custom:`` natspec tags (`#3403 <https://github.com/vyperlang/vyper/pull/3403>`_)
- add missing pc maps to ``vyper_json`` output (`#3333 <https://github.com/vyperlang/vyper/pull/3333>`_)
- fix constructor context for internal functions (`#3388 <https://github.com/vyperlang/vyper/pull/3388>`_)
- add deprecation warning for ``selfdestruct`` usage (`#3372 <https://github.com/vyperlang/vyper/pull/3372>`_)
- add bytecode metadata option to vyper-json (`#3117 <https://github.com/vyperlang/vyper/pull/3117>`_)
- fix compiler panic when a ``break`` is outside of a loop (`#3177 <https://github.com/vyperlang/vyper/pull/3177>`_)
- fix complex arguments to builtin functions (`#3167 <https://github.com/vyperlang/vyper/pull/3167>`_)
- add support for all types in ABI imports (`#3154 <https://github.com/vyperlang/vyper/pull/3154>`_)
- disable uadd operator (`#3174 <https://github.com/vyperlang/vyper/pull/3174>`_)
- block bitwise ops on decimals (`#3219 <https://github.com/vyperlang/vyper/pull/3219>`_)
- raise ``UNREACHABLE`` (`#3194 <https://github.com/vyperlang/vyper/pull/3194>`_)
- allow enum as mapping key (`#3256 <https://github.com/vyperlang/vyper/pull/3256>`_)
- block boolean ``not`` operator on numeric types (`#3231 <https://github.com/vyperlang/vyper/pull/3231>`_)
- enforce that loop's iterators are valid names (`#3242 <https://github.com/vyperlang/vyper/pull/3242>`_)
- fix typechecker hotspot (`#3318 <https://github.com/vyperlang/vyper/pull/3318>`_)
- rewrite typechecker journal to handle nested commits (`#3375 <https://github.com/vyperlang/vyper/pull/3375>`_)
- fix missing pc map for empty functions (`#3202 <https://github.com/vyperlang/vyper/pull/3202>`_)
- guard against iterating over empty list in for loop (`#3197 <https://github.com/vyperlang/vyper/pull/3197>`_)
- skip enum members during constant folding (`#3235 <https://github.com/vyperlang/vyper/pull/3235>`_)
- bitwise ``not`` constant folding (`#3222 <https://github.com/vyperlang/vyper/pull/3222>`_)
- allow accessing members of constant address (`#3261 <https://github.com/vyperlang/vyper/pull/3261>`_)
- guard against decorators in interface (`#3266 <https://github.com/vyperlang/vyper/pull/3266>`_)
- fix bounds for decimals in some builtins (`#3283 <https://github.com/vyperlang/vyper/pull/3283>`_)
- length of literal empty bytestrings (`#3276 <https://github.com/vyperlang/vyper/pull/3276>`_)
- block ``empty()`` for HashMaps (`#3303 <https://github.com/vyperlang/vyper/pull/3303>`_)
- fix type inference for empty lists (`#3377 <https://github.com/vyperlang/vyper/pull/3377>`_)
- disallow logging from ``pure``, ``view`` functions (`#3424 <https://github.com/vyperlang/vyper/pull/3424>`_)
- improve optimizer rules for comparison operators (`#3412 <https://github.com/vyperlang/vyper/pull/3412>`_)
- deploy to ghcr on push (`#3435 <https://github.com/vyperlang/vyper/pull/3435>`_)
- add note on return value bounds in interfaces (`#3205 <https://github.com/vyperlang/vyper/pull/3205>`_)
- index ``id`` param in ``URI`` event of ``ERC1155ownable`` (`#3203 <https://github.com/vyperlang/vyper/pull/3203>`_)
- add missing ``asset`` function to ``ERC4626`` built-in interface (`#3295 <https://github.com/vyperlang/vyper/pull/3295>`_)
- clarify ``skip_contract_check=True`` can result in undefined behavior (`#3386 <https://github.com/vyperlang/vyper/pull/3386>`_)
- add ``custom`` NatSpec tag to docs (`#3404 <https://github.com/vyperlang/vyper/pull/3404>`_)
- fix ``uint256_addmod`` doc (`#3300 <https://github.com/vyperlang/vyper/pull/3300>`_)
- document optional kwargs for external calls (`#3122 <https://github.com/vyperlang/vyper/pull/3122>`_)
- remove ``slice()`` length documentation caveats (`#3152 <https://github.com/vyperlang/vyper/pull/3152>`_)
- fix docs of ``blockhash`` to reflect revert behaviour (`#3168 <https://github.com/vyperlang/vyper/pull/3168>`_)
- improvements to compiler error messages (`#3121 <https://github.com/vyperlang/vyper/pull/3121>`_, `#3134 <https://github.com/vyperlang/vyper/pull/3134>`_, `#3312 <https://github.com/vyperlang/vyper/pull/3312>`_, `#3304 <https://github.com/vyperlang/vyper/pull/3304>`_, `#3240 <https://github.com/vyperlang/vyper/pull/3240>`_, `#3264 <https://github.com/vyperlang/vyper/pull/3264>`_, `#3343 <https://github.com/vyperlang/vyper/pull/3343>`_, `#3307 <https://github.com/vyperlang/vyper/pull/3307>`_, `#3313 <https://github.com/vyperlang/vyper/pull/3313>`_ and `#3215 <https://github.com/vyperlang/vyper/pull/3215>`_)

These are really just the highlights, as many other bugfixes, docs updates and refactoring (over 150 pull requests!) made it into this release! For the full list, please see the `changelog <https://github.com/vyperlang/vyper/compare/v0.3.7...v0.3.8>`__. Special thanks to contributions from @tserg, @trocher, @z80dev, @emc415 and @benber86 in this release!

New Contributors:

- @omahs made their first contribution in (`#3128 <https://github.com/vyperlang/vyper/pull/3128>`_)
- @ObiajuluM made their first contribution in (`#3124 <https://github.com/vyperlang/vyper/pull/3124>`_)
- @trocher made their first contribution in (`#3134 <https://github.com/vyperlang/vyper/pull/3134>`_)
- @ozmium22 made their first contribution in (`#3149 <https://github.com/vyperlang/vyper/pull/3149>`_)
- @ToonVanHove made their first contribution in (`#3168 <https://github.com/vyperlang/vyper/pull/3168>`_)
- @emc415 made their first contribution in (`#3158 <https://github.com/vyperlang/vyper/pull/3158>`_)
- @lgtm-com made their first contribution in (`#3147 <https://github.com/vyperlang/vyper/pull/3147>`_)
- @tdurieux made their first contribution in (`#3224 <https://github.com/vyperlang/vyper/pull/3224>`_)
- @victor-ego made their first contribution in (`#3263 <https://github.com/vyperlang/vyper/pull/3263>`_)
- @miohtama made their first contribution in (`#3257 <https://github.com/vyperlang/vyper/pull/3257>`_)
- @kelvinfan001 made their first contribution in (`#2687 <https://github.com/vyperlang/vyper/pull/2687>`_)


v0.3.7
******

Date released: 2022-09-26

Breaking changes:

- chore: drop python 3.7 support (`#3071 <https://github.com/vyperlang/vyper/pull/3071>`_)
- fix: relax check for statically sized calldata (`#3090 <https://github.com/vyperlang/vyper/pull/3090>`_)

Non-breaking changes and improvements:

- fix: assert description in ``Crowdfund.finalize()`` (`#3058 <https://github.com/vyperlang/vyper/pull/3058>`_)
- fix: change mutability of example ERC721 interface (`#3076 <https://github.com/vyperlang/vyper/pull/3076>`_)
- chore: improve error message for non-checksummed address literal (`#3065 <https://github.com/vyperlang/vyper/pull/3065>`_)
- feat: ``isqrt()`` builtin (`#3074 <https://github.com/vyperlang/vyper/pull/3074>`_) (`#3069 <https://github.com/vyperlang/vyper/pull/3069>`_)
- feat: add ``block.prevrandao`` as alias for ``block.difficulty`` (`#3085 <https://github.com/vyperlang/vyper/pull/3085>`_)
- feat: ``epsilon()`` builtin (`#3057 <https://github.com/vyperlang/vyper/pull/3057>`_)
- feat: extend ecrecover signature to accept additional parameter types (`#3084 <https://github.com/vyperlang/vyper/pull/3084>`_)
- feat: allow constant and immutable variables to be declared public (`#3024 <https://github.com/vyperlang/vyper/pull/3024>`_)
- feat: optionally disable metadata in bytecode (`#3107 <https://github.com/vyperlang/vyper/pull/3107>`_)
    
Bugfixes:

- fix: empty nested dynamic arrays (`#3061 <https://github.com/vyperlang/vyper/pull/3061>`_)
- fix: foldable builtin default args in imports (`#3079 <https://github.com/vyperlang/vyper/pull/3079>`_) (`#3077 <https://github.com/vyperlang/vyper/pull/3077>`_)

Additional changes and improvements:

- doc: update broken links in SECURITY.md (`#3095 <https://github.com/vyperlang/vyper/pull/3095>`_)
- chore: update discord link in docs (`#3031 <https://github.com/vyperlang/vyper/pull/3031>`_)
- fix: broken links in various READMEs (`#3072 <https://github.com/vyperlang/vyper/pull/3072>`_)
- chore: fix compile warnings in examples (`#3033 <https://github.com/vyperlang/vyper/pull/3033>`_)
- feat: append lineno to the filename in error messages (`#3092 <https://github.com/vyperlang/vyper/pull/3092>`_)
- chore: migrate lark grammar (`#3082 <https://github.com/vyperlang/vyper/pull/3082>`_)
- chore: loosen and upgrade semantic version (`#3106 <https://github.com/vyperlang/vyper/pull/3106>`_)

New Contributors

- @emilianobonassi made their first contribution in `#3107 <https://github.com/vyperlang/vyper/pull/3107>`_
- @unparalleled-js made their first contribution in `#3106 <https://github.com/vyperlang/vyper/pull/3106>`_
- @pcaversaccio made their first contribution in `#3085 <https://github.com/vyperlang/vyper/pull/3085>`_
- @nfwsncked made their first contribution in `#3058 <https://github.com/vyperlang/vyper/pull/3058>`_
- @z80 made their first contribution in `#3057 <https://github.com/vyperlang/vyper/pull/3057>`_
- @Benny made their first contribution in `#3024 <https://github.com/vyperlang/vyper/pull/3024>`_
- @cairo made their first contribution in `#3072 <https://github.com/vyperlang/vyper/pull/3072>`_
- @fiddy made their first contribution in `#3069 <https://github.com/vyperlang/vyper/pull/3069>`_

Special thanks to returning contributors @tserg, @pandadefi, and @delaaxe.

v0.3.6
******

Date released: 2022-08-07

Bugfixes:

* Fix ``in`` expressions when list members are variables (`#3035 <https://github.com/vyperlang/vyper/pull/3035>`_)


v0.3.5
******
**THIS RELEASE HAS BEEN PULLED**

Date released: 2022-08-05

Non-breaking changes and improvements:

* Add blueprint deployer output format (`#3001 <https://github.com/vyperlang/vyper/pull/3001>`_)
* Allow arbitrary data to be passed to ``create_from_blueprint`` (`#2996 <https://github.com/vyperlang/vyper/pull/2996>`_)
* Add CBOR length to bytecode for decoders (`#3010 <https://github.com/vyperlang/vyper/pull/3010>`_)
* Fix compiler panic when accessing enum storage vars via ``self`` (`#2998 <https://github.com/vyperlang/vyper/pull/2998>`_)
* Fix: allow ``empty()`` in constant definitions and in default argument position (`#3008 <https://github.com/vyperlang/vyper/pull/3008>`_)
* Fix: disallow ``self`` address in pure functions (`#3027 <https://github.com/vyperlang/vyper/pull/3027>`_)

v0.3.4
******

Date released: 2022-07-27

Non-breaking changes and improvements:

* Add enum types (`#2874 <https://github.com/vyperlang/vyper/pull/2874>`_, `#2915 <https://github.com/vyperlang/vyper/pull/2915>`_, `#2925 <https://github.com/vyperlang/vyper/pull/2925>`_, `#2977 <https://github.com/vyperlang/vyper/pull/2977>`_)
* Add ``_abi_decode`` builtin (`#2882 <https://github.com/vyperlang/vyper/pull/2882>`_)
* Add ``create_from_blueprint`` and ``create_copy_of`` builtins (`#2895 <https://github.com/vyperlang/vyper/pull/2895>`_)
* Add ``default_return_value`` kwarg for calls (`#2839 <https://github.com/vyperlang/vyper/pull/2839>`_)
* Add ``min_value`` and ``max_value`` builtins for numeric types (`#2935 <https://github.com/vyperlang/vyper/pull/2935>`_)
* Add ``uint2str`` builtin (`#2879 <https://github.com/vyperlang/vyper/pull/2879>`_)
* Add vyper signature to bytecode (`#2860 <https://github.com/vyperlang/vyper/pull/2860>`_)


Other fixes and improvements:

* Call internal functions from constructor (`#2496 <https://github.com/vyperlang/vyper/pull/2496>`_)
* Arithmetic for new int types (`#2843 <https://github.com/vyperlang/vyper/pull/2843>`_)
* Allow ``msg.data`` in ``raw_call`` without ``slice`` (`#2902 <https://github.com/vyperlang/vyper/pull/2902>`_)
* Per-method calldatasize checks (`#2911 <https://github.com/vyperlang/vyper/pull/2911>`_)
* Type inference and annotation of arguments for builtin functions (`#2817 <https://github.com/vyperlang/vyper/pull/2817>`_)
* Allow varargs for ``print`` (`#2833 <https://github.com/vyperlang/vyper/pull/2833>`_)
* Add ``error_map`` output format for tooling consumption (`#2939 <https://github.com/vyperlang/vyper/pull/2939>`_)
* Multiple evaluation of contract address in call (`GHSA-4v9q-cgpw-cf38 <https://github.com/vyperlang/vyper/security/advisories/GHSA-4v9q-cgpw-cf38>`_)
* Improve ast output (`#2824 <https://github.com/vyperlang/vyper/pull/2824>`_)
* Allow ``@nonreentrant`` on view functions (`#2921 <https://github.com/vyperlang/vyper/pull/2921>`_)
* Add ``shift()`` support for signed integers (`#2964 <https://github.com/vyperlang/vyper/pull/2964>`_)
* Enable dynarrays of strings (`#2922 <https://github.com/vyperlang/vyper/pull/2922>`_)
* Fix off-by-one bounds check in certain safepow cases (`#2983 <https://github.com/vyperlang/vyper/pull/2983>`_)
* Optimizer improvements (`#2647 <https://github.com/vyperlang/vyper/pull/2647>`_, `#2868 <https://github.com/vyperlang/vyper/pull/2868>`_, `#2914 <https://github.com/vyperlang/vyper/pull/2914>`_, `#2843 <https://github.com/vyperlang/vyper/pull/2843>`_, `#2944 <https://github.com/vyperlang/vyper/pull/2944>`_)
* Reverse order in which exceptions are reported (`#2838 <https://github.com/vyperlang/vyper/pull/2838>`_)
* Fix compile-time blowup for large contracts (`#2981 <https://github.com/vyperlang/vyper/pull/2981>`_)
* Rename ``vyper-ir`` binary to ``fang`` (`#2936 <https://github.com/vyperlang/vyper/pull/2936>`_)


Many other small bugfixes, optimizations and refactoring also made it into this release! Special thanks to @tserg and @pandadefi for contributing several important bugfixes, refactoring and features to this release!


v0.3.3
******

Date released: 2022-04-22

This is a bugfix release. It patches an off-by-one error in the storage allocation mechanism for dynamic arrays reported by @haltman-at in `#2820 <https://github.com/vyperlang/vyper/issues/2820>`_

Other fixes and improvements:

* Add a ``print`` built-in which allows printing debugging messages in hardhat. (`#2818 <https://github.com/vyperlang/vyper/pull/2818>`_)
* Fix various error messages (`#2798 <https://github.com/vyperlang/vyper/pull/2798>`_, `#2805 <https://github.com/vyperlang/vyper/pull/2805>`_)


v0.3.2
******

Date released: 2022-04-17

Breaking changes:

* Increase the bounds of the ``decimal`` type (`#2730 <https://github.com/vyperlang/vyper/pull/2730>`_)
* Generalize and simplify the semantics of the ``convert`` builtin (`#2694 <https://github.com/vyperlang/vyper/pull/2694>`_)
* Restrict hex and bytes literals (`#2736 <https://github.com/vyperlang/vyper/pull/2736>`_, `#2872 <https://github.com/vyperlang/vyper/pull/2782>`_)

Non-breaking changes and improvements:

* Implement dynamic arrays (`#2556 <https://github.com/vyperlang/vyper/pull/2556>`_, `#2606 <https://github.com/vyperlang/vyper/pull/2606>`_, `#2615 <https://github.com/vyperlang/vyper/pull/2615>`_)
* Support all ABIv2 integer and bytes types (`#2705 <https://github.com/vyperlang/vyper/pull/2705>`_)
* Add storage layout override mechanism (`#2593 <https://github.com/vyperlang/vyper/pull/2593>`_)
* Support ``<address>.code`` attribute (`#2583 <https://github.com/vyperlang/vyper/pull/2583>`_)
* Add ``tx.gasprice`` builtin (`#2624 <https://github.com/vyperlang/vyper/pull/2624>`_)
* Allow structs as constant variables (`#2617 <https://github.com/vyperlang/vyper/pull/2617>`_)
* Implement ``skip_contract_check`` kwarg (`#2551 <https://github.com/vyperlang/vyper/pull/2551>`_)
* Support EIP-2678 ethPM manifest files (`#2628 <https://github.com/vyperlang/vyper/pull/2628>`_)
* Add ``metadata`` output format (`#2597 <https://github.com/vyperlang/vyper/pull/2597>`_)
* Allow ``msg.*`` variables in internal functions (`#2632 <https://github.com/vyperlang/vyper/pull/2632>`_)
* Add ``unsafe_`` arithmetic builtins (`#2629 <https://github.com/vyperlang/vyper/pull/2629>`_)
* Add subroutines to Vyper IR (`#2598 <https://github.com/vyperlang/vyper/pull/2598>`_)
* Add ``select`` opcode to Vyper IR (`#2690 <https://github.com/vyperlang/vyper/pull/2690>`_)
* Allow lists of any type as loop variables (`#2616 <https://github.com/vyperlang/vyper/pull/2616>`_)
* Improve suggestions in error messages (`#2806 <https://github.com/vyperlang/vyper/pull/2806>`_)

Notable Fixes:

* Clamping of returndata from external calls in complex expressions (`GHSA-4mrx-6fxm-8jpg <https://github.com/vyperlang/vyper/security/advisories/GHSA-4mrx-6fxm-8jpg>`_, `GHSA-j2x6-9323-fp7h <https://github.com/vyperlang/vyper/security/advisories/GHSA-j2x6-9323-fp7h>`_)
* Bytestring equality for (N<=32) (`GHSA-7vrm-3jc8-5wwm <https://github.com/vyperlang/vyper/security/advisories/GHSA-7vrm-3jc8-5wwm>`_)
* Typechecking of constant variables (`#2580 <https://github.com/vyperlang/vyper/pull/2580>`_, `#2603 <https://github.com/vyperlang/vyper/pull/2603>`_)
* Referencing immutables in constructor (`#2627 <https://github.com/vyperlang/vyper/pull/2627>`_)
* Arrays of interfaces in for loops (`#2699 <https://github.com/vyperlang/vyper/pull/2699>`_)

Lots of optimizations, refactoring and other fixes made it into this release! For the full list, please see the `changelog <https://github.com/vyperlang/vyper/compare/v0.3.1...v0.3.2>`__.

Special thanks to @tserg for typechecker fixes and significant testing of new features! Additional contributors to this release include @abdullathedruid, @hi-ogawa, @skellet0r, @fubuloubu, @onlymaresia, @SwapOperator, @hitsuzen-eth, @Sud0u53r, @davidhq.


v0.3.1
*******

Date released: 2021-12-01

Breaking changes:

* Disallow changes to decimal precision when used as a library (`#2479 <https://github.com/vyperlang/vyper/pull/2479>`_)

Non-breaking changes and improvements:

* Add immutable variables (`#2466 <https://github.com/vyperlang/vyper/pull/2466>`_)
* Add uint8 type (`#2477 <https://github.com/vyperlang/vyper/pull/2477>`_)
* Add gaslimit and basefee env variables (`#2495 <https://github.com/vyperlang/vyper/pull/2495>`_)
* Enable checkable raw_call (`#2482 <https://github.com/vyperlang/vyper/pull/2482>`_)
* Propagate revert data when external call fails (`#2531 <https://github.com/vyperlang/vyper/pull/2531>`_)
* Improve LLL annotations (`#2486 <https://github.com/vyperlang/vyper/pull/2486>`_)
* Optimize short-circuiting boolean operations (`#2467 <https://github.com/vyperlang/vyper/pull/2467>`_, `#2493 <https://github.com/vyperlang/vyper/pull/2493>`_)
* Optimize identity precompile usage (`#2488 <https://github.com/vyperlang/vyper/pull/2488>`_)
* Remove loaded limits for int128 and address (`#2506 <https://github.com/vyperlang/vyper/pull/2506>`_)
* Add machine readable ir_json format (`#2510 <https://github.com/vyperlang/vyper/pull/2510>`_)
* Optimize raw_call for the common case when the input is in memory (`#2481 <https://github.com/vyperlang/vyper/pull/2481>`_)
* Remove experimental OVM transpiler (`#2532 <https://github.com/vyperlang/vyper/pull/2532>`_)
* Add CLI flag to disable optimizer (`#2522 <https://github.com/vyperlang/vyper/pull/2522>`_)
* Add docs for LLL syntax and semantics (`#2494 <https://github.com/vyperlang/vyper/pull/2494>`_)

Fixes:

* Allow non-constant revert reason strings (`#2509 <https://github.com/vyperlang/vyper/pull/2509>`_)
* Allow slices of complex expressions (`#2500 <https://github.com/vyperlang/vyper/pull/2500>`_)
* Remove seq_unchecked from LLL codegen (`#2485 <https://github.com/vyperlang/vyper/pull/2485>`_)
* Fix external calls with default parameters (`#2526 <https://github.com/vyperlang/vyper/pull/2526>`_)
* Enable lists of structs as function arguments (`#2515 <https://github.com/vyperlang/vyper/pull/2515>`_)
* Fix .balance on constant addresses (`#2533 <https://github.com/vyperlang/vyper/pull/2533>`_)
* Allow variable indexing into constant/literal arrays (`#2534 <https://github.com/vyperlang/vyper/pull/2534>`_)
* Fix allocation of unused storage slots (`#2439 <https://github.com/vyperlang/vyper/pull/2439>`_, `#2514 <https://github.com/vyperlang/vyper/pull/2514>`_)

Special thanks to @skellet0r for some major features in this release!

v0.3.0
*******
⚠️ A critical security vulnerability has been discovered in this version and we strongly recommend using version `0.3.1 <https://github.com/vyperlang/vyper/releases/tag/v0.3.1>`_ or higher. For more information, please see the Security Advisory `GHSA-5824-cm3x-3c38 <https://github.com/vyperlang/vyper/security/advisories/GHSA-5824-cm3x-3c38>`_.

Date released: 2021-10-04

Breaking changes:

* Change ABI encoding of single-struct return values to be compatible with Solidity (`#2457 <https://github.com/vyperlang/vyper/pull/2457>`_)
* Drop Python 3.6 support (`#2462 <https://github.com/vyperlang/vyper/pull/2462>`_)

Non-breaking changes and improvements:

* Rewrite internal calling convention (`#2447 <https://github.com/vyperlang/vyper/pull/2447>`_)
* Allow any ABI-encodable type as function arguments and return types (`#2154 <https://github.com/vyperlang/vyper/issues/2154>`_, `#2190 <https://github.com/vyperlang/vyper/issues/2190>`_)
* Add support for deterministic deployment of minimal proxies using CREATE2 (`#2460 <https://github.com/vyperlang/vyper/pull/2460>`_)
* Optimize code for certain copies (`#2468 <https://github.com/vyperlang/vyper/pull/2468>`_)
* Add -o CLI flag to redirect output to a file (`#2452 <https://github.com/vyperlang/vyper/pull/2452>`_)
* Other docs updates (`#2450 <https://github.com/vyperlang/vyper/pull/2450>`_)

Fixes:

* _abi_encode builtin evaluates arguments multiple times (`#2459 <https://github.com/vyperlang/vyper/issues/2459>`_)
* ABI length is too short for nested tuples (`#2458 <https://github.com/vyperlang/vyper/issues/2458>`_)
* Returndata is not clamped for certain numeric types (`#2454 <https://github.com/vyperlang/vyper/issues/2454>`_)
* __default__ functions do not respect nonreentrancy keys (`#2455 <https://github.com/vyperlang/vyper/issues/2455>`_)
* Clamps for bytestrings in initcode are broken (`#2456 <https://github.com/vyperlang/vyper/issues/2456>`_)
* Missing clamps for decimal args in external functions (`GHSA-c7pr-343r-5c46 <https://github.com/vyperlang/vyper/security/advisories/GHSA-c7pr-343r-5c46>`_)
* Memory corruption when returning a literal struct with a private function call inside of it (`GHSA-xv8x-pr4h-73jv <https://github.com/vyperlang/vyper/security/advisories/GHSA-xv8x-pr4h-73jv>`_)

Special thanks to contributions from @skellet0r and @benjyz for this release!


v0.2.16
*******
⚠️ A critical security vulnerability has been discovered in this version and we strongly recommend using version `0.3.1 <https://github.com/vyperlang/vyper/releases/tag/v0.3.1>`_ or higher. For more information, please see the Security Advisory `GHSA-5824-cm3x-3c38 <https://github.com/vyperlang/vyper/security/advisories/GHSA-5824-cm3x-3c38>`_.

Date released: 2021-08-27

Non-breaking changes and improvements:

* Expose _abi_encode as a user-facing builtin (`#2401 <https://github.com/vyperlang/vyper/pull/2401>`_)
* Export the storage layout as a compiler output option (`#2433 <https://github.com/vyperlang/vyper/pull/2433>`_)
* Add experimental OVM backend (`#2416 <https://github.com/vyperlang/vyper/pull/2416>`_)
* Allow any ABI-encodable type as event arguments (`#2403 <https://github.com/vyperlang/vyper/pull/2403>`_)
* Optimize int128 clamping (`#2411 <https://github.com/vyperlang/vyper/pull/2411>`_)
* Other docs updates (`#2405 <https://github.com/vyperlang/vyper/pull/2405>`_, `#2422 <https://github.com/vyperlang/vyper/pull/2422>`_, `#2425 <https://github.com/vyperlang/vyper/pull/2425>`_)

Fixes:

* Disallow nonreentrant decorator on constructors (`#2426 <https://github.com/vyperlang/vyper/pull/2426>`_)
* Fix bounds checks when handling msg.data (`#2419 <https://github.com/vyperlang/vyper/pull/2419>`_)
* Allow interfaces in lists, structs and maps (`#2397 <https://github.com/vyperlang/vyper/pull/2397>`_)
* Fix trailing newline parse bug (`#2412 <https://github.com/vyperlang/vyper/pull/2412>`_)

Special thanks to contributions from @skellet0r, @sambacha and @milancermak for this release!


v0.2.15
*******
⚠️ A critical security vulnerability has been discovered in this version and we strongly recommend using version `0.3.1 <https://github.com/vyperlang/vyper/releases/tag/v0.3.1>`_ or higher. For more information, please see the Security Advisory `GHSA-5824-cm3x-3c38 <https://github.com/vyperlang/vyper/security/advisories/GHSA-5824-cm3x-3c38>`_.

Date released: 23-07-2021

Non-breaking changes and improvements
- Optimization when returning nested tuples (`#2392 <https://github.com/vyperlang/vyper/pull/2392>`_)

Fixes:
- Annotated kwargs for builtins (`#2389 <https://github.com/vyperlang/vyper/pull/2389>`_)
- Storage slot allocation bug (`#2391 <https://github.com/vyperlang/vyper/pull/2391>`_)

v0.2.14
*******
**THIS RELEASE HAS BEEN PULLED**

Date released: 20-07-2021

Non-breaking changes and improvements:
- Reduce bytecode by sharing code for clamps (`#2387 <https://github.com/vyperlang/vyper/pull/2387>`_)

Fixes:
- Storage corruption from re-entrancy locks (`#2379 <https://github.com/vyperlang/vyper/pull/2379>`_)

v0.2.13
*******
**THIS RELEASE HAS BEEN PULLED**

Date released: 06-07-2021

Non-breaking changes and improvements:

- Add the ``abs`` builtin function (`#2356 <https://github.com/vyperlang/vyper/pull/2356>`_)
- Streamline the location of arrays within storage (`#2361 <https://github.com/vyperlang/vyper/pull/2361>`_)

v0.2.12
*******

Date released: 16-04-2021

This release fixes a memory corruption bug (`#2345 <https://github.com/vyperlang/vyper/pull/2345>`_) that was introduced in the v0.2.x series
and was not fixed in `VVE-2020-0004 <https://github.com/vyperlang/vyper/security/advisories/GHSA-2r3x-4mrv-mcxf>`_. Read about it further in
`VVE-2021-0001 <https://github.com/vyperlang/vyper/security/advisories/GHSA-22wc-c9wj-6q2v>`_.

Non-breaking changes and improvements:

- Optimize ``calldataload`` (`#2352 <https://github.com/vyperlang/vyper/pull/2352>`_)
- Add the ``int256`` signed integer type (`#2351 <https://github.com/vyperlang/vyper/pull/2351>`_)
- EIP2929 opcode repricing and Berlin support (`#2350 <https://github.com/vyperlang/vyper/pull/2350>`_)
- Add ``msg.data`` environment variable #2343 (`#2343 <https://github.com/vyperlang/vyper/pull/2343>`_)
- Full support for Python 3.9 (`#2233 <https://github.com/vyperlang/vyper/pull/2233>`_)

v0.2.11
*******

Date released: 27-02-2021

This is a quick patch release to fix a memory corruption bug that was introduced in v0.2.9 (`#2321 <https://github.com/vyperlang/vyper/pull/2321>`_) with excessive memory deallocation when releasing internal variables

v0.2.10
*******
**THIS RELEASE HAS BEEN PULLED**

Date released: 17-02-2021

This is a quick patch release to fix incorrect generated ABIs that was introduced in v0.2.9 (`#2311 <https://github.com/vyperlang/vyper/pull/2311>`_) where storage variable getters were incorrectly marked as ``nonpayable`` instead of ``view``

v0.2.9
******
**THIS RELEASE HAS BEEN PULLED**

Date released: 16-02-2021

Non-breaking changes and improvements:
- Add license to wheel, Anaconda support (`#2265 <https://github.com/vyperlang/vyper/pull/2265>`_)
- Consider events during type-check with `implements:` (`#2283 <https://github.com/vyperlang/vyper/pull/2283>`_)
- Refactor ABI generation (`#2284 <https://github.com/vyperlang/vyper/pull/2284>`_)
- Remove redundant checks in parser/signatures (`#2288 <https://github.com/vyperlang/vyper/pull/2288>`_)
- Streamling ABI-encoding logic for tuple return types (`#2302 <https://github.com/vyperlang/vyper/pull/2302>`_)
- Optimize function ordering within bytecode (`#2303 <https://github.com/vyperlang/vyper/pull/2303>`_)
- Assembly-level optimizations (`#2304 <https://github.com/vyperlang/vyper/pull/2304>`_)
- Optimize nonpayable assertion (`#2307 <https://github.com/vyperlang/vyper/pull/2307>`_)
- Optimize re-entrancy locks (`#2308 <https://github.com/vyperlang/vyper/pull/2308>`_)

Fixes:
- Change forwarder proxy bytecode to ERC-1167 (`#2281 <https://github.com/vyperlang/vyper/pull/2281>`_)
- Reserved keywords check update (`#2286 <https://github.com/vyperlang/vyper/pull/2286>`_)
- Incorrect type-check error in literal lists (`#2309 <https://github.com/vyperlang/vyper/pull/2309>`_)

Tons of Refactoring work courtesy of (`@iamdefinitelyahuman <https://github.com/iamdefinitelyahuman>`_)!

v0.2.8
******

Date released: 04-12-2020

Non-breaking changes and improvements:

- AST updates to provide preliminary support for Python 3.9 (`#2225 <https://github.com/vyperlang/vyper/pull/2225>`_)
- Support for the ``not in`` comparator (`#2232 <https://github.com/vyperlang/vyper/pull/2232>`_)
- Lift restriction on calldata variables shadowing storage variables (`#2226 <https://github.com/vyperlang/vyper/pull/2226>`_)
- Optimize ``shift`` bytecode when 2nd arg is a literal (`#2201 <https://github.com/vyperlang/vyper/pull/2201>`_)
- Warn when EIP-170 size limit is exceeded (`#2208 <https://github.com/vyperlang/vyper/pull/2208>`_)

Fixes:

- Allow use of ``slice`` on a calldata ``bytes32`` (`#2227 <https://github.com/vyperlang/vyper/pull/2227>`_)
- Explicitly disallow iteration of a list of structs (`#2228 <https://github.com/vyperlang/vyper/pull/2228>`_)
- Improved validation of address checksums (`#2229 <https://github.com/vyperlang/vyper/pull/2229>`_)
- Bytes are always represented as hex within the AST (`#2231 <https://github.com/vyperlang/vyper/pull/2231>`_)
- Allow ``empty`` as an argument within a function call (`#2234 <https://github.com/vyperlang/vyper/pull/2234>`_)
- Allow ``empty`` static-sized array as an argument within a ``log`` statement (`#2235 <https://github.com/vyperlang/vyper/pull/2235>`_)
- Compile-time issue with ``Bytes`` variables as a key in a mapping (`#2239 <https://github.com/vyperlang/vyper/pull/2239>`_)

v0.2.7
******

Date released: 10-14-2020

This is a quick patch release to fix a runtime error introduced in ``v0.2.6`` (`#2188 <https://github.com/vyperlang/vyper/pull/2188>`_) that could allow for memory corruption under certain conditions.

Non-breaking changes and improvements:

- Optimizations around ``assert`` and ``raise`` (`#2198 <https://github.com/vyperlang/vyper/pull/2198>`_)
- Simplified internal handling of memory variables (`#2194 <https://github.com/vyperlang/vyper/pull/2194>`_)

Fixes:

- Ensure internal variables are always placed sequentially within memory (`#2196 <https://github.com/vyperlang/vyper/pull/2196>`_)
- Bugfixes around memory de-allocation (`#2197 <https://github.com/vyperlang/vyper/pull/2197>`_)

v0.2.6
******
**THIS RELEASE HAS BEEN PULLED**

Date released: 10-10-2020

Non-breaking changes and improvements:

- Release and reuse memory slots within the same function (`#2188 <https://github.com/vyperlang/vyper/pull/2188>`_)
- Allow implicit use of ``uint256`` as iterator type in range-based for loops (`#2180 <https://github.com/vyperlang/vyper/pull/2180>`_)
- Optimize clamping logic for ``int128`` (`#2179 <https://github.com/vyperlang/vyper/pull/2179>`_)
- Calculate array index offsets at compile time where possible (`#2187 <https://github.com/vyperlang/vyper/pull/2187>`_)
- Improved exception for invalid use of dynamically sized struct (`#2189 <https://github.com/vyperlang/vyper/pull/2189>`_)
- Improved exception for incorrect arg count in function call (`#2178 <https://github.com/vyperlang/vyper/pull/2178>`_)
- Improved exception for invalid subscript (`#2177 <https://github.com/vyperlang/vyper/pull/2177>`_)

Fixes:

- Memory corruption issue when performing function calls inside a tuple or another function call (`#2186 <https://github.com/vyperlang/vyper/pull/2186>`_)
- Incorrect function output when using multidimensional arrays (`#2184 <https://github.com/vyperlang/vyper/pull/2184>`_)
- Reduced ambiguity between ``address`` and ``Bytes[20]`` (`#2191 <https://github.com/vyperlang/vyper/pull/2191>`_)

v0.2.5
******

Date released: 30-09-2020

Non-breaking changes and improvements:

- Improve exception on incorrect interface (`#2131 <https://github.com/vyperlang/vyper/pull/2131>`_)
- Standalone binary preparation (`#2134 <https://github.com/vyperlang/vyper/pull/2134>`_)
- Improve make freeze (`#2135 <https://github.com/vyperlang/vyper/pull/2135>`_)
- Remove Excessive Scoping Rules on Local Variables (`#2166 <https://github.com/vyperlang/vyper/pull/2166>`_)
- Optimize nonpayable check for contracts that do not accept ETH (`#2172 <https://github.com/vyperlang/vyper/pull/2172>`_)
- Optimize safemath on division-by-zero with a literal divisor (`#2173 <https://github.com/vyperlang/vyper/pull/2173>`_)
- Optimize multiple sequential memory-zeroings (`#2174 <https://github.com/vyperlang/vyper/pull/2174>`_)
- Optimize size-limit checks for address and bool types (`#2175 <https://github.com/vyperlang/vyper/pull/2175>`_)

Fixes:

- Constant folding on lhs of assignments (`#2137 <https://github.com/vyperlang/vyper/pull/2137>`_)
- ABI issue with bytes and string arrays inside tuples (`#2140 <https://github.com/vyperlang/vyper/pull/2140>`_)
- Returning struct from a external function gives error (`#2143 <https://github.com/vyperlang/vyper/pull/2143>`_)
- Error messages with struct display all members (`#2160 <https://github.com/vyperlang/vyper/pull/2160>`_)
- The returned struct value from the external call doesn't get stored properly (`#2164 <https://github.com/vyperlang/vyper/pull/2164>`_)
- Improved exception on invalid function-scoped assignment (`#2176 <https://github.com/vyperlang/vyper/pull/2176>`_)

v0.2.4
******

Date released: 03-08-2020

Non-breaking changes and improvements:

- Improve EOF Exceptions (`#2115 <https://github.com/vyperlang/vyper/pull/2115>`_)
- Improve exception messaging for type mismatches (`#2119 <https://github.com/vyperlang/vyper/pull/2119>`_)
- Ignore trailing newline tokens (`#2120 <https://github.com/vyperlang/vyper/pull/2120>`_)

Fixes:

- Fix ABI translations for structs that are returned from functions (`#2114 <https://github.com/vyperlang/vyper/pull/2114>`_)
- Raise when items that are not types are called (`#2118 <https://github.com/vyperlang/vyper/pull/2118>`_)
- Ensure hex and decimal AST nodes are serializable (`#2123 <https://github.com/vyperlang/vyper/pull/2123>`_)

v0.2.3
******

Date released: 16-07-2020

Non-breaking changes and improvements:

- Show contract names in raised exceptions (`#2103 <https://github.com/vyperlang/vyper/pull/2103>`_)
- Adjust function offsets to not include decorators (`#2102 <https://github.com/vyperlang/vyper/pull/2102>`_)
- Raise certain exception types immediately during module-scoped type checking (`#2101 <https://github.com/vyperlang/vyper/pull/2101>`_)

Fixes:

- Pop ``for`` loop values from stack prior to returning (`#2110 <https://github.com/vyperlang/vyper/pull/2110>`_)
- Type checking non-literal array index values (`#2108 <https://github.com/vyperlang/vyper/pull/2108>`_)
- Meaningful output during ``for`` loop type checking (`#2096 <https://github.com/vyperlang/vyper/pull/2096>`_)

v0.2.2
******

Date released: 04-07-2020

Fixes:

- Do not fold exponentiation to a negative power (`#2089 <https://github.com/vyperlang/vyper/pull/2089>`_)
- Add repr for mappings (`#2090 <https://github.com/vyperlang/vyper/pull/2090>`_)
- Literals are only validated once (`#2093 <https://github.com/vyperlang/vyper/pull/2093>`_)

v0.2.1
******

Date released: 03-07-2020

This is a major breaking release of the Vyper compiler and language. It is also the first release following our versioning scheme (`#1887 <https://github.com/vyperlang/vyper/issues/1887>`_).

Breaking changes:

- ``@public`` and ``@private`` function decorators have been renamed to ``@external`` and ``@internal`` (VIP `#2065 <https://github.com/vyperlang/vyper/issues/2065>`_)
- The ``@constant`` decorator has been renamed to ``@view`` (VIP `#2040 <https://github.com/vyperlang/vyper/issues/2040>`_)
- Type units have been removed (VIP `#1881 <https://github.com/vyperlang/vyper/issues/1881>`_)
- Event declaration syntax now resembles that of struct declarations (VIP `#1864 <https://github.com/vyperlang/vyper/issues/1864>`_)
- ``log`` is now a statement (VIP `#1864 <https://github.com/vyperlang/vyper/issues/1864>`_)
- Mapping declaration syntax changed to ``HashMap[key_type, value_type]`` (VIP `#1969 <https://github.com/vyperlang/vyper/issues/1969>`_)
- Interfaces are now declared via the ``interface`` keyword instead of ``contract`` (VIP `#1825 <https://github.com/vyperlang/vyper/issues/1825>`_)
- ``bytes`` and ``string`` types are now written as ``Bytes`` and ``String`` (`#2080 <https://github.com/vyperlang/vyper/pull/2080>`_)
- ``bytes`` and ``string`` literals must now be bytes or regular strings, respectively. They are no longer interchangeable. (VIP `#1876 <https://github.com/vyperlang/vyper/issues/1876>`_)
- ``assert_modifiable`` has been removed, you can now directly perform assertions on calls (`#2050 <https://github.com/vyperlang/vyper/pull/2050>`_)
- ``value`` is no longer an allowable variable name in a function input (VIP `#1877 <https://github.com/vyperlang/vyper/issues/1877>`_)
- The ``slice`` builtin function expects ``uint256`` for the ``start`` and ``length`` args (VIP `#1986 <https://github.com/vyperlang/vyper/issues/1986>`_)
- ``len`` return type is now ``uint256`` (VIP `#1979 <https://github.com/vyperlang/vyper/issues/1979>`_)
- ``value`` and ``gas`` kwargs for external function calls must be given as ``uint256`` (VIP `#1878 <https://github.com/vyperlang/vyper/issues/1878>`_)
- The ``outsize`` kwarg in ``raw_call`` has been renamed to ``max_outsize`` (`#1977 <https://github.com/vyperlang/vyper/pull/1977>`_)
- The ``type`` kwarg in ``extract32`` has been renamed to ``output_type`` (`#2036 <https://github.com/vyperlang/vyper/pull/2036>`_)
- Public array getters now use ``uint256`` for their input argument(s) (VIP `#1983 <https://github.com/vyperlang/vyper/issues/1983>`_)
- Public struct getters now return all values of a struct (`#2064 <https://github.com/vyperlang/vyper/pull/2064>`_)
- ``RLPList`` has been removed (VIP `#1866 <https://github.com/vyperlang/vyper/issues/1866>`_)


The following non-breaking VIPs and features were implemented:

- Implement boolean condition short circuiting (VIP `#1817 <https://github.com/vyperlang/vyper/issues/1817>`_)
- Add the ``empty`` builtin function for zero-ing a value (`#1676 <https://github.com/vyperlang/vyper/pull/1676>`_)
- Refactor of the compiler process resulting in an almost 5x performance boost! (`#1962 <https://github.com/vyperlang/vyper/pull/1962>`_)
- Support ABI State Mutability Fields in Interface Definitions (VIP `#2042 <https://github.com/vyperlang/vyper/issues/2042>`_)
- Support ``@pure`` decorator (VIP `#2041 <https://github.com/vyperlang/vyper/issues/2041>`_)
- Overflow checks for exponentiation (`#2072 <https://github.com/vyperlang/vyper/pull/2072>`_)
- Validate return data length via ``RETURNDATASIZE`` (`#2076 <https://github.com/vyperlang/vyper/pull/2076>`_)
- Improved constant folding (`#1949 <https://github.com/vyperlang/vyper/pull/1949>`_)
- Allow raise without reason string (VIP `#1902 <https://github.com/vyperlang/vyper/issues/1902>`_)
- Make the type argument in ``method_id`` optional (VIP `#1980 <https://github.com/vyperlang/vyper/issues/1980>`_)
- Hash complex types when used as indexed values in an event (`#2060 <https://github.com/vyperlang/vyper/pull/2060>`_)
- Ease restrictions on calls to self (`#2059 <https://github.com/vyperlang/vyper/pull/2059>`_)
- Remove ordering restrictions in module-scope of contract (`#2057 <https://github.com/vyperlang/vyper/pull/2057>`_)
- ``raw_call`` can now be used to perform a ``STATICCALL`` (`#1973 <https://github.com/vyperlang/vyper/pull/1973>`_)
- Optimize precompiles to use ``STATICCALL`` (`#1930 <https://github.com/vyperlang/vyper/pull/1930>`_)

Some of the bug and stability fixes:

- Arg clamping issue when using multidimensional arrays (`#2071 <https://github.com/vyperlang/vyper/pull/2071>`_)
- Support calldata arrays with the ``in`` comparator (`#2070 <https://github.com/vyperlang/vyper/pull/2070>`_)
- Prevent modification of a storage array during iteration via ``for`` loop (`#2028 <https://github.com/vyperlang/vyper/pull/2028>`_)
- Fix memory length of revert string (`#1982 <https://github.com/vyperlang/vyper/pull/1982>`_)
- Memory offset issue when returning tuples from private functions (`#1968 <https://github.com/vyperlang/vyper/pull/1968>`_)
- Issue with arrays as default function arguments (`#2077 <https://github.com/vyperlang/vyper/pull/2077>`_)
- Private function calls no longer generate a call signature (`#2058 <https://github.com/vyperlang/vyper/pull/2058>`_)

Significant codebase refactor, thanks to (`@iamdefinitelyahuman <https://github.com/iamdefinitelyahuman>`_)!

**NOTE**: ``v0.2.0`` was not used due to a conflict in PyPI with a previous release. Both tags ``v0.2.0`` and ``v0.2.1`` are identical.

v0.1.0-beta.17
**************

Date released: 24-03-2020

The following VIPs and features were implemented for Beta 17:

- ``raw_call`` and ``slice`` argument updates (VIP `#1879 <https://github.com/vyperlang/vyper/issues/1879>`_)
- NatSpec support (`#1898 <https://github.com/vyperlang/vyper/pull/1898>`_)

Some of the bug and stability fixes:

- ABI interface fixes (`#1842 <https://github.com/vyperlang/vyper/pull/1842>`_)
- Modifications to how ABI data types are represented (`#1846 <https://github.com/vyperlang/vyper/pull/1846>`_)
- Generate method identifier for struct return type (`#1843 <https://github.com/vyperlang/vyper/pull/1843>`_)
- Return tuple with fixed array fails to compile (`#1838 <https://github.com/vyperlang/vyper/pull/1838>`_)
- Also lots of refactoring and doc updates!

This release will be the last to follow our current release process.
All future releases will be governed by the versioning scheme (`#1887 <https://github.com/vyperlang/vyper/issues/1887>`_).
The next release will be v0.2.0, and contain many breaking changes.


v0.1.0-beta.16
**************

Date released: 09-01-2020

Beta 16 was a quick patch release to fix one issue: (`#1829 <https://github.com/vyperlang/vyper/pull/1829>`_)

v0.1.0-beta.15
**************

Date released: 06-01-2020

**NOTE**: we changed our license to Apache 2.0 (`#1772 <https://github.com/vyperlang/vyper/pull/1772>`_)

The following VIPs were implemented for Beta 15:

- EVM Ruleset Switch (VIP `#1230 <https://github.com/vyperlang/vyper/issues/1230>`_)
- Add support for `EIP-1344 <https://eips.ethereum.org/EIPS/eip-1344>`_, Chain ID Opcode (VIP `#1652 <https://github.com/vyperlang/vyper/issues/1652>`_)
- Support for `EIP-1052 <https://eips.ethereum.org/EIPS/eip-1052>`_, ``EXTCODEHASH`` (VIP `#1765 <https://github.com/vyperlang/vyper/issues/1765>`_)

Some of the bug and stability fixes:

- Removed all traces of Javascript from the codebase (`#1770 <https://github.com/vyperlang/vyper/pull/1770>`_)
- Ensured sufficient gas stipend for precompiled calls (`#1771 <https://github.com/vyperlang/vyper/pull/1771>`_)
- Allow importing an interface that contains an ``implements`` statement (`#1774 <https://github.com/vyperlang/vyper/pull/1774>`_)
- Fixed how certain values compared when using ``min`` and ``max`` (`#1790 <https://github.com/vyperlang/vyper/pull/1790>`_)
- Removed unnecessary overflow checks on ``addmod`` and ``mulmod`` (`#1786 <https://github.com/vyperlang/vyper/pull/1786>`_)
- Check for state modification when using tuples (`#1785 <https://github.com/vyperlang/vyper/pull/1785>`_)
- Fix Windows path issue when importing interfaces (`#1781 <https://github.com/vyperlang/vyper/pull/1781>`_)
- Added Vyper grammar, currently used for fuzzing (`#1768 <https://github.com/vyperlang/vyper/pull/1768>`_)
- Modify modulus calculations for literals to be consistent with the EVM (`#1792 <https://github.com/vyperlang/vyper/pull/1792>`_)
- Explicitly disallow the use of exponentiation on decimal values (`#1792 <https://github.com/vyperlang/vyper/pull/1792>`_)
- Add compile-time checks for divide by zero and modulo by zero (`#1792 <https://github.com/vyperlang/vyper/pull/1792>`_)
- Fixed some issues with negating constants (`#1791 <https://github.com/vyperlang/vyper/pull/1791>`_)
- Allow relative imports beyond one parent level (`#1784 <https://github.com/vyperlang/vyper/pull/1784>`_)
- Implement SHL/SHR for bitshifting, using Constantinople rules (`#1796 <https://github.com/vyperlang/vyper/pull/1796>`_)
- ``vyper-json`` compatibility with ``solc`` settings (`#1795 <https://github.com/vyperlang/vyper/pull/1795>`_)
- Simplify the type check when returning lists (`#1797 <https://github.com/vyperlang/vyper/pull/1797>`_)
- Add branch coverage reporting (`#1743 <https://github.com/vyperlang/vyper/pull/1743>`_)
- Fix struct assignment order (`#1728 <https://github.com/vyperlang/vyper/pull/1728>`_)
- Added more words to reserved keyword list (`#1741 <https://github.com/vyperlang/vyper/pull/1741>`_)
- Allow scientific notation for literals (`#1721 <https://github.com/vyperlang/vyper/pull/1721>`_)
- Avoid overflow on sqrt of Decimal upper bound (`#1679 <https://github.com/vyperlang/vyper/pull/1679>`_)
- Refactor ABI encoder (`#1723 <https://github.com/vyperlang/vyper/pull/1723>`_)
- Changed opcode costs per `EIP-1884 <https://eips.ethereum.org/EIPS/eip-1884>`_ (`#1764 <https://github.com/vyperlang/vyper/pull/1764>`_)

Special thanks to (`@iamdefinitelyahuman <https://github.com/iamdefinitelyahuman>`_) for lots of updates this release!

v0.1.0-beta.14
**************

Date released: 13-11-2019

Some of the bug and stability fixes:

- Mucho Documentation and Example cleanup!
- Python 3.8 support (`#1678 <https://github.com/vyperlang/vyper/pull/1678>`_)
- Disallow scientific notation in literals, which previously parsed incorrectly (`#1681 <https://github.com/vyperlang/vyper/pull/1681>`_)
- Add implicit rewrite rule for ``bytes[32]`` -> ``bytes32`` (`#1718 <https://github.com/vyperlang/vyper/pull/1718>`_)
- Support ``bytes32`` in ``raw_log`` (`#1719 <https://github.com/vyperlang/vyper/pull/1719>`_)
- Fixed EOF parsing bug (`#1720 <https://github.com/vyperlang/vyper/pull/1720>`_)
- Cleaned up arithmetic expressions (`#1661 <https://github.com/vyperlang/vyper/pull/1661>`_)
- Fixed off-by-one in check for homogeneous list element types (`#1673 <https://github.com/vyperlang/vyper/pull/1673>`_)
- Fixed stack valency issues in if and for statements (`#1665 <https://github.com/vyperlang/vyper/pull/1665>`_)
- Prevent overflow when using ``sqrt`` on certain datatypes (`#1679 <https://github.com/vyperlang/vyper/pull/1679>`_)
- Prevent shadowing of internal variables (`#1601 <https://github.com/vyperlang/vyper/pull/1601>`_)
- Reject unary subtraction on unsigned types  (`#1638 <https://github.com/vyperlang/vyper/pull/1638>`_)
- Disallow ``orelse`` syntax in ``for`` loops (`#1633 <https://github.com/vyperlang/vyper/pull/1633>`_)
- Increased clarity and efficiency of zero-padding (`#1605 <https://github.com/vyperlang/vyper/pull/1605>`_)

v0.1.0-beta.13
**************

Date released: 27-09-2019

The following VIPs were implemented for Beta 13:

- Add ``vyper-json`` compilation mode (VIP `#1520 <https://github.com/vyperlang/vyper/issues/1520>`_)
- Environment variables and constants can now be used as default parameters (VIP `#1525 <https://github.com/vyperlang/vyper/issues/1525>`_)
- Require uninitialized memory be set on creation (VIP `#1493 <https://github.com/vyperlang/vyper/issues/1493>`_)

Some of the bug and stability fixes:

- Type check for default params and arrays (`#1596 <https://github.com/vyperlang/vyper/pull/1596>`_)
- Fixed bug when using assertions inside for loops (`#1619 <https://github.com/vyperlang/vyper/pull/1619>`_)
- Fixed zero padding error for ABI encoder (`#1611 <https://github.com/vyperlang/vyper/pull/1611>`_)
- Check ``calldatasize`` before ``calldataload`` for function selector (`#1606 <https://github.com/vyperlang/vyper/pull/1606>`_)

v0.1.0-beta.12
**************

Date released: 27-08-2019

The following VIPs were implemented for Beta 12:

- Support for relative imports (VIP `#1367 <https://github.com/vyperlang/vyper/issues/1367>`_)
- Restricted use of environment variables in private functions (VIP `#1199 <https://github.com/vyperlang/vyper/issues/1199>`_)

Some of the bug and stability fixes:

- ``@nonreentrant``/``@constant`` logical inconsistency (`#1544 <https://github.com/vyperlang/vyper/issues/1544>`_)
- Struct passthrough issue (`#1551 <https://github.com/vyperlang/vyper/issues/1551>`_)
- Private underflow issue (`#1470 <https://github.com/vyperlang/vyper/pull/1470>`_)
- Constancy check issue (`#1480 <https://github.com/vyperlang/vyper/pull/1480>`_)
- Prevent use of conflicting method IDs (`#1530 <https://github.com/vyperlang/vyper/pull/1530>`_)
- Missing arg check for private functions (`#1579 <https://github.com/vyperlang/vyper/pull/1579>`_)
- Zero padding issue (`#1563 <https://github.com/vyperlang/vyper/issues/1563>`_)
- ``vyper.cli`` rearchitecture of scripts (`#1574 <https://github.com/vyperlang/vyper/issues/1574>`_)
- AST end offsets and Solidity-compatible compressed sourcemap (`#1580 <https://github.com/vyperlang/vyper/pull/1580>`_)

Special thanks to (`@iamdefinitelyahuman <https://github.com/iamdefinitelyahuman>`_) for lots of updates this release!

v0.1.0-beta.11
**************

Date released: 23-07-2019

Beta 11 brings some performance and stability fixes.

- Using calldata instead of memory parameters. (`#1499 <https://github.com/vyperlang/vyper/pull/1499>`_)
- Reducing of contract size, for large parameter functions. (`#1486 <https://github.com/vyperlang/vyper/pull/1486>`_)
- Improvements for Windows users (`#1486 <https://github.com/vyperlang/vyper/pull/1486>`_)  (`#1488 <https://github.com/vyperlang/vyper/pull/1488>`_)
- Array copy optimisation (`#1487 <https://github.com/vyperlang/vyper/pull/1487>`_)
- Fixing ``@nonreentrant`` decorator for return statements (`#1532 <https://github.com/vyperlang/vyper/pull/1532>`_)
- ``sha3`` builtin function removed  (`#1328 <https://github.com/vyperlang/vyper/issues/1328>`_)
- Disallow conflicting method IDs (`#1530 <https://github.com/vyperlang/vyper/pull/1530>`_)
- Additional ``convert()`` supported types (`#1524 <https://github.com/vyperlang/vyper/pull/1524>`_) (`#1500 <https://github.com/vyperlang/vyper/pull/1500>`_)
- Equality operator for strings and bytes (`#1507 <https://github.com/vyperlang/vyper/pull/1507>`_)
- Change in ``compile_codes`` interface function (`#1504 <https://github.com/vyperlang/vyper/pull/1504>`_)

Thanks to all the contributors!

v0.1.0-beta.10
**************

Date released: 24-05-2019

- Lots of linting and refactoring!
- Bugfix with regards to using arrays as parameters to private functions (`#1418 <https://github.com/vyperlang/vyper/issues/1418>`_). Please check your contracts, and upgrade to latest version, if you do use this.
- Slight shrinking in init produced bytecode. (`#1399 <https://github.com/vyperlang/vyper/issues/1399>`_)
- Additional constancy protection in the ``for .. range`` expression. (`#1397 <https://github.com/vyperlang/vyper/issues/1397>`_)
- Improved bug report (`#1394 <https://github.com/vyperlang/vyper/issues/1394>`_)
- Fix returning of External Contract from functions (`#1376 <https://github.com/vyperlang/vyper/issues/1376>`_)
- Interface unit fix (`#1303 <https://github.com/vyperlang/vyper/issues/1303>`_)
- Not Equal (!=) optimisation (`#1303 <https://github.com/vyperlang/vyper/issues/1303>`_) 1386
- New ``assert <condition>, UNREACHABLE`` statement. (`#711 <https://github.com/vyperlang/vyper/issues/711>`_)

Special thanks to (`Charles Cooper <https://github.com/charles-cooper>`_), for some excellent contributions this release.

v0.1.0-beta.9
*************

Date released: 12-03-2019

- Add support for list constants (`#1211 <https://github.com/vyperlang/vyper/issues/1211>`_)
- Add ``sha256`` function (`#1327 <https://github.com/vyperlang/vyper/issues/1327>`_)
- Renamed ``create_with_code_of`` to ``create_forwarder_to`` (`#1177 <https://github.com/vyperlang/vyper/issues/1177>`_)
- ``@nonreentrant`` Decorator  (`#1204 <https://github.com/vyperlang/vyper/issues/1204>`_)
- Add opcodes and opcodes_runtime flags to compiler (`#1255 <https://github.com/vyperlang/vyper/pull/1255>`_)
- Improved External contract call interfaces (`#885 <https://github.com/vyperlang/vyper/issues/885>`_)

Prior to v0.1.0-beta.9
**********************

Prior to this release, we managed our change log in a different fashion.
Here is the old changelog:

* **2019.04.05**: Add stricter checking of unbalanced return statements. (`#590 <https://github.com/vyperlang/vyper/issues/590>`_)
* **2019.03.04**: ``create_with_code_of`` has been renamed to ``create_forwarder_to``. (`#1177 <https://github.com/vyperlang/vyper/issues/1177>`_)
* **2019.02.14**: Assigning a persistent contract address can only be done using the ``bar_contact = ERC20(<address>)`` syntax.
* **2019.02.12**: ERC20 interface has to be imported using ``from vyper.interfaces import ERC20`` to use.
* **2019.01.30**: Byte array literals need to be annotated using ``b""``, strings are represented as `""`.
* **2018.12.12**: Disallow use of ``None``, disallow use of ``del``, implemented ``clear()`` built-in function.
* **2018.11.19**: Change mapping syntax to use ``map()``. (`VIP564 <https://github.com/vyperlang/vyper/issues/564>`_)
* **2018.10.02**: Change the convert style to use types instead of string. (`VIP1026 <https://github.com/vyperlang/vyper/issues/1026>`_)
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
* **2018.01.04**: Types need to be specified on assignment (`VIP545 <https://github.com/vyperlang/vyper/issues/545>`_).
* **2017.01.02** Change ``as_wei_value`` to use quotes for units.
* **2017.12.25**: Change name from Viper to Vyper.
* **2017.12.22**: Add ``continue`` for loops
* **2017.11.29**: ``@internal`` renamed to ``@private``.
* **2017.11.15**: Functions require either ``@internal`` or ``@public`` decorators.
* **2017.07.25**: The ``def foo() -> num(const): ...`` syntax no longer works; you now need to do ``def foo() -> num: ...`` with a ``@constant`` decorator on the previous line.
* **2017.07.25**: Functions without a ``@payable`` decorator now fail when called with nonzero wei.
* **2017.07.25**: A function can only call functions that are declared above it (that is, A can call B only if B appears earlier in the code than A does). This was introduced
