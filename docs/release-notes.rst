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
    remove authorship slugs (leave them on github release page; they have no meaning outside of github though)
    :'<,'>s/by @\S\+ //c
    for advisory links:
    :'<,'>s/\v(https:\/\/github.com\/vyperlang\/vyper\/security\/advisories\/)([-A-Za-z0-9]+)/(`\2 <\1\2>`_)/g

v0.4.1 ("Tokara Habu")
**********************

Date released: 2025-03-01
=========================

v0.4.1 is primarily a polishing release, focusing on bug fixes, UX improvements, and security-related fixes (with four low-to-moderate severity GHSA reports published). However, a substantial amount of effort has also been invested in improving the Venom pipeline, resulting in better performance and code generation from the Venom pipeline. Venom can be enabled by passing the ``--venom`` or ``--experimental-codegen`` flag to the Vyper compiler (they are aliases of each other). Venom code can now also be compiled directly, using the ``venom`` binary (included in this release).

Breaking changes
----------------
* feat[lang]!: make ``@external`` modifier optional in ``.vyi`` files (`#4178 <https://github.com/vyperlang/vyper/pull/4178>`_)
* feat[codegen]!: check ``returndatasize`` even when ``skip_contract_check`` is set (`#4148 <https://github.com/vyperlang/vyper/pull/4148>`_)
* fix[stdlib]!: fix ``IERC4626`` signatures (`#4425 <https://github.com/vyperlang/vyper/pull/4425>`_)
* fix[lang]!: disallow absolute relative imports (`#4268 <https://github.com/vyperlang/vyper/pull/4268>`_)

Other new features and improvements
-----------------------------------
* feat[lang]: add ``module.__at__()`` to cast to interface (`#4090 <https://github.com/vyperlang/vyper/pull/4090>`_)
* feat[lang]: use keyword arguments for event instantiation (`#4257 <https://github.com/vyperlang/vyper/pull/4257>`_)
* feat[lang]: add native hex string literals (`#4271 <https://github.com/vyperlang/vyper/pull/4271>`_)
* feat[lang]: introduce ``mana`` as an alias for ``gas`` (`#3713 <https://github.com/vyperlang/vyper/pull/3713>`_)
* feat[lang]: support top level ``"abi"`` key in json interfaces (`#4279 <https://github.com/vyperlang/vyper/pull/4279>`_)
* feat[lang]: support flags from imported interfaces (`#4253 <https://github.com/vyperlang/vyper/pull/4253>`_)
* feat[ux]: allow "compiling" ``.vyi`` files (`#4290 <https://github.com/vyperlang/vyper/pull/4290>`_)
* feat[ux]: improve hint for events kwarg upgrade (`#4275 <https://github.com/vyperlang/vyper/pull/4275>`_)

Tooling / CLI
-------------
* feat[tool]: add ``-Werror`` and ``-Wnone`` options (`#4447 <https://github.com/vyperlang/vyper/pull/4447>`_)
* feat[tool]: support storage layouts via ``json`` and ``.vyz`` inputs (`#4370 <https://github.com/vyperlang/vyper/pull/4370>`_)
* feat[tool]: add integrity hash to initcode (`#4234 <https://github.com/vyperlang/vyper/pull/4234>`_)
* fix[ci]: fix commithash calculation for pypi release (`#4309 <https://github.com/vyperlang/vyper/pull/4309>`_)
* fix[tool]: include structs in ``-f interface`` output (`#4294 <https://github.com/vyperlang/vyper/pull/4294>`_)
* feat[tool]: separate import resolution pass (`#4229 <https://github.com/vyperlang/vyper/pull/4229>`_)
* feat[tool]: add all imported modules to ``-f annotated_ast`` output (`#4209 <https://github.com/vyperlang/vyper/pull/4209>`_)
* fix[tool]: add missing internal functions to metadata (`#4328 <https://github.com/vyperlang/vyper/pull/4328>`_)
* fix[tool]: update VarAccess pickle implementation (`#4270 <https://github.com/vyperlang/vyper/pull/4270>`_)
* fix[tool]: fix output formats for .vyz files (`#4338 <https://github.com/vyperlang/vyper/pull/4338>`_)
* fix[tool]: add missing user errors to error map  (`#4286 <https://github.com/vyperlang/vyper/pull/4286>`_)
* fix[ci]: fix README encoding in ``setup.py`` (`#4348 <https://github.com/vyperlang/vyper/pull/4348>`_)
* refactor[tool]: refactor ``compile_from_zip()`` (`#4366 <https://github.com/vyperlang/vyper/pull/4366>`_)

Bugfixes
--------
* fix[lang]: add ``raw_log()`` constancy check (`#4201 <https://github.com/vyperlang/vyper/pull/4201>`_)
* fix[lang]: use folded node for typechecking (`#4365 <https://github.com/vyperlang/vyper/pull/4365>`_)
* fix[ux]: fix error message for "staticall" typo (`#4438 <https://github.com/vyperlang/vyper/pull/4438>`_)
* fix[lang]: fix certain varinfo comparisons (`#4164 <https://github.com/vyperlang/vyper/pull/4164>`_)
* fix[codegen]: fix ``abi_encode`` buffer size in external calls (`#4202 <https://github.com/vyperlang/vyper/pull/4202>`_)
* fix[lang]: fix ``==`` and ``!=`` bytesM folding (`#4254 <https://github.com/vyperlang/vyper/pull/4254>`_)
* fix[lang]: fix ``.vyi`` function body check (`#4177 <https://github.com/vyperlang/vyper/pull/4177>`_)
* fix[venom]: invalid jump error (`#4214 <https://github.com/vyperlang/vyper/pull/4214>`_)
* fix[lang]: fix precedence in floordiv hint (`#4203 <https://github.com/vyperlang/vyper/pull/4203>`_)
* fix[lang]: define rounding mode for sqrt (`#4486 <https://github.com/vyperlang/vyper/pull/4486>`_)
* fix[codegen]: disable augassign with overlap (`#4487 <https://github.com/vyperlang/vyper/pull/4487>`_)
* fix[codegen]: relax the filter for augassign oob check (`#4497 <https://github.com/vyperlang/vyper/pull/4497>`_)
* fix[lang]: fix panic in call cycle detection (`#4200 <https://github.com/vyperlang/vyper/pull/4200>`_)
* fix[tool]: update ``InterfaceT.__str__`` implementation (`#4205 <https://github.com/vyperlang/vyper/pull/4205>`_)
* fix[tool]: fix classification of AST nodes (`#4210 <https://github.com/vyperlang/vyper/pull/4210>`_)
* fix[tool]: keep ``experimentalCodegen`` blank in standard json input (`#4216 <https://github.com/vyperlang/vyper/pull/4216>`_)
* fix[ux]: fix relpath compiler panic on windows (`#4228 <https://github.com/vyperlang/vyper/pull/4228>`_)
* fix[ux]: fix empty hints in error messages (`#4351 <https://github.com/vyperlang/vyper/pull/4351>`_)
* fix[ux]: fix validation for ``abi_encode()`` ``method_id`` kwarg (`#4369 <https://github.com/vyperlang/vyper/pull/4369>`_)
* fix[ux]: fix false positive for overflow in type checker (`#4385 <https://github.com/vyperlang/vyper/pull/4385>`_)
* fix[ux]: add missing filename to syntax exceptions (`#4343 <https://github.com/vyperlang/vyper/pull/4343>`_)
* fix[ux]: improve error message on failed imports (`#4409 <https://github.com/vyperlang/vyper/pull/4409>`_)
* fix[parser]: fix bad tokenization of hex strings (`#4406 <https://github.com/vyperlang/vyper/pull/4406>`_)
* fix[lang]: fix encoding of string literals (`#3091 <https://github.com/vyperlang/vyper/pull/3091>`_)
* fix[codegen]: fix assertions for certain precompiles (`#4451 <https://github.com/vyperlang/vyper/pull/4451>`_)
* fix[lang]: allow ``print()`` schema larger than 32 bytes (`#4456 <https://github.com/vyperlang/vyper/pull/4456>`_)
* fix[codegen]: fix iteration over constant literals (`#4462 <https://github.com/vyperlang/vyper/pull/4462>`_)
* fix[codegen]: fix gas usage of iterators (`#4485 <https://github.com/vyperlang/vyper/pull/4485>`_)
* fix[codegen]: cache result of iter eval (`#4488 <https://github.com/vyperlang/vyper/pull/4488>`_)
* fix[lang]: fix recursive interface imports (`#4303 <https://github.com/vyperlang/vyper/pull/4303>`_)
* fix[tool]: roll back OS used to build binaries (`#4494 <https://github.com/vyperlang/vyper/pull/4494>`_)

