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
        from vyper.venom.basicblock import IROperand, MemoryLocation

        self.pass_objects.clear()

        if hevm is None:
            hevm = self.default_hevm

        pre_ctx = parse_from_basic_block(pre)
        for fn in pre_ctx.functions.values():
            ac = IRAnalysesCache(fn)

            mem_ssa = ac.request_analysis(MemSSA)

            for address, size in self.volatile_locations:
                volatile_loc = MemoryLocation(
                    base=IROperand(address), offset=0, size=size, is_volatile=True
                )
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
