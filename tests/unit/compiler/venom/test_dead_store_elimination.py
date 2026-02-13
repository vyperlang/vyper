import pytest

from tests.venom_utils import PrePostChecker, assert_ctx_eq, parse_from_basic_block
from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.mem_ssa import mem_ssa_type_factory
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.passes import SCCP, DeadStoreElimination, RemoveUnusedVariablesPass
from vyper.venom.passes.base_pass import IRPass

pytestmark = pytest.mark.hevm


class VolatilePrePostChecker(PrePostChecker):
    def __init__(
        self,
        passes: list[type],
        volatile_locations=None,
        addr_space: AddrSpace = MEMORY,
        post=None,
        default_hevm=True,
    ):
        super().__init__(passes, post, default_hevm)
        self.addr_space = addr_space
        if volatile_locations is None:
            self.volatile_locations = []
        else:
            self.volatile_locations = volatile_locations

    def __call__(self, pre: str, post: str, hevm: bool | None = None) -> list[IRPass]:
        self.pass_objects.clear()

        if hevm is None:
            hevm = self.default_hevm

        pre_ctx = parse_from_basic_block(pre)
        for fn in pre_ctx.functions.values():
            ac = IRAnalysesCache(fn)
            SCCP(ac, fn).run_pass()

            mem_ssa = ac.request_analysis(mem_ssa_type_factory(self.addr_space))

            for address, size in self.volatile_locations:
                volatile_loc = MemoryLocation(offset=address, size=size, _is_volatile=True)
                mem_ssa.mark_location_volatile(volatile_loc)

            for p in self.passes:
                obj = p(ac, fn)
                self.pass_objects.append(obj)
                obj.run_pass(self.addr_space)

            # clean up allocas left dead after DSE
            RemoveUnusedVariablesPass(ac, fn).run_pass()

        post_ctx = parse_from_basic_block(post)
        for fn in post_ctx.functions.values():
            ac = IRAnalysesCache(fn)
            SCCP(ac, fn).run_pass()
            for p in self.post_passes:
                obj = p(ac, fn)
                self.pass_objects.append(obj)
                obj.run_pass()

            # clean up allocas left dead after DSE
            RemoveUnusedVariablesPass(ac, fn).run_pass()

        assert_ctx_eq(pre_ctx, post_ctx)

        if hevm:
            from tests.hevm import hevm_check_venom

            hevm_check_venom(pre, post)

        return self.pass_objects


_check_pre_post = VolatilePrePostChecker([DeadStoreElimination])


def _check_no_change(code, hevm=False):
    return _check_pre_post(code, code, hevm=hevm)


@pytest.mark.parametrize("position", [0, "alloca 32"])
def test_basic_dead_store(position):
    pre = f"""
        _global:
            %val1 = 42
            %val2 = 24
            %ptr = {position}
            mstore %ptr, %val1  ; Dead store - overwritten before read
            mstore %ptr, 10     ; Dead store - overwritten before read
            mstore %ptr, %val2
            %loaded = mload %ptr  ; Only reads val2
            stop
    """
    post = f"""
        _global:
            %val1 = 42
            %val2 = 24
            %ptr = {position}
            nop
            nop
            mstore %ptr, %val2
            %loaded = mload %ptr
            stop
    """
    _check_pre_post(pre, post)