Patched security advisories (GHSAs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
* success of certain precompiles not checked (`GHSA-vgf2-gvx8-xwc3 <https://github.com/vyperlang/vyper/security/advisories/GHSA-vgf2-gvx8-xwc3>`_)
* AugAssign evaluation order causing OOB write within object (`GHSA-4w26-8p97-f4jp <https://github.com/vyperlang/vyper/security/advisories/GHSA-4w26-8p97-f4jp>`_)
* ``sqrt`` doesn't define rounding behavior (`GHSA-2p94-8669-xg86 <https://github.com/vyperlang/vyper/security/advisories/GHSA-2p94-8669-xg86>`_)
* multiple eval in ``for`` list iterator (`GHSA-h33q-mhmp-8p67 <https://github.com/vyperlang/vyper/security/advisories/GHSA-h33q-mhmp-8p67>`_)

Venom improvements
------------------
* feat[venom]: add venom parser (`#4381 <https://github.com/vyperlang/vyper/pull/4381>`_)
* feat[venom]: new ``DFTPass`` algorithm (`#4255 <https://github.com/vyperlang/vyper/pull/4255>`_)
* feat[venom]: only ``stack_reorder`` before join points (`#4247 <https://github.com/vyperlang/vyper/pull/4247>`_)
* feat[venom]: add function inliner (`#4478 <https://github.com/vyperlang/vyper/pull/4478>`_)
* feat[venom]: add binop optimizations (`#4281 <https://github.com/vyperlang/vyper/pull/4281>`_)
* feat[venom]: offset instruction (`#4180 <https://github.com/vyperlang/vyper/pull/4180>`_)
* feat[venom]: make dft-pass commutative aware (`#4358 <https://github.com/vyperlang/vyper/pull/4358>`_)
* perf[venom]: add ``OrderedSet.last()`` (`#4236 <https://github.com/vyperlang/vyper/pull/4236>`_)
* feat[venom]: improve liveness computation time (`#4086 <https://github.com/vyperlang/vyper/pull/4086>`_)
* fix[venom]: fix invalid ``phi``s after SCCP (`#4181 <https://github.com/vyperlang/vyper/pull/4181>`_)
* fix[venom]: clean up sccp pass (`#4261 <https://github.com/vyperlang/vyper/pull/4261>`_)
* refactor[venom]: remove ``dup_requirements`` analysis (`#4262 <https://github.com/vyperlang/vyper/pull/4262>`_)
* fix[venom]: remove duplicate volatile instructions (`#4263 <https://github.com/vyperlang/vyper/pull/4263>`_)
* fix[venom]: fix ``_stack_reorder()`` routine (`#4220 <https://github.com/vyperlang/vyper/pull/4220>`_)
* feat[venom]: store expansion pass (`#4068 <https://github.com/vyperlang/vyper/pull/4068>`_)
* feat[venom]: add effects to instructions (`#4264 <https://github.com/vyperlang/vyper/pull/4264>`_)
* feat[venom]: add small heuristic for cleaning input stack (`#4251 <https://github.com/vyperlang/vyper/pull/4251>`_)
* refactor[venom]: refactor module structure (`#4295 <https://github.com/vyperlang/vyper/pull/4295>`_)
* refactor[venom]: refactor sccp pass to use dfg (`#4329 <https://github.com/vyperlang/vyper/pull/4329>`_)
* refactor[venom]: update translator for ``deploy`` instruction (`#4318 <https://github.com/vyperlang/vyper/pull/4318>`_)
* feat[venom]: make cfg scheduler "stack aware" (`#4356 <https://github.com/vyperlang/vyper/pull/4356>`_)
* feat[venom]: improve liveness computation (`#4330 <https://github.com/vyperlang/vyper/pull/4330>`_)
* refactor[venom]: optimize lattice evaluation (`#4368 <https://github.com/vyperlang/vyper/pull/4368>`_)
* perf[venom]: improve OrderedSet operations (`#4246 <https://github.com/vyperlang/vyper/pull/4246>`_)
* fix[venom]: promote additional memory locations to variables (`#4039 <https://github.com/vyperlang/vyper/pull/4039>`_)
* feat[venom]: add codesize optimization pass (`#4333 <https://github.com/vyperlang/vyper/pull/4333>`_)
* fix[venom]: fix unused variables pass (`#4259 <https://github.com/vyperlang/vyper/pull/4259>`_)
* refactor[venom]: move commutative instruction set (`#4307 <https://github.com/vyperlang/vyper/pull/4307>`_)
* fix[venom]: add ``make_ssa`` pass after algebraic optimizations (`#4292 <https://github.com/vyperlang/vyper/pull/4292>`_)
* feat[venom]: reduce legacy opts when venom is enabled (`#4336 <https://github.com/vyperlang/vyper/pull/4336>`_)
* fix[venom]: fix duplicate allocas (`#4321 <https://github.com/vyperlang/vyper/pull/4321>`_)
* fix[venom]: add missing extcodesize+hash effects (`#4373 <https://github.com/vyperlang/vyper/pull/4373>`_)
* refactor[ux]: add ``venom`` as ``experimental-codegen`` alias (`#4337 <https://github.com/vyperlang/vyper/pull/4337>`_)
* feat[venom]: allow alphanumeric variables and source comments (`#4403 <https://github.com/vyperlang/vyper/pull/4403>`_)
* feat[venom]: cleanup variable version handling (`#4404 <https://github.com/vyperlang/vyper/pull/4404>`_)
* feat[venom]: merge memory writes (`#4341 <https://github.com/vyperlang/vyper/pull/4341>`_)
* refactor[venom]: make venom repr parseable (`#4402 <https://github.com/vyperlang/vyper/pull/4402>`_)
* feat[venom]: propagate ``dload`` instruction to venom (`#4410 <https://github.com/vyperlang/vyper/pull/4410>`_)
* feat[venom]: remove special cases in store elimination (`#4413 <https://github.com/vyperlang/vyper/pull/4413>`_)
* feat[venom]: update text format for data section (`#4414 <https://github.com/vyperlang/vyper/pull/4414>`_)
* feat[venom]: add load elimination pass (`#4265 <https://github.com/vyperlang/vyper/pull/4265>`_)
* fix[venom]: fix ``MakeSSA`` with existing phis (`#4423 <https://github.com/vyperlang/vyper/pull/4423>`_)
* refactor[venom]: refactor mem2var (`#4421 <https://github.com/vyperlang/vyper/pull/4421>`_)
* fix[venom]: fix store elimination pass (`#4428 <https://github.com/vyperlang/vyper/pull/4428>`_)
* refactor[venom]: add ``make_nop()`` helper function (`#4470 <https://github.com/vyperlang/vyper/pull/4470>`_)
* feat[venom]: improve load elimination (`#4407 <https://github.com/vyperlang/vyper/pull/4407>`_)
* refactor[venom]: replace ``bb.mark_for_removal`` with ``make_nop`` (`#4474 <https://github.com/vyperlang/vyper/pull/4474>`_)

Docs
----
* chore[docs]: add ``method_id`` to ``abi_encode`` signature (`#4355 <https://github.com/vyperlang/vyper/pull/4355>`_)
* chore[docs]: mention the ``--venom`` flag in venom docs (`#4353 <https://github.com/vyperlang/vyper/pull/4353>`_)
* feat[docs]: add bug bounty program to security policy (`#4230 <https://github.com/vyperlang/vyper/pull/4230>`_)
* feat[docs]: add installation via pipx and uv (`#4274 <https://github.com/vyperlang/vyper/pull/4274>`_)
* chore[docs]: add binary installation methods (`#4258 <https://github.com/vyperlang/vyper/pull/4258>`_)
* chore[docs]: update ``sourceMap`` field descriptions (`#4170 <https://github.com/vyperlang/vyper/pull/4170>`_)
* chore[docs]: remove experimental note for cancun (`#4183 <https://github.com/vyperlang/vyper/pull/4183>`_)
* chore[venom]: expand venom docs (`#4314 <https://github.com/vyperlang/vyper/pull/4314>`_)
* chore[docs]: abi function signature for default arguments (`#4415 <https://github.com/vyperlang/vyper/pull/4415>`_)
* feat[docs]: add Telegram badge to README.md (`#4342 <https://github.com/vyperlang/vyper/pull/4342>`_)
* chore[docs]: update readme about testing (`#4448 <https://github.com/vyperlang/vyper/pull/4448>`_)
* chore[docs]: ``nonpayable`` ``internal`` function behaviour (`#4416 <https://github.com/vyperlang/vyper/pull/4416>`_)
* chore[docs]: add ``FUNDING.json`` for drips funding (`#4167 <https://github.com/vyperlang/vyper/pull/4167>`_)
* chore[docs]: add giveth to ``FUNDING.yml`` (`#4466 <https://github.com/vyperlang/vyper/pull/4466>`_)
* chore[tool]: update ``FUNDING.json`` for optimism RPGF (`#4218 <https://github.com/vyperlang/vyper/pull/4218>`_)
* chore[tool]: mention that output format is comma separated (`#4467 <https://github.com/vyperlang/vyper/pull/4467>`_)

Test suite improvements
-----------------------
* refactor[venom]: add new venom test machinery (`#4401 <https://github.com/vyperlang/vyper/pull/4401>`_)
* feat[ci]: use ``coverage combine`` to reduce codecov uploads (`#4452 <https://github.com/vyperlang/vyper/pull/4452>`_)
* feat[test]: add hevm harness for venom passes (`#4460 <https://github.com/vyperlang/vyper/pull/4460>`_)
* fix[test]: fix test in grammar fuzzer (`#4150 <https://github.com/vyperlang/vyper/pull/4150>`_)
* chore[test]: fix a type hint (`#4173 <https://github.com/vyperlang/vyper/pull/4173>`_)
* chore[ci]: add auto-labeling workflow (`#4276 <https://github.com/vyperlang/vyper/pull/4276>`_)
* fix[test]: fix some clamper tests (`#4300 <https://github.com/vyperlang/vyper/pull/4300>`_)
* refactor[test]: add some sanity checks to ``abi_decode`` tests (`#4096 <https://github.com/vyperlang/vyper/pull/4096>`_)
* chore[ci]: enable Python ``3.13`` tests (`#4386 <https://github.com/vyperlang/vyper/pull/4386>`_)
* chore[ci]: update codecov github action to v5 (`#4437 <https://github.com/vyperlang/vyper/pull/4437>`_)
* chore[ci]: bump upload-artifact action to v4 (`#4445 <https://github.com/vyperlang/vyper/pull/4445>`_)
* chore[ci]: separate codecov upload into separate job (`#4455 <https://github.com/vyperlang/vyper/pull/4455>`_)
* chore[ci]: improve coverage jobs (`#4457 <https://github.com/vyperlang/vyper/pull/4457>`_)
* chore[ci]: update ubuntu image for ``build`` job (`#4473 <https://github.com/vyperlang/vyper/pull/4473>`_)

Misc / Refactor
---------------
* refactor[parser]: remove ``ASTTokens`` (`#4364 <https://github.com/vyperlang/vyper/pull/4364>`_)
* refactor[codegen]: remove redundant ``IRnode.from_list`` (`#4151 <https://github.com/vyperlang/vyper/pull/4151>`_)
* feat[ux]: move exception hint to the end of the message (`#4154 <https://github.com/vyperlang/vyper/pull/4154>`_)
* fix[ux]: improve error message for bad hex literals (`#4244 <https://github.com/vyperlang/vyper/pull/4244>`_)
* refactor[lang]: remove translated fields for constant nodes (`#4287 <https://github.com/vyperlang/vyper/pull/4287>`_)
* refactor[ux]: refactor preparser (`#4293 <https://github.com/vyperlang/vyper/pull/4293>`_)
* refactor[codegen]: add profiling utils (`#4412 <https://github.com/vyperlang/vyper/pull/4412>`_)
* refactor[lang]: remove VyperNode ``__hash__()`` and ``__eq__()`` implementations (`#4433 <https://github.com/vyperlang/vyper/pull/4433>`_)


v0.4.0 ("Nagini")
*****************

Date released: 2024-06-20
=========================

v0.4.0 represents a major overhaul to the Vyper language. Notably, it overhauls the import system and adds support for code reuse. It also adds a new, experimental backend to Vyper which lays the foundation for improved analysis, optimization and integration with third party tools.

Breaking Changes
----------------
* feat[tool]!: make cancun the default evm version (`#4029 <https://github.com/vyperlang/vyper/pull/4029>`_)
* feat[lang]: remove named reentrancy locks (`#3769 <https://github.com/vyperlang/vyper/pull/3769>`_)
* feat[lang]!: change the signature of ``block.prevrandao`` (`#3879 <https://github.com/vyperlang/vyper/pull/3879>`_)
* feat[lang]!: change ABI type of ``decimal`` to ``int168`` (`#3696 <https://github.com/vyperlang/vyper/pull/3696>`_)
* feat[lang]: rename ``_abi_encode`` and ``_abi_decode`` (`#4097 <https://github.com/vyperlang/vyper/pull/4097>`_)
* feat[lang]!: add feature flag for decimals (`#3930 <https://github.com/vyperlang/vyper/pull/3930>`_)
* feat[lang]!: make internal decorator optional (`#4040 <https://github.com/vyperlang/vyper/pull/4040>`_)
* feat[lang]: protect external calls with keyword (`#2938 <https://github.com/vyperlang/vyper/pull/2938>`_)
* introduce floordiv, ban regular div for integers (`#2937 <https://github.com/vyperlang/vyper/pull/2937>`_)
* feat[lang]: use keyword arguments for struct instantiation (`#3777 <https://github.com/vyperlang/vyper/pull/3777>`_)
* feat: require type annotations for loop variables (`#3596 <https://github.com/vyperlang/vyper/pull/3596>`_)
* feat: replace ``enum`` with ``flag`` keyword (`#3697 <https://github.com/vyperlang/vyper/pull/3697>`_)
* feat: remove builtin constants (`#3350 <https://github.com/vyperlang/vyper/pull/3350>`_)
* feat: drop istanbul and berlin support (`#3843 <https://github.com/vyperlang/vyper/pull/3843>`_)
* feat: allow range with two arguments and bound (`#3679 <https://github.com/vyperlang/vyper/pull/3679>`_)
* fix[codegen]: range bound check for signed integers (`#3814 <https://github.com/vyperlang/vyper/pull/3814>`_)
* feat: default code offset = 3 (`#3454 <https://github.com/vyperlang/vyper/pull/3454>`_)
* feat: rename ``vyper.interfaces`` to ``ethereum.ercs`` (`#3741 <https://github.com/vyperlang/vyper/pull/3741>`_)
* chore: add prefix to ERC interfaces (`#3804 <https://github.com/vyperlang/vyper/pull/3804>`_)
* chore[ux]: compute natspec as part of standard pipeline (`#3946 <https://github.com/vyperlang/vyper/pull/3946>`_)
* feat: deprecate ``vyper-serve`` (`#3666 <https://github.com/vyperlang/vyper/pull/3666>`_)

Module system
-------------
* refactor: internal handling of imports (`#3655 <https://github.com/vyperlang/vyper/pull/3655>`_)
* feat: implement "stateless" modules (`#3663 <https://github.com/vyperlang/vyper/pull/3663>`_)
* feat[lang]: export interfaces (`#3919 <https://github.com/vyperlang/vyper/pull/3919>`_)
* feat[lang]: singleton modules with ownership hierarchy (`#3729 <https://github.com/vyperlang/vyper/pull/3729>`_)
* feat[lang]: implement function exports (`#3786 <https://github.com/vyperlang/vyper/pull/3786>`_)
* feat[lang]: auto-export events in ABI (`#3808 <https://github.com/vyperlang/vyper/pull/3808>`_)
* fix: allow using interface defs from imported modules (`#3725 <https://github.com/vyperlang/vyper/pull/3725>`_)
* feat: add support for constants in imported modules (`#3726 <https://github.com/vyperlang/vyper/pull/3726>`_)
* fix[lang]: prevent modules as storage variables (`#4088 <https://github.com/vyperlang/vyper/pull/4088>`_)
* fix[ux]: improve initializer hint for unimported modules (`#4145 <https://github.com/vyperlang/vyper/pull/4145>`_)
* feat: add python ``sys.path`` to vyper path (`#3763 <https://github.com/vyperlang/vyper/pull/3763>`_)
* feat[ux]: improve error message for importing ERC20 (`#3816 <https://github.com/vyperlang/vyper/pull/3816>`_)
* fix[lang]: fix importing of flag types (`#3871 <https://github.com/vyperlang/vyper/pull/3871>`_)
* feat: search path resolution for cli (`#3694 <https://github.com/vyperlang/vyper/pull/3694>`_)
* fix[lang]: transitive exports (`#3888 <https://github.com/vyperlang/vyper/pull/3888>`_)
* fix[ux]: error messages relating to initializer issues (`#3831 <https://github.com/vyperlang/vyper/pull/3831>`_)
* fix[lang]: recursion in ``uses`` analysis for nonreentrant functions (`#3971 <https://github.com/vyperlang/vyper/pull/3971>`_)
* fix[ux]: fix ``uses`` error message (`#3926 <https://github.com/vyperlang/vyper/pull/3926>`_)
* fix[lang]: fix ``uses`` analysis for nonreentrant functions (`#3927 <https://github.com/vyperlang/vyper/pull/3927>`_)
* fix[lang]: fix a hint in global initializer check (`#4089 <https://github.com/vyperlang/vyper/pull/4089>`_)
* fix[lang]: builtin type comparisons (`#3956 <https://github.com/vyperlang/vyper/pull/3956>`_)
* fix[tool]: fix ``combined_json`` output for CLI (`#3901 <https://github.com/vyperlang/vyper/pull/3901>`_)
* fix[tool]: compile multiple files (`#4053 <https://github.com/vyperlang/vyper/pull/4053>`_)
* refactor: reimplement AST folding (`#3669 <https://github.com/vyperlang/vyper/pull/3669>`_)
* refactor: constant folding (`#3719 <https://github.com/vyperlang/vyper/pull/3719>`_)
* fix[lang]: typecheck hashmap indexes with folding (`#4007 <https://github.com/vyperlang/vyper/pull/4007>`_)
* fix[lang]: fix array index checks when the subscript is folded (`#3924 <https://github.com/vyperlang/vyper/pull/3924>`_)
* fix[lang]: pure access analysis (`#3895 <https://github.com/vyperlang/vyper/pull/3895>`_)

Venom
-----
* feat: implement new IR for vyper (venom IR) (`#3659 <https://github.com/vyperlang/vyper/pull/3659>`_)
* feat[ir]: add ``make_ssa`` pass to venom pipeline (`#3825 <https://github.com/vyperlang/vyper/pull/3825>`_)
* feat[venom]: implement ``mem2var`` and ``sccp`` passes (`#3941 <https://github.com/vyperlang/vyper/pull/3941>`_)
* feat[venom]: add store elimination pass (`#4021 <https://github.com/vyperlang/vyper/pull/4021>`_)
* feat[venom]: add ``extract_literals`` pass (`#4067 <https://github.com/vyperlang/vyper/pull/4067>`_)
* feat[venom]: optimize branching (`#4049 <https://github.com/vyperlang/vyper/pull/4049>`_)
* feat[venom]: avoid last ``swap`` for commutative ops (`#4048 <https://github.com/vyperlang/vyper/pull/4048>`_)
* feat[venom]: "pickaxe" stack scheduler optimization (`#3951 <https://github.com/vyperlang/vyper/pull/3951>`_)
* feat[venom]: add algebraic optimization pass (`#4054 <https://github.com/vyperlang/vyper/pull/4054>`_)
* feat: Implement target constrained venom jump instruction (`#3687 <https://github.com/vyperlang/vyper/pull/3687>`_)
* feat: remove ``deploy`` instruction from venom (`#3703 <https://github.com/vyperlang/vyper/pull/3703>`_)
* fix[venom]: liveness analysis in some loops (`#3732 <https://github.com/vyperlang/vyper/pull/3732>`_)
* feat: add more venom instructions (`#3733 <https://github.com/vyperlang/vyper/pull/3733>`_)
* refactor[venom]: use venom pass instances (`#3908 <https://github.com/vyperlang/vyper/pull/3908>`_)
* refactor[venom]: refactor venom operand classes (`#3915 <https://github.com/vyperlang/vyper/pull/3915>`_)
* refactor[venom]: introduce ``IRContext`` and ``IRAnalysisCache`` (`#3983 <https://github.com/vyperlang/vyper/pull/3983>`_)
* feat: add utility functions to ``OrderedSet`` (`#3833 <https://github.com/vyperlang/vyper/pull/3833>`_)
* feat[venom]: optimize ``get_basic_block()`` (`#4002 <https://github.com/vyperlang/vyper/pull/4002>`_)
* fix[venom]: fix branch eliminator cases in sccp (`#4003 <https://github.com/vyperlang/vyper/pull/4003>`_)
* fix[codegen]: same symbol jumpdest merge (`#3982 <https://github.com/vyperlang/vyper/pull/3982>`_)
* fix[venom]: fix eval of ``exp`` in sccp (`#4009 <https://github.com/vyperlang/vyper/pull/4009>`_)
* refactor[venom]: remove unused method in ``make_ssa.py`` (`#4012 <https://github.com/vyperlang/vyper/pull/4012>`_)
* fix[venom]: fix return opcode handling in mem2var (`#4011 <https://github.com/vyperlang/vyper/pull/4011>`_)
* fix[venom]: fix ``cfg`` output format (`#4010 <https://github.com/vyperlang/vyper/pull/4010>`_)
* chore[venom]: fix output formatting of data segment in ``IRContext`` (`#4016 <https://github.com/vyperlang/vyper/pull/4016>`_)
* feat[venom]: optimize mem2var and store/variable elimination pass sequences (`#4032 <https://github.com/vyperlang/vyper/pull/4032>`_)
* fix[venom]: fix some sccp evaluations (`#4028 <https://github.com/vyperlang/vyper/pull/4028>`_)
* fix[venom]: add ``unique_symbols`` check to venom pipeline (`#4149 <https://github.com/vyperlang/vyper/pull/4149>`_)
* feat[venom]: remove redundant store elimination pass (`#4036 <https://github.com/vyperlang/vyper/pull/4036>`_)
* fix[venom]: remove some dead code in ``venom_to_assembly`` (`#4042 <https://github.com/vyperlang/vyper/pull/4042>`_)
* feat[venom]: improve unused variable removal pass (`#4055 <https://github.com/vyperlang/vyper/pull/4055>`_)
* fix[venom]: remove liveness requests (`#4058 <https://github.com/vyperlang/vyper/pull/4058>`_)
* fix[venom]: fix list of volatile instructions (`#4065 <https://github.com/vyperlang/vyper/pull/4065>`_)
* fix[venom]: remove dominator tree invalidation for store elimination pass (`#4069 <https://github.com/vyperlang/vyper/pull/4069>`_)
* fix[venom]: move loop invariant assertion to entry block (`#4098 <https://github.com/vyperlang/vyper/pull/4098>`_)
* fix[venom]: clear ``out_vars`` during calculation (`#4129 <https://github.com/vyperlang/vyper/pull/4129>`_)
* fix[venom]: alloca for default arguments (`#4155 <https://github.com/vyperlang/vyper/pull/4155>`_)
* Refactor ctx.add_instruction() and friends (`#3685 <https://github.com/vyperlang/vyper/pull/3685>`_)
* fix: type annotation of helper function (`#3702 <https://github.com/vyperlang/vyper/pull/3702>`_)
* feat[ir]: emit ``djump`` in dense selector table (`#3849 <https://github.com/vyperlang/vyper/pull/3849>`_)
* chore: move venom tests to ``tests/unit/compiler`` (`#3684 <https://github.com/vyperlang/vyper/pull/3684>`_)

Other new features
------------------
* feat[lang]: add ``blobhash()`` builtin (`#3962 <https://github.com/vyperlang/vyper/pull/3962>`_)
* feat[lang]: support ``block.blobbasefee`` (`#3945 <https://github.com/vyperlang/vyper/pull/3945>`_)
* feat[lang]: add ``revert_on_failure`` kwarg for create builtins (`#3844 <https://github.com/vyperlang/vyper/pull/3844>`_)
* feat[lang]: allow downcasting of bytestrings (`#3832 <https://github.com/vyperlang/vyper/pull/3832>`_)

Docs
----
* chore[docs]: add docs for v0.4.0 features (`#3947 <https://github.com/vyperlang/vyper/pull/3947>`_)
* chore[docs]: ``implements`` does not check event declarations (`#4052 <https://github.com/vyperlang/vyper/pull/4052>`_)
* docs: adopt a new theme: ``shibuya`` (`#3754 <https://github.com/vyperlang/vyper/pull/3754>`_)
* chore[docs]: add evaluation order warning for builtins (`#4158 <https://github.com/vyperlang/vyper/pull/4158>`_)
* Update ``FUNDING.yml`` (`#3636 <https://github.com/vyperlang/vyper/pull/3636>`_)
* docs: fix nit in v0.3.10 release notes (`#3638 <https://github.com/vyperlang/vyper/pull/3638>`_)
* docs: add note on ``pragma`` parsing (`#3640 <https://github.com/vyperlang/vyper/pull/3640>`_)
* docs: retire security@vyperlang.org (`#3660 <https://github.com/vyperlang/vyper/pull/3660>`_)
* feat[docs]: add more detail to modules docs (`#4087 <https://github.com/vyperlang/vyper/pull/4087>`_)
* docs: update resources section (`#3656 <https://github.com/vyperlang/vyper/pull/3656>`_)
* docs: add script to help working on the compiler (`#3674 <https://github.com/vyperlang/vyper/pull/3674>`_)
* docs: add warnings at the top of all example token contracts (`#3676 <https://github.com/vyperlang/vyper/pull/3676>`_)
* docs: typo in ``on_chain_market_maker.vy`` (`#3677 <https://github.com/vyperlang/vyper/pull/3677>`_)
* docs: clarify ``address.codehash`` for empty account (`#3711 <https://github.com/vyperlang/vyper/pull/3711>`_)
* docs: indexed arguments for events are limited (`#3715 <https://github.com/vyperlang/vyper/pull/3715>`_)
* docs: Fix typos (`#3747 <https://github.com/vyperlang/vyper/pull/3747>`_)
* docs: Upgrade dependencies and fixes (`#3745 <https://github.com/vyperlang/vyper/pull/3745>`_)
* docs: add missing cli flags (`#3736 <https://github.com/vyperlang/vyper/pull/3736>`_)
* chore: fix formatting and docs for new struct instantiation syntax (`#3792 <https://github.com/vyperlang/vyper/pull/3792>`_)
* docs: floordiv (`#3797 <https://github.com/vyperlang/vyper/pull/3797>`_)
* docs: add missing ``annotated_ast`` flag (`#3813 <https://github.com/vyperlang/vyper/pull/3813>`_)
* docs: update logo in readme, remove competition reference (`#3837 <https://github.com/vyperlang/vyper/pull/3837>`_)
* docs: add rationale for floordiv rounding behavior (`#3845 <https://github.com/vyperlang/vyper/pull/3845>`_)
* chore[docs]: amend ``revert_on_failure`` kwarg docs for create builtins (`#3921 <https://github.com/vyperlang/vyper/pull/3921>`_)
* fix[docs]: fix clipped ``endAuction`` method in example section (`#3969 <https://github.com/vyperlang/vyper/pull/3969>`_)
* refactor[docs]: refactor security policy (`#3981 <https://github.com/vyperlang/vyper/pull/3981>`_)
* fix: edit link to style guide (`#3658 <https://github.com/vyperlang/vyper/pull/3658>`_)
* Add Vyper online compiler tooling (`#3680 <https://github.com/vyperlang/vyper/pull/3680>`_)
* chore: fix typos (`#3749 <https://github.com/vyperlang/vyper/pull/3749>`_)

Bugfixes
--------
* fix[codegen]: fix ``raw_log()`` when topics are non-literals (`#3977 <https://github.com/vyperlang/vyper/pull/3977>`_)
* fix[codegen]: fix transient codegen for ``slice`` and ``extract32`` (`#3874 <https://github.com/vyperlang/vyper/pull/3874>`_)
* fix[codegen]: bounds check for signed index accesses (`#3817 <https://github.com/vyperlang/vyper/pull/3817>`_)
* fix: disallow ``value=`` passing for delegate and static raw_calls (`#3755 <https://github.com/vyperlang/vyper/pull/3755>`_)
* fix[codegen]: fix double evals in sqrt, slice, blueprint (`#3976 <https://github.com/vyperlang/vyper/pull/3976>`_)
* fix[codegen]: fix double eval in dynarray append/pop (`#4030 <https://github.com/vyperlang/vyper/pull/4030>`_)
* fix[codegen]: fix double eval of start in range expr (`#4033 <https://github.com/vyperlang/vyper/pull/4033>`_)
* fix[codegen]: overflow check in ``slice()`` (`#3818 <https://github.com/vyperlang/vyper/pull/3818>`_)
* fix: concat buffer bug (`#3738 <https://github.com/vyperlang/vyper/pull/3738>`_)
* fix[codegen]: fix ``make_setter`` overlap with internal calls (`#4037 <https://github.com/vyperlang/vyper/pull/4037>`_)
* fix[codegen]: fix ``make_setter`` overlap in ``dynarray_append`` (`#4059 <https://github.com/vyperlang/vyper/pull/4059>`_)
* fix[codegen]: ``make_setter`` overlap in the presence of ``staticcall`` (`#4128 <https://github.com/vyperlang/vyper/pull/4128>`_)
* fix[codegen]: fix ``_abi_decode`` buffer overflow (`#3925 <https://github.com/vyperlang/vyper/pull/3925>`_)
* fix[codegen]: zero-length dynarray ``abi_decode`` validation (`#4060 <https://github.com/vyperlang/vyper/pull/4060>`_)
* fix[codegen]: recursive dynarray oob check (`#4091 <https://github.com/vyperlang/vyper/pull/4091>`_)
* fix[codegen]: add back in ``returndatasize`` check (`#4144 <https://github.com/vyperlang/vyper/pull/4144>`_)
* fix: block memory allocation overflow (`#3639 <https://github.com/vyperlang/vyper/pull/3639>`_)
* fix[codegen]: panic on potential eval order issue for some builtins (`#4157 <https://github.com/vyperlang/vyper/pull/4157>`_)
* fix[codegen]: panic on potential subscript eval order issue (`#4159 <https://github.com/vyperlang/vyper/pull/4159>`_)
* add comptime check for uint2str input (`#3671 <https://github.com/vyperlang/vyper/pull/3671>`_)
* fix: dead code analysis inside for loops (`#3731 <https://github.com/vyperlang/vyper/pull/3731>`_)
* fix[ir]: fix a latent bug in ``sha3_64`` codegen (`#4063 <https://github.com/vyperlang/vyper/pull/4063>`_)
* fix: ``opcodes`` and ``opcodes_runtime`` outputs (`#3735 <https://github.com/vyperlang/vyper/pull/3735>`_)
* fix: bad assertion in expr.py (`#3758 <https://github.com/vyperlang/vyper/pull/3758>`_)
* fix: iterator modification analysis (`#3764 <https://github.com/vyperlang/vyper/pull/3764>`_)
* feat: allow constant interfaces (`#3718 <https://github.com/vyperlang/vyper/pull/3718>`_)
* fix: assembly dead code eliminator (`#3791 <https://github.com/vyperlang/vyper/pull/3791>`_)
* fix: prevent range over decimal (`#3798 <https://github.com/vyperlang/vyper/pull/3798>`_)
* fix: mutability check for interface implements (`#3805 <https://github.com/vyperlang/vyper/pull/3805>`_)
* fix[codegen]: fix non-memory reason strings (`#3877 <https://github.com/vyperlang/vyper/pull/3877>`_)
* fix[ux]: fix compiler hang for large exponentiations (`#3893 <https://github.com/vyperlang/vyper/pull/3893>`_)
* fix[lang]: allow type expressions inside pure functions (`#3906 <https://github.com/vyperlang/vyper/pull/3906>`_)
* fix[ux]: raise ``VersionException`` with source info (`#3920 <https://github.com/vyperlang/vyper/pull/3920>`_)
* fix[lang]: fix ``pow`` folding when args are not literals (`#3949 <https://github.com/vyperlang/vyper/pull/3949>`_)
* fix[codegen]: fix some hardcoded references to ``STORAGE`` location (`#4015 <https://github.com/vyperlang/vyper/pull/4015>`_)

Patched security advisories (GHSAs)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* Bounds check on built-in ``slice()`` function can be overflowed (`GHSA-9x7f-gwxq-6f2c <https://github.com/vyperlang/vyper/security/advisories/GHSA-9x7f-gwxq-6f2c>`_)
* ``concat`` built-in can corrupt memory (`GHSA-2q8v-3gqq-4f8p <https://github.com/vyperlang/vyper/security/advisories/GHSA-2q8v-3gqq-4f8p>`_)
* ``raw_call`` ``value=`` kwargs not disabled for static and delegate calls (`GHSA-x2c2-q32w-4w6m <https://github.com/vyperlang/vyper/security/advisories/GHSA-x2c2-q32w-4w6m>`_)
* negative array index bounds checks (`GHSA-52xq-j7v9-v4v2 <https://github.com/vyperlang/vyper/security/advisories/GHSA-52xq-j7v9-v4v2>`_)
* ``range(start, start + N)`` reverts for negative numbers (`GHSA-ppx5-q359-pvwj <https://github.com/vyperlang/vyper/security/advisories/GHSA-ppx5-q359-pvwj>`_)
* incorrect topic logging in ``raw_log`` (`GHSA-xchq-w5r3-4wg3 <https://github.com/vyperlang/vyper/security/advisories/GHSA-xchq-w5r3-4wg3>`_)
* double eval of the ``slice`` start/length args in certain cases (`GHSA-r56x-j438-vw5m <https://github.com/vyperlang/vyper/security/advisories/GHSA-r56x-j438-vw5m>`_)
* multiple eval of ``sqrt()`` built in argument (`GHSA-5jrj-52x8-m64h <https://github.com/vyperlang/vyper/security/advisories/GHSA-5jrj-52x8-m64h>`_)
* double eval of raw_args in ``create_from_blueprint`` (`GHSA-3whq-64q2-qfj6 <https://github.com/vyperlang/vyper/security/advisories/GHSA-3whq-64q2-qfj6>`_)
* ``sha3`` codegen bug (`GHSA-6845-xw22-ffxv <https://github.com/vyperlang/vyper/security/advisories/GHSA-6845-xw22-ffxv>`_)
* ``extract32`` can read dirty memory (`GHSA-4hwq-4cpm-8vmx <https://github.com/vyperlang/vyper/security/advisories/GHSA-4hwq-4cpm-8vmx>`_)
* ``_abi_decode`` Memory Overflow (`GHSA-9p8r-4xp4-gw5w <https://github.com/vyperlang/vyper/security/advisories/GHSA-9p8r-4xp4-gw5w>`_)
* External calls can overflow return data to return input buffer (`GHSA-gp3w-2v2m-p686 <https://github.com/vyperlang/vyper/security/advisories/GHSA-gp3w-2v2m-p686>`_)

Tooling
-------
* feat[tool]: archive format (`#3891 <https://github.com/vyperlang/vyper/pull/3891>`_)
* feat[tool]: add source map for constructors (`#4008 <https://github.com/vyperlang/vyper/pull/4008>`_)
* feat: add short options ``-v`` and ``-O`` to the CLI (`#3695 <https://github.com/vyperlang/vyper/pull/3695>`_)
* feat: Add ``bb`` and ``bb_runtime`` output options  (`#3700 <https://github.com/vyperlang/vyper/pull/3700>`_)
* fix: remove hex-ir from format cli options list (`#3657 <https://github.com/vyperlang/vyper/pull/3657>`_)
* fix: pickleability of ``CompilerData`` (`#3803 <https://github.com/vyperlang/vyper/pull/3803>`_)
* feat[tool]: validate AST nodes early in the pipeline (`#3809 <https://github.com/vyperlang/vyper/pull/3809>`_)
* feat[tool]: delay global constraint check (`#3810 <https://github.com/vyperlang/vyper/pull/3810>`_)
* feat[tool]: export variable read/write access (`#3790 <https://github.com/vyperlang/vyper/pull/3790>`_)
* feat[tool]: improvements to AST annotation (`#3829 <https://github.com/vyperlang/vyper/pull/3829>`_)
* feat[tool]: add ``node_id`` map to source map (`#3811 <https://github.com/vyperlang/vyper/pull/3811>`_)
* chore[tool]: add help text for ``hex-ir`` CLI flag (`#3942 <https://github.com/vyperlang/vyper/pull/3942>`_)
* refactor[tool]: refactor storage layout export (`#3789 <https://github.com/vyperlang/vyper/pull/3789>`_)
* fix[tool]: fix cross-compilation issues, add windows CI (`#4014 <https://github.com/vyperlang/vyper/pull/4014>`_)
* fix[tool]: star option in ``outputSelection`` (`#4094 <https://github.com/vyperlang/vyper/pull/4094>`_)

Performance
-----------
* perf: lazy eval of f-strings in IRnode ctor (`#3602 <https://github.com/vyperlang/vyper/pull/3602>`_)
* perf: levenshtein optimization (`#3780 <https://github.com/vyperlang/vyper/pull/3780>`_)
* feat: frontend optimizations (`#3781 <https://github.com/vyperlang/vyper/pull/3781>`_)
* feat: optimize ``VyperNode.deepcopy`` (`#3784 <https://github.com/vyperlang/vyper/pull/3784>`_)
* feat: more frontend optimizations (`#3785 <https://github.com/vyperlang/vyper/pull/3785>`_)
* perf: reimplement ``IRnode.__deepcopy__`` (`#3761 <https://github.com/vyperlang/vyper/pull/3761>`_)

Testing suite improvements
--------------------------
* refactor[test]: bypass ``eth-tester`` and interface with evm backend directly (`#3846 <https://github.com/vyperlang/vyper/pull/3846>`_)
* feat: Refactor assert_tx_failed into a context (`#3706 <https://github.com/vyperlang/vyper/pull/3706>`_)
* feat[test]: implement ``abi_decode`` spec test (`#4095 <https://github.com/vyperlang/vyper/pull/4095>`_)
* feat[test]: add more coverage to ``abi_decode`` fuzzer tests (`#4153 <https://github.com/vyperlang/vyper/pull/4153>`_)
* feat[ci]: enable cancun testing (`#3861 <https://github.com/vyperlang/vyper/pull/3861>`_)
* fix: add missing test for memory allocation overflow (`#3650 <https://github.com/vyperlang/vyper/pull/3650>`_)
* chore: fix test for ``slice`` (`#3633 <https://github.com/vyperlang/vyper/pull/3633>`_)
* add abi_types unit tests (`#3662 <https://github.com/vyperlang/vyper/pull/3662>`_)
* refactor: test directory structure (`#3664 <https://github.com/vyperlang/vyper/pull/3664>`_)
* chore: test all output formats (`#3683 <https://github.com/vyperlang/vyper/pull/3683>`_)
* chore: deduplicate test files (`#3773 <https://github.com/vyperlang/vyper/pull/3773>`_)
* feat[test]: add more transient storage tests (`#3883 <https://github.com/vyperlang/vyper/pull/3883>`_)
* chore[ci]: fix apt-get failure in era pipeline (`#3821 <https://github.com/vyperlang/vyper/pull/3821>`_)
* chore[ci]: enable python3.12 tests (`#3860 <https://github.com/vyperlang/vyper/pull/3860>`_)
* chore[ci]: refactor jobs to use gh actions (`#3863 <https://github.com/vyperlang/vyper/pull/3863>`_)
* chore[ci]: use ``--dist worksteal`` from latest ``xdist`` (`#3869 <https://github.com/vyperlang/vyper/pull/3869>`_)
* chore: run mypy as part of lint rule in Makefile (`#3771 <https://github.com/vyperlang/vyper/pull/3771>`_)
* chore[test]: always specify the evm backend (`#4006 <https://github.com/vyperlang/vyper/pull/4006>`_)
* chore: update lint dependencies (`#3704 <https://github.com/vyperlang/vyper/pull/3704>`_)
* chore: add color to mypy output (`#3793 <https://github.com/vyperlang/vyper/pull/3793>`_)
* chore: remove tox rules for lint commands (`#3826 <https://github.com/vyperlang/vyper/pull/3826>`_)
* chore[ci]: roll back GH actions/artifacts version (`#3838 <https://github.com/vyperlang/vyper/pull/3838>`_)
* chore: Upgrade GitHub action dependencies (`#3807 <https://github.com/vyperlang/vyper/pull/3807>`_)
* chore[ci]: pin eth-abi for decode regression (`#3834 <https://github.com/vyperlang/vyper/pull/3834>`_)
* fix[ci]: release artifacts (`#3839 <https://github.com/vyperlang/vyper/pull/3839>`_)
* chore[ci]: merge mypy job into lint (`#3840 <https://github.com/vyperlang/vyper/pull/3840>`_)
* test: parametrize CI over EVM versions (`#3842 <https://github.com/vyperlang/vyper/pull/3842>`_)
* feat[ci]: add PR title validation (`#3887 <https://github.com/vyperlang/vyper/pull/3887>`_)
* fix[test]: fix failure in grammar fuzzing (`#3892 <https://github.com/vyperlang/vyper/pull/3892>`_)
* feat[test]: add ``xfail_strict``, clean up ``setup.cfg`` (`#3889 <https://github.com/vyperlang/vyper/pull/3889>`_)
* fix[ci]: pin hexbytes to pre-1.0.0 (`#3903 <https://github.com/vyperlang/vyper/pull/3903>`_)
* chore[test]: update hexbytes version and tests (`#3904 <https://github.com/vyperlang/vyper/pull/3904>`_)
* fix[test]: fix a bad bound in decimal fuzzing (`#3909 <https://github.com/vyperlang/vyper/pull/3909>`_)
* fix[test]: fix a boundary case in decimal fuzzing (`#3918 <https://github.com/vyperlang/vyper/pull/3918>`_)
* feat[ci]: update pypi release pipeline to use OIDC (`#3912 <https://github.com/vyperlang/vyper/pull/3912>`_)
* chore[ci]: reconfigure single commit validation (`#3937 <https://github.com/vyperlang/vyper/pull/3937>`_)
* chore[ci]: downgrade codecov action to v3 (`#3940 <https://github.com/vyperlang/vyper/pull/3940>`_)
* feat[ci]: add codecov configuration (`#4057 <https://github.com/vyperlang/vyper/pull/4057>`_)
* feat[test]: remove memory mocker (`#4005 <https://github.com/vyperlang/vyper/pull/4005>`_)
* refactor[test]: change fixture scope in examples (`#3995 <https://github.com/vyperlang/vyper/pull/3995>`_)
* fix[test]: fix call graph stability fuzzer (`#4064 <https://github.com/vyperlang/vyper/pull/4064>`_)
* chore[test]: add macos to test matrix (`#4025 <https://github.com/vyperlang/vyper/pull/4025>`_)
* refactor[test]: change default expected exception type (`#4004 <https://github.com/vyperlang/vyper/pull/4004>`_)

Misc / refactor
---------------
* feat[ir]: add ``eval_once`` sanity fences to more builtins (`#3835 <https://github.com/vyperlang/vyper/pull/3835>`_)
* fix: reorder compilation of branches in stmt.py (`#3603 <https://github.com/vyperlang/vyper/pull/3603>`_)
* refactor[codegen]: make settings into a global object (`#3929 <https://github.com/vyperlang/vyper/pull/3929>`_)
* chore: improve exception handling in IR generation (`#3705 <https://github.com/vyperlang/vyper/pull/3705>`_)
* refactor: merge ``annotation.py`` and ``local.py`` (`#3456 <https://github.com/vyperlang/vyper/pull/3456>`_)
* chore[ux]: remove deprecated python AST classes (`#3998 <https://github.com/vyperlang/vyper/pull/3998>`_)
* refactor[ux]: remove deprecated ``VyperNode`` properties (`#3999 <https://github.com/vyperlang/vyper/pull/3999>`_)
* feat: remove Index AST node (`#3757 <https://github.com/vyperlang/vyper/pull/3757>`_)
* refactor: for loop target parsing (`#3724 <https://github.com/vyperlang/vyper/pull/3724>`_)
* chore: improve diagnostics for invalid for loop annotation (`#3721 <https://github.com/vyperlang/vyper/pull/3721>`_)
* refactor: builtin functions inherit from ``VyperType`` (`#3559 <https://github.com/vyperlang/vyper/pull/3559>`_)
* fix: remove .keyword from Call AST node (`#3689 <https://github.com/vyperlang/vyper/pull/3689>`_)
* improvement: assert descriptions in Crowdfund finalize() and participate() (`#3064 <https://github.com/vyperlang/vyper/pull/3064>`_)
* feat: improve panics in IR generation (`#3708 <https://github.com/vyperlang/vyper/pull/3708>`_)
* feat: improve warnings, refactor ``vyper_warn()`` (`#3800 <https://github.com/vyperlang/vyper/pull/3800>`_)
* fix[ir]: unique symbol name (`#3848 <https://github.com/vyperlang/vyper/pull/3848>`_)
* refactor: remove duplicate terminus checking code (`#3541 <https://github.com/vyperlang/vyper/pull/3541>`_)
* refactor: ``ExprVisitor`` type validation (`#3739 <https://github.com/vyperlang/vyper/pull/3739>`_)
* chore: improve exception for type validation (`#3759 <https://github.com/vyperlang/vyper/pull/3759>`_)
* fix: fuzz test not updated to use TypeMismatch (`#3768 <https://github.com/vyperlang/vyper/pull/3768>`_)
* chore: fix StringEnum._generate_next_value_ signature (`#3770 <https://github.com/vyperlang/vyper/pull/3770>`_)
* chore: improve some error messages (`#3775 <https://github.com/vyperlang/vyper/pull/3775>`_)
* refactor: ``get_search_paths()`` for vyper cli (`#3778 <https://github.com/vyperlang/vyper/pull/3778>`_)
* chore: replace occurrences of 'enum' by 'flag' (`#3794 <https://github.com/vyperlang/vyper/pull/3794>`_)
* chore: add another borrowship test (`#3802 <https://github.com/vyperlang/vyper/pull/3802>`_)
* chore[ux]: improve an exports error message (`#3822 <https://github.com/vyperlang/vyper/pull/3822>`_)
* chore: improve codegen test coverage report (`#3824 <https://github.com/vyperlang/vyper/pull/3824>`_)
* chore: improve syntax error messages (`#3885 <https://github.com/vyperlang/vyper/pull/3885>`_)
* chore[tool]: remove ``vyper-serve`` from ``setup.py`` (`#3936 <https://github.com/vyperlang/vyper/pull/3936>`_)
* fix[ux]: replace standard strings with f-strings (`#3953 <https://github.com/vyperlang/vyper/pull/3953>`_)
* chore[ir]: sanity check types in for range codegen (`#3968 <https://github.com/vyperlang/vyper/pull/3968>`_)

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
