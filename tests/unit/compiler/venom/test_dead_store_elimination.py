import pytest

from tests.venom_utils import PrePostChecker, assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.mem_ssa import MemSSA
from vyper.venom.passes import DeadStoreElimination
from vyper.venom.passes.base_pass import IRPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([DeadStoreElimination])


class VolatilePrePostChecker(PrePostChecker):
    def __init__(self, passes: list[type], volatile_locations=None, post=None, default_hevm=True):
        super().__init__(passes, post, default_hevm)
        if volatile_locations is None:
            self.volatile_locations = []
        else:
            self.volatile_locations = volatile_locations

    def __call__(self, pre: str, post: str, hevm: bool | None = None) -> list[IRPass]:
        from vyper.venom.basicblock import MemoryLocation

        self.pass_objects.clear()

        if hevm is None:
            hevm = self.default_hevm

        pre_ctx = parse_from_basic_block(pre)
        for fn in pre_ctx.functions.values():
            ac = IRAnalysesCache(fn)

            mem_ssa = ac.request_analysis(MemSSA)

            for address, size in self.volatile_locations:
                volatile_loc = MemoryLocation(offset=address, size=size, is_volatile=True)
                mem_ssa.mark_location_volatile(volatile_loc)

            for p in self.passes:
                obj = p(ac, fn)
                self.pass_objects.append(obj)
                obj.run_pass()

        post_ctx = parse_from_basic_block(post)
        for fn in post_ctx.functions.values():
            ac = IRAnalysesCache(fn)
            for p in self.post_passes:
                obj = p(ac, fn)
                self.pass_objects.append(obj)
                obj.run_pass()

        assert_ctx_eq(pre_ctx, post_ctx)

        if hevm:
            from tests.hevm import hevm_check_venom

            hevm_check_venom(pre, post)

        return self.pass_objects


def test_basic_dead_store():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1  ; Dead store - overwritten before read
            mstore 0, 10     ; Dead store - overwritten before read
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            nop
            nop
            mstore 0, %val2
            %loaded = mload 0
            stop
    """
    _check_pre_post(pre, post)


def test_basic_not_dead_store():
    pre = """
        _global:
            %1 = param
            mstore %1, 1
            stop
    """
    _check_pre_post(pre, pre)


def test_basic_not_dead_store_with_mload():
    pre = """
        _global:
            %1 = param
            mstore 0, 1
            mstore 32, 2
            %2 = mload 0
            stop
    """
    post = """
        _global:
            %1 = param
            mstore 0, 1
            nop
            %2 = mload 0
            stop
    """
    _check_pre_post(pre, post)


def test_basic_not_dead_store_with_return():
    pre = """
        _global:
            %1 = param
            mstore 0, 1
            mstore 32, 2
            return 0, 32
    """
    post = """
        _global:
            %1 = param
            mstore 0, 1
            nop
            return 0, 32
    """
    _check_pre_post(pre, post)


def test_never_read_store():
    pre = """
        _global:
            %val = 42
            mstore 0, %val  ; Dead store - never read
            stop
    """
    post = """
        _global:
            %val = 42
            nop
            stop
    """
    _check_pre_post(pre, post)


def test_live_store():
    pre = """
        _global:
            %val = 42
            mstore 0, %val
            %loaded = mload 0  ; Makes the store live
            stop
    """
    _check_pre_post(pre, pre)  # Should not change


def test_dead_store_different_locations():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1   ; Dead store - never read
            mstore 32, %val2  ; Live store
            %loaded = mload 32
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            nop
            mstore 32, %val2
            %loaded = mload 32
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


def test_dead_store_in_branches():
    pre = """
        _global:
            %cond = 1
            %val1 = 42
            %val2 = 24
            jnz %cond, @then, @else
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
    post = """
        _global:
            %cond = 1
            %val1 = 42
            %val2 = 24
            jnz %cond, @then, @else
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


def test_dead_store_in_loop():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            %i = 0
            mstore 0, %val1  ; Dead store - overwritten in loop before any read
            jmp @loop
        loop:
            %cond = lt %i, 5
            jnz %cond, @body, @exit
        body:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            %i = 0
            nop
            jmp @loop
        loop:
            %cond = lt %i, 5
            jnz %cond, @body, @exit
        body:
            mstore 0, %val2
            %loaded = mload 0
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    _check_pre_post(pre, post)


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

    post = """
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
    _check_pre_post(pre, post, hevm=False)


def test_call_overwrites_previous_stores():
    pre = """
        _global:
            ; Store at the location that will be overwritten
            ; by call and never read before overwriting
            mstore 64, 42  ; This should be eliminated due to
                           ; call overwriting it before any read

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

    post = """
        _global:
            ; Store at the location that will be overwritten
            ; by call and never read before overwriting
            nop

            ; Store value needed for call
            mstore 32, 24  ; This should remain as it's used by call

            ; Call has both memory read (32) and write (64) effects
            %success = call 1000, 0x12, 0, 32, 32, 64, 32

            ; Read the call result from memory (at the location
            ; where val1 was stored but got overwritten)
            %result = mload 64

            return %result, 32
    """
    _check_pre_post(pre, post, hevm=False)


def test_call_raw_example():
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
    _check_pre_post(pre, post)


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
    post = """
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
    _check_pre_post(pre, post, hevm=False)