# for future implementation of better escape analysis
# and alias analysis
@pytest.mark.xfail
def test_basic_not_dead_store():
    pre = """
        _global:
            %1 = source
            mstore %1, 1
            stop
    """
    post = """
        _global:
            %1 = source
            nop
            stop
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("positions", [(0, 32), ("alloca 32", "alloca 32")])
def test_basic_not_dead_store_with_mload(positions):
    a, b = positions
    pre = f"""
        _global:
            %1 = source
            %ptr_a = {a}
            %ptr_b = {b}
            mstore %ptr_a, 1
            mstore %ptr_b, 2
            %2 = mload %ptr_a
            stop
    """
    post = f"""
        _global:
            %1 = source
            %ptr_a = {a}
            nop
            mstore %ptr_a, 1
            nop
            %2 = mload %ptr_a
            stop
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("positions", [(0, 32), ("alloca 32", "alloca 32")])
def test_basic_not_dead_store_with_return(positions):
    a, b = positions
    pre = f"""
        _global:
            %1 = source
            %ptr_a = {a}
            %ptr_b = {b}
            mstore %ptr_a, 1
            mstore %ptr_b, 2
            return %ptr_a, 32
    """
    post = f"""
        _global:
            %1 = source
            %ptr_a = {a}
            nop
            mstore %ptr_a, 1
            nop
            return %ptr_a, 32
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("position", [0, 32, "alloca 32"])
def test_never_read_store(position):
    pre = f"""
        _global:
            %val = 42
            %ptr = {position}
            mstore %ptr, %val  ; Dead store - never read
            stop
    """
    post = """
        _global:
            %val = 42
            nop
            nop
            stop
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("position", [0, 32, "alloca 32"])
def test_live_store(position):
    pre = f"""
        _global:
            %val = 42
            %ptr = {position}
            mstore %ptr, %val
            %loaded = mload %ptr  ; Makes the store live
            stop
    """
    _check_pre_post(pre, pre)  # Should not change


@pytest.mark.parametrize("positions", [(0, 32), ("alloca 32", "alloca 32")])
def test_dead_store_different_locations(positions):
    a, b = positions
    pre = f"""
        _global:
            %val1 = 42
            %val2 = 24
            %ptr_a = {a}
            %ptr_b = {b}
            mstore %ptr_a, %val1   ; Dead store - never read
            mstore %ptr_b, %val2  ; Live store
            %loaded = mload %ptr_b
            stop
    """
    post = f"""
        _global:
            %val1 = 42
            %val2 = 24
            nop
            %ptr_b = {b}
            nop
            mstore %ptr_b, %val2
            %loaded = mload %ptr_b
            stop
    """
    _check_pre_post(pre, post)


def test_dead_store_memory_copy():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1
            mstore 32, %val2
            mcopy 128, 0, 64
            return 128, 64
    """
    _check_pre_post(pre, pre)


def _generate_jnz_configurations(cond, then, else_):
    return [f"jnz {cond}, {then}, {else_}", f"jnz {cond}, {else_}, {then}"]


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%cond", "@then", "@else"))
def test_dead_store_in_branches(jnz):
    pre = f"""
        _global:
            %cond = source
            %val1 = 42
            %val2 = 24
            {jnz}
        then:
            mstore 0, %val1  ; Dead store - overwritten in merge
            jmp @merge
        else:
            mstore 0, %val2  ; Dead store - overwritten in merge
            jmp @merge
        merge:
            %val3 = 84
            mstore 0, %val3
            %loaded = mload 0  ; Only reads val3
            stop
    """
    post = f"""
        _global:
            %cond = source
            %val1 = 42
            %val2 = 24
            {jnz}
        then:
            nop
            jmp @merge
        else:
            nop
            jmp @merge
        merge:
            %val3 = 84
            mstore 0, %val3
            %loaded = mload 0
            stop
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%cond", "@body", "@exit"))
def test_dead_store_in_loop(jnz):
    pre = f"""
        _global:
            %val1 = 42
            %val2 = 24
            %i = source
            mstore 0, %val1  ; Dead store - overwritten in loop before any read
            jmp @loop
        loop:
            %cond = lt %i, 5
            {jnz}
        body:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    post = f"""
        _global:
            %val1 = 42
            %val2 = 24
            %i = source
            nop
            jmp @loop
        loop:
            %cond = lt %i, 5
            {jnz}
        body:
            mstore 0, %val2
            %loaded = mload 0
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    _check_pre_post(pre, post, hevm=False)


# loop with no branching
def test_trivial_loop():
    pre = """
        main:
            mstore 0, 1 ; can be eliminated
            jmp @main
    """
    post = """
        main:
            nop
            jmp @main
    """
    _check_pre_post(pre, post, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%cond", "@body", "@exit"))
def test_dead_store_in_loop2(jnz):
    pre = f"""
        main:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1  ; not dead store
            jmp @loop
        loop:
            %i = mload 0
            %cond = lt %i, 5
            {jnz}
        body:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i:2 = add %i, 1
            mstore 0, %i:2  ; dead store - overwritten in all branches
            jmp @main
        exit:
            stop
    """
    post = f"""
        main:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1
            jmp @loop
        loop:
            %i = mload 0
            %cond = lt %i, 5
            {jnz}
        body:
            mstore 0, %val2
            %loaded = mload 0
            %i:2 = add %i, 1
            nop
            jmp @main
        exit:
            stop
    """
    _check_pre_post(pre, post, hevm=False)


@pytest.mark.parametrize("jnz1", _generate_jnz_configurations("%cond", "@body", "@exit"))
@pytest.mark.parametrize("jnz2", _generate_jnz_configurations("%cond", "@loop", "@main"))
def test_dead_store_in_loop3(jnz1, jnz2):
    # test an even weirder cfg cycle
    pre = f"""
        main:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1  ; not dead store
            jmp @loop
        loop:
            %i = mload 0
            %cond = lt %i, 5
            {jnz1}
        body:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i:2 = add %i, 1
            mstore 0, %i:2  ; not dead store
            {jnz2}
        exit:
            stop
    """
    _check_no_change(pre, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%cond", "@then", "@else"))
def test_dead_store_alias_across_basic_blocks(jnz):
    pre = f"""
        _global:
            %cond = source
            %val1 = 42
            %val2 = 24
            mstore 0, %val1  ; aliased by mload 5, can't be eliminated
            jmp @next
        next:
            %loaded2 = mload 5  ; aliasing read of slot 0
            {jnz}
        then:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i = add %i, 1
            jmp @else
        else:
            stop
    """
    # no change
    _check_no_change(pre, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%cond", "@body", "@exit"))
def test_dead_store_alias_across_basic_blocks_loop(jnz):
    pre = f"""
        _global:
            %val1 = 42
            %val2 = 24
            %i = source
            mstore 0, %val1  ; aliased by mload 5, can't be eliminated
            jmp @loop
        loop:
            %loaded2 = mload 5  ; aliasing read of slot 0
            %cond = lt %i, 5
            {jnz}
        body:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    # no change
    _check_no_change(pre, hevm=False)


def test_multiple_dead_stores():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84
            mstore 0, %val1  ; Dead store - overwritten before read
            mstore 0, %val2  ; Dead store - overwritten before read
            mstore 0, %val3
            %loaded = mload 0  ; Only reads val3
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84
            nop
            nop
            mstore 0, %val3
            %loaded = mload 0
            stop
    """
    _check_pre_post(pre, post)


def test_volatile_location_store():
    pre = """
        _global:
            %val = 42
            mstore 0xFFFF0000, %val  ; This store should not be eliminated
                                     ; because the location will be marked as volatile
            stop
    """

    # Should not change - volatile stores are preserved
    checker = VolatilePrePostChecker([DeadStoreElimination], volatile_locations=[(0xFFFF0000, 32)])
    checker(pre, pre)


def test_volatile_vs_non_volatile_store():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24

            mstore 0x1000, %val1

            mstore 0xFFFF0000, %val2

            stop
    """

    post = """
        _global:
            %val1 = 42
            %val2 = 24

            nop

            mstore 0xFFFF0000, %val2

            stop
    """

    checker = VolatilePrePostChecker([DeadStoreElimination], volatile_locations=[(0xFFFF0000, 32)])
    checker(pre, post)


def test_multiple_volatile_locations():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84

            mstore 0xFFFF0000, %val1
            mstore 0xFFFF1000, %val2

            mstore 0x2000, %val3

            stop
    """

    post = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84

            mstore 0xFFFF0000, %val1
            mstore 0xFFFF1000, %val2

            nop

            stop
    """

    checker = VolatilePrePostChecker(
        [DeadStoreElimination], volatile_locations=[(0xFFFF0000, 32), (0xFFFF1000, 32)]
    )
    checker(pre, post)


def test_volatile_locations_with_different_sizes():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84
            %val4 = 16

            mstore 0xFFFF0000, %val1
            mstore 0xFFFF1000, %val2
            mstore 0xFFFF1020, %val3

            mstore 0x2000, %val4

            stop
    """

    post = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84
            %val4 = 16

            mstore 0xFFFF0000, %val1
            mstore 0xFFFF1000, %val2
            mstore 0xFFFF1020, %val3

            nop

            stop
    """

    checker = VolatilePrePostChecker(
        [DeadStoreElimination], volatile_locations=[(0xFFFF0000, 32), (0xFFFF1000, 64)]
    )
    checker(pre, post)


def test_call_with_memory_and_other_effects():
    pre = """
        _global:
            ; Store value that is never read (dead store)
            mstore 0, 42  ; This should be eliminated

            ; Store value needed for call
            mstore 32, 24  ; This should remain as it's used by call

            ; Prepare call arguments in memory
            %gas = 1000
            %addr = 0x1234567890123456789012345678901234567890
            %in_offset = 32   ; Points to memory with val2
            %in_size = 32
            %out_offset = 64  ; Output will be written here
            %out_size = 32

            ; Call has both memory read (32) and write (64) effects,
            ; as well as other effects (eg. state changes)
            %success = call %gas, %addr, 0, %in_offset, %in_size, %out_offset, %out_size

            ; Read the call result from memory
            %result = mload 64

            ; Store that is never read (dead), but retained due to return after it
            mstore 128, 42

            ; Return the result from the call
            return %out_offset, %out_size
    """

    # REVIEW this was different but I would like to
    # check it more properly because it is kinda weird
    # I left original commented out
    post = """
        _global:
            ; Store value that is never read (dead store)
            ; mstore 0, 42  ; This should be eliminated
            nop

            ; Store value needed for call
            mstore 32, 24  ; This should remain as it's used by call

            ; Prepare call arguments in memory
            %gas = 1000
            %addr = 0x1234567890123456789012345678901234567890
            %in_offset = 32   ; Points to memory with val2
            %in_size = 32
            %out_offset = 64  ; Output will be written here
            %out_size = 32

            ; Call has both memory read (32) and write (64) effects,
            ; as well as other effects (eg. state changes)
            %success = call %gas, %addr, 0, %in_offset, %in_size, %out_offset, %out_size

            ; Read the call result from memory
            %result = mload 64

            ; Store that is never read (dead), but retained due to return after it
            ; mstore 128, 42
            nop

            ; Return the result from the call
            return %out_offset, %out_size
    """
    _check_pre_post(pre, post, hevm=False)


def test_call_does_not_overwrite_previous_stores():
    pre = """
        _global:
            ; Store at the location uses same memory
            ; as the call instruction output buffer
            ; and never read before the call
            ; However, the mstore cannot be elided
            ; since we don't know how much memory the call
            ; will actually write to (calls are *bounded*
            ; by the output buffer size, not guaranteed
            ; to use all of it)
            mstore 64, 42

            ; Store value needed for call
            mstore 32, 24  ; This should remain as it's used by call

            ; Call has both memory read (32) and write (64) effects
            ; Output will overwrite earlier store
            %success = call 1000, 0x12, 0, 32, 32, 64, 32

            ; Read the call result from memory (at the
            ; location where val1 was stored but got overwritten)
            %result = mload 64

            return %result, 32
    """

    _check_no_change(pre)


def test_calldatacopy_example():
    pre = """
        _global:
            %6 = callvalue
            mstore 192, 32  ; Should not be eliminated as calldatacopy is ambiguous
            mstore 64, 5
            calldatacopy %6, 0, 32
            return 192, 32
    """
    post = """
        _global:
            %6 = callvalue
            mstore 192, 32
            nop
            calldatacopy %6, 0, 32
            return 192, 32
    """
    _check_pre_post(pre, post, hevm=False)


def test_call_reading_partial_mstore():
    pre = """
        _global:
            %11 = calldataload 4
            mstore 96, 801029432
            %20 = add 32, 96
            mstore 128, 601
            %22 = gas
            %23 = add 28, 96
            %24 = call %22, %11, 0, 124, 36, 96, 32
            stop
    """
    _check_pre_post(pre, pre, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%1", "@then", "@else"))
def test_jnz_order(jnz):
    pre = f"""
    main:
      %1 = calldataload 0
      mstore 0, 100  ; not dead store
      {jnz}
    then:
      mstore 0, 101
      jmp @else
    else:
      return 0, 32
    """
    _check_no_change(pre)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%1", "@then", "@else"))
def test_mcopy_partial(jnz):
    pre = f"""
    _global:
        %1 = calldataload 0
        {jnz}

    then:
        mcopy 64, 160, 35 ; not dead store
        jmp @out
    else:
        jmp @out
    out:
        mstore 384, 32
        %40 = mload 64
        sink %40
    """
    post = f"""
    _global:
        %1 = calldataload 0
        {jnz}

    then:
        mcopy 64, 160, 35
        jmp @out
    else:
        jmp @out
    out:
        nop
        %40 = mload 64
        sink %40
    """

    _check_pre_post(pre, post, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%25", "@exit", "@body"))
def test_phi_placement_recursion_error(jnz):
    pre = f"""
        _global:
            mstore 64, 32
            jmp @condition
        condition:
            ; phi: 7 <- 1 from @_global, 2 from @body
            %25 = calldataload 0
            {jnz}
        body:
            mstore 12, 12
            jmp @condition
        exit:
            %29 = mload 96
            sink %29
    """
    post = f"""
        _global:
            nop
            jmp @condition
        condition:
            ; phi: 7 <- 1 from @_global, 2 from @body
            %25 = calldataload 0
            {jnz}
        body:
            nop
            jmp @condition
        exit:
            %29 = mload 96
            sink %29
    """
    _check_pre_post(pre, post, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%17", "@body", "@exit"))
def test_indexed_access(jnz):
    pre = f"""
    _global:
        mstore 64, 1
        mstore 96, 2
        mstore 128, 3
        mstore 160, 4
        mstore 192, 5
        %13 = source
        jmp @condition
    condition:
        %13:1:1 = phi @_global, %13, @body, %13:2
        %17 = xor 5, %13:1:1
        {jnz}
    body:
        %21 = mload %13:1:1
        mstore 224, %21
        %13:2 = add 1, %13:1:1
        jmp @condition
    exit:
        return 256, 32
    """

    _check_no_change(pre, hevm=False)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%19", "@5_if_exit", "@3_then"))
def test_raw_call_dead_store(jnz):
    pre = f"""
    _global:
      mstore 192, 32
      mstore 64, 5
      mstore 96, 0x6d6f6f7365000000000000000000000000000000000000000000000000000000
      %10 = gas
      %19 = call %10, 4, 0, 96, 5, 160, 7
      {jnz}

    3_then:
      revert 0, 0

    5_if_exit:
      %41 = calldatasize
      calldatacopy 0, %41, %41
      return 192, 32
    """
    post = f"""
    _global:
      mstore 192, 32
      nop
      mstore 96, 0x6d6f6f7365000000000000000000000000000000000000000000000000000000
      %10 = gas
      %19 = call %10, 4, 0, 96, 5, 160, 7
      {jnz}

    3_then:
      revert 0, 0

    5_if_exit:
      %41 = calldatasize
      calldatacopy 0, %41, %41
      return 192, 32
    """
    _check_pre_post(pre, post, hevm=False)


def test_new_test():
    pre = """
    _global:
      %1 = calldataload 0
      %2 = shr 224, %1
      %4 = mod %2, 3
      %5 = shl 1, %4
      %6 = add @selector_buckets, %5
      codecopy 30, %6, 2
      %7 = mload 0
      djmp %7, @selector_bucket_0, @selector_bucket_1, @selector_bucket_2

  selector_bucket_2:
      %8 = xor 0xac44dd3c, %2
      %9 = iszero %8
      assert %9
      %11 = calldatasize
      %12 = gt 68, %11
      %10 = callvalue
      %13 = or %10, %12
      %14 = iszero %13
      assert %14
      mstore 448, 7
      mstore 480, 0x74657374696e6700000000000000000000000000000000000000000000000000
      mcopy 256, 448, 39
      %alloca_4_19_0:1 = 999
      jmp @"external 0 fooBar(Bytes[100],int128,Bytes[100],uint256)_common"

  selector_bucket_1:
      %21 = xor 0x6078d402, %2
      %22 = iszero %21
      assert %22
      %24 = calldatasize
      %25 = gt 100, %24
      %23 = callvalue
      %26 = or %23, %25
      %27 = iszero %26
      assert %27
      %28 = calldataload 68
      %29 = add 4, %28
      %31 = calldataload %29
      %33 = lt 100, %31
      %34 = iszero %33
      assert %34
      %36 = add 32, %31
      calldatacopy 256, %29, %36
      %alloca_4_19_0:2 = 999
      jmp @"external 0 fooBar(Bytes[100],int128,Bytes[100],uint256)_common"

  selector_bucket_0:
      %39 = xor 0x8ae972f7, %2
      %40 = iszero %39
      assert %40
      %42 = calldatasize
      %43 = gt 132, %42
      %41 = callvalue
      %44 = or %41, %43
      %45 = iszero %44
      assert %45
      %46 = calldataload 68
      %47 = add 4, %46
      %49 = calldataload %47
      %51 = lt 100, %49
      %52 = iszero %51
      assert %52
      %54 = add 32, %49
      calldatacopy 256, %47, %54
      %56 = calldataload 100
      %alloca_4_19_0:3 = %56
      jmp @"external 0 fooBar(Bytes[100],int128,Bytes[100],uint256)_common"

  "external 0 fooBar(Bytes[100],int128,Bytes[100],uint256)_common":
      %alloca_4_19_0 = phi @selector_bucket_2, %alloca_4_19_0:1, @selector_bucket_1, %alloca_4_19_0:2, @selector_bucket_0, %alloca_4_19_0:3  # noqa: E501
      %57 = calldataload 4
      %58 = add 4, %57
      %60 = calldataload %58
      %62 = lt 100, %60
      %63 = iszero %62
      assert %63
      %65 = add 32, %60
      calldatacopy 64, %58, %65
      %68 = calldataload 36
      %70 = signextend 15, %68
      %71 = xor %68, %70
      %72 = iszero %71
      assert %72
      mstore 512, 128
      %78 = mload 64
      %79 = add 32, %78
      mcopy 640, 64, %79
      %81 = mload 640
      %87 = sub 0, %81
      %88 = and 31, %87
      %86 = calldatasize
      %84 = add 672, %81
      calldatacopy %84, %86, %88
      %89 = mload 640
      mstore 544, %68
      %90 = add 32, %89
      %91 = add 31, %90
      %93 = and 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0, %91
      %94 = add 128, %93
      mstore 576, %94
      %100 = mload 256
      %101 = add 32, %100
      %98 = add 512, %94
      mcopy %98, 256, %101
      %103 = mload %98
      %109 = sub 0, %103
      %110 = and 31, %109
      %108 = calldatasize
      %105 = add 32, %98
      %106 = add %105, %103
      calldatacopy %106, %108, %110
      %111 = mload %98
      mstore 608, %alloca_4_19_0
      %112 = add 32, %111
      %113 = add 31, %112
      %115 = and 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0, %113
      %116 = add %94, %115
      return 512, %116
    """
    _check_pre_post(pre, pre, hevm=False)


# for future implementation of better escape analysis and alias analysis
@pytest.mark.xfail
def test_non_volatile_location_store():
    pre = """
    _global:
      %1 = calldataload 0
      mstore %1, 1
      ret %1
    """
    post = """
    _global:
      %1 = calldataload 0
      nop
      ret %1
    """
    _check_pre_post(pre, post, hevm=False)


def test_volatile_external_location_store():
    pre = """
    _global:
      %1 = source
      %2 = source
      mstore %1, 1
      ret %2
    """
    post = """
    _global:
      %1 = source
      %2 = source
      mstore %1, 1
      ret %2
    """
    _check_pre_post(pre, post, hevm=False)


def test_volatile_derived_location_store():
    pre = """
    _global:
      %1 = source
      %2 = source
      %3 = add %1, 32
      mstore %3, 1
      ret %2
    """
    post = """
    _global:
      %1 = source
      %2 = source
      %3 = add %1, 32
      mstore %3, 1
      ret %2
    """
    _check_pre_post(pre, post, hevm=False)


def test_unknown_size_store():
    pre = """
    _global:
      %1 = calldataload 0
      mstore 0, 1
      mcopy 128, 32, %1
      %2 = mload 32
      sink %2
    """
    post = """
    _global:
      %1 = calldataload 0
      nop
      mcopy 128, 32, %1
      %2 = mload 32
      sink %2
    """
    _check_pre_post(pre, post, hevm=False)


def test_unknown_size_overwriting_store():
    pre = """
    _global:
      %1 = calldataload 0
      mstore 0, 1
      mcopy 128, 31, %1
      %2 = mload 32
      sink %2
    """
    post = """
    _global:
      %1 = calldataload 0
      mstore 0, 1
      mcopy 128, 31, %1
      %2 = mload 32
      sink %2
    """
    _check_pre_post(pre, post, hevm=False)


_persistent_address_spaces = (STORAGE, TRANSIENT)


def _check_pre_post_generic(pre, post, addr_space):
    VolatilePrePostChecker([DeadStoreElimination], addr_space=addr_space)(pre, post)


@pytest.mark.parametrize("addr_space", _persistent_address_spaces)
def test_storage_basic_dead_store(addr_space):
    pre = f"""
        _global:
            {addr_space.store_op} 0, 1
            stop
    """
    post = f"""
        _global:
            {addr_space.store_op} 0, 1
            stop
    """
    _check_pre_post_generic(pre, post, addr_space)


@pytest.mark.parametrize("addr_space", _persistent_address_spaces)
def test_storage_basic_dead_store_clobbered(addr_space):
    pre = f"""
        _global:
            {addr_space.store_op} 0, 1
            {addr_space.store_op} 0, 2
            stop
    """
    post = f"""
        _global:
            nop
            {addr_space.store_op} 0, 2
            stop
    """
    _check_pre_post_generic(pre, post, addr_space)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%1", "@then", "@else"))
@pytest.mark.parametrize("addr_space", _persistent_address_spaces)
def test_storage_dead_store_branch_success(jnz, addr_space):
    pre = f"""
        _global:
            %1 = calldataload 0
            {addr_space.store_op} 0, 1 ; not dead as first branches succeeds
            {jnz}
        then:
            sink %1
        else:
            {addr_space.store_op} 0, 2
            sink %1
    """
    post = f"""
        _global:
            %1 = calldataload 0
            {addr_space.store_op} 0, 1
            {jnz}
        then:
            sink %1
        else:
            {addr_space.store_op} 0, 2
            sink %1
    """
    _check_pre_post_generic(pre, post, addr_space)


@pytest.mark.parametrize("jnz", _generate_jnz_configurations("%1", "@then", "@else"))
@pytest.mark.parametrize("addr_space", _persistent_address_spaces)
def test_storage_dead_store_branch_revert(jnz, addr_space):
    pre = f"""
        _global:
            %1 = calldataload 0
            {addr_space.store_op} 0, 1 ; dead as first branch reverts second clobbers
            {jnz}
        then:
            revert 0, 0
        else:
            {addr_space.store_op} 0, 2
            sink %1
    """
    post = f"""
        _global:
            %1 = calldataload 0
            nop
            {jnz}
        then:
            revert 0, 0
        else:
            {addr_space.store_op} 0, 2
            sink %1
    """
    _check_pre_post_generic(pre, post, addr_space)
