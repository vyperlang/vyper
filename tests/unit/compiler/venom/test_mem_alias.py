from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.mem_alias import MemoryAliasAnalysis
from vyper.venom.basicblock import EMPTY_MEMORY_ACCESS, FULL_MEMORY_ACCESS, IRLabel, MemoryLocation
from vyper.venom.parser import parse_venom


def test_may_alias_full_memory_access():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    loc1 = MemoryLocation(offset=0, size=32)
    assert alias.may_alias(
        FULL_MEMORY_ACCESS, loc1
    ), "FULL_MEMORY_ACCESS should alias with regular location"
    assert alias.may_alias(
        loc1, FULL_MEMORY_ACCESS
    ), "FULL_MEMORY_ACCESS should alias with regular location"

    assert not alias.may_alias(
        FULL_MEMORY_ACCESS, EMPTY_MEMORY_ACCESS
    ), "FULL_MEMORY_ACCESS should not alias with EMPTY_MEMORY_ACCESS"
    assert not alias.may_alias(
        EMPTY_MEMORY_ACCESS, FULL_MEMORY_ACCESS
    ), "FULL_MEMORY_ACCESS should not alias with EMPTY_MEMORY_ACCESS"

    assert alias.may_alias(
        FULL_MEMORY_ACCESS, FULL_MEMORY_ACCESS
    ), "FULL_MEMORY_ACCESS should alias with itself"

    loc1 = MemoryLocation(offset=0, size=32)
    assert not alias.may_alias(
        EMPTY_MEMORY_ACCESS, loc1
    ), "EMPTY_MEMORY_ACCESS should not alias with regular location"
    assert not alias.may_alias(
        loc1, EMPTY_MEMORY_ACCESS
    ), "EMPTY_MEMORY_ACCESS should not alias with regular location"

    assert not alias.may_alias(
        EMPTY_MEMORY_ACCESS, EMPTY_MEMORY_ACCESS
    ), "EMPTY_MEMORY_ACCESS should not alias with itself"


def test_may_alias_volatile():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    volatile_loc = MemoryLocation(offset=0, size=32, is_volatile=True)
    regular_loc = MemoryLocation(offset=0, size=32)
    assert alias.may_alias(
        volatile_loc, regular_loc
    ), "Volatile location should alias with overlapping regular location"
    assert alias.may_alias(
        regular_loc, volatile_loc
    ), "Regular location should alias with overlapping volatile location"

    non_overlapping_loc = MemoryLocation(offset=32, size=32)
    assert not alias.may_alias(
        volatile_loc, non_overlapping_loc
    ), "Volatile location should not alias with non-overlapping location"
    assert not alias.may_alias(
        non_overlapping_loc, volatile_loc
    ), "Non-overlapping location should not alias with volatile location"


def test_mark_volatile():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    loc1 = MemoryLocation(offset=0, size=32)
    loc2 = MemoryLocation(offset=0, size=32)
    loc3 = MemoryLocation(offset=32, size=32)

    alias._analyze_mem_location(loc1)
    alias._analyze_mem_location(loc2)
    alias._analyze_mem_location(loc3)

    volatile_loc = alias.mark_volatile(loc1)

    assert volatile_loc.is_volatile, "Marked location should be volatile"
    assert volatile_loc.offset == loc1.offset, "Volatile location should have same offset"
    assert volatile_loc.size == loc1.size, "Volatile location should have same size"

    assert volatile_loc in alias.alias_sets, "Volatile location should be in alias sets"
    assert (
        loc1 in alias.alias_sets[volatile_loc]
    ), "Original location should be in volatile location's alias set"
    assert (
        volatile_loc in alias.alias_sets[loc1]
    ), "Volatile location should be in original location's alias set"
    assert (
        loc2 in alias.alias_sets[volatile_loc]
    ), "Aliasing location should be in volatile location's alias set"
    assert (
        volatile_loc in alias.alias_sets[loc2]
    ), "Volatile location should be in aliasing location's alias set"
    assert (
        loc3 not in alias.alias_sets[volatile_loc]
    ), "Non-aliasing location should not be in volatile location's alias set"


def test_may_alias_with_alias_sets():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    loc1 = MemoryLocation(offset=0, size=32)
    loc2 = MemoryLocation(offset=0, size=32)
    loc3 = MemoryLocation(offset=32, size=32)

    alias._analyze_mem_location(loc1)
    alias._analyze_mem_location(loc2)
    alias._analyze_mem_location(loc3)

    assert alias.may_alias(loc1, loc2), "Locations in same alias set should alias"
    assert not alias.may_alias(loc1, loc3), "Locations in different alias sets should not alias"

    # Test may_alias with new location not in alias sets
    loc4 = MemoryLocation(offset=0, size=32)
    assert alias.may_alias(loc1, loc4), "New location should alias with existing location"
    assert loc4 in alias.alias_sets, "New location should be added to alias sets"


def test_mark_volatile_edge_cases():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    # Test marking a location not in alias sets
    loc1 = MemoryLocation(offset=0, size=32)
    volatile_loc = alias.mark_volatile(loc1)
    assert volatile_loc.is_volatile, "Marked location should be volatile"
    assert (
        volatile_loc not in alias.alias_sets
    ), "Volatile location should not be in alias sets if original wasn't"

    # Test marking a location with no aliases
    loc2 = MemoryLocation(offset=0, size=32)
    alias._analyze_mem_location(loc2)
    volatile_loc2 = alias.mark_volatile(loc2)
    assert volatile_loc2 in alias.alias_sets, "Volatile location should be in alias sets"
    assert (
        len(alias.alias_sets[volatile_loc2]) == 2
    ), "Volatile location should only alias with original location"
    assert (
        loc2 in alias.alias_sets[volatile_loc2]
    ), "Original location should be in volatile location's alias set"
    assert (
        volatile_loc2 in alias.alias_sets[loc2]
    ), "Volatile location should be in original location's alias set"


def test_may_alias_edge_cases():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    assert not alias._may_alias(
        FULL_MEMORY_ACCESS, EMPTY_MEMORY_ACCESS
    ), "FULL_MEMORY_ACCESS should not alias with EMPTY_MEMORY_ACCESS"
    assert not alias._may_alias(
        EMPTY_MEMORY_ACCESS, FULL_MEMORY_ACCESS
    ), "EMPTY_MEMORY_ACCESS should not alias with FULL_MEMORY_ACCESS"

    loc1 = MemoryLocation(offset=0, size=32)
    assert not alias._may_alias(
        EMPTY_MEMORY_ACCESS, loc1
    ), "EMPTY_MEMORY_ACCESS should not alias with regular location"
    assert not alias._may_alias(
        loc1, EMPTY_MEMORY_ACCESS
    ), "Regular location should not alias with EMPTY_MEMORY_ACCESS"

    volatile_loc = MemoryLocation(offset=0, size=32, is_volatile=True)
    non_overlapping_loc = MemoryLocation(offset=32, size=32)
    assert not alias.may_alias(
        volatile_loc, non_overlapping_loc
    ), "Volatile location should not alias with non-overlapping location"

    loc2 = MemoryLocation(offset=0, size=32)
    loc3 = MemoryLocation(offset=32, size=32)
    assert alias.may_alias(loc2, loc3) == alias._may_alias(
        loc2, loc3
    ), "may_alias should use _may_alias for locations not in alias sets"

    loc4 = MemoryLocation(offset=0, size=32)
    loc5 = MemoryLocation(offset=0, size=32)
    loc6 = MemoryLocation(offset=32, size=32)
    alias._analyze_mem_location(loc4)
    alias._analyze_mem_location(loc5)
    alias._analyze_mem_location(loc6)
    volatile_loc2 = alias.mark_volatile(loc4)
    assert (
        volatile_loc2 in alias.alias_sets[loc5]
    ), "Volatile location should be in aliasing location's alias set"
    assert (
        loc5 in alias.alias_sets[volatile_loc2]
    ), "Aliasing location should be in volatile location's alias set"


def test_may_alias_edge_cases2():
    pre = """
    function _global {
        _global:
            stop
    }
    """
    ctx = parse_venom(pre)
    fn = ctx.functions[IRLabel("_global")]
    ac = IRAnalysesCache(fn)
    alias = MemoryAliasAnalysis(ac, fn)
    alias.analyze()

    loc1 = MemoryLocation(offset=0, size=32)
    assert alias._may_alias(
        FULL_MEMORY_ACCESS, loc1
    ), "FULL_MEMORY_ACCESS should alias with regular location"

    assert not alias._may_alias(
        EMPTY_MEMORY_ACCESS, loc1
    ), "EMPTY_MEMORY_ACCESS should not alias with regular location"

    volatile_loc = MemoryLocation(offset=0, size=32, is_volatile=True)
    overlapping_loc = MemoryLocation(offset=16, size=32)
    assert alias.may_alias(
        volatile_loc, overlapping_loc
    ), "Volatile location should alias with overlapping location"

    loc2 = MemoryLocation(offset=0, size=64)
    loc3 = MemoryLocation(offset=32, size=64)
    result = alias.may_alias(loc2, loc3)
    assert result == alias._may_alias(
        loc2, loc3
    ), "may_alias should use _may_alias for locations not in alias sets"

    loc4 = MemoryLocation(offset=0, size=32)
    loc5 = MemoryLocation(offset=0, size=32)
    loc6 = MemoryLocation(offset=0, size=32)
    alias._analyze_mem_location(loc4)
    alias._analyze_mem_location(loc5)
    alias._analyze_mem_location(loc6)
    volatile_loc2 = alias.mark_volatile(loc4)
    assert (
        len(alias.alias_sets[volatile_loc2]) >= 3
    ), "Volatile location should have multiple aliases"
    assert all(
        volatile_loc2 in alias.alias_sets[loc] for loc in [loc4, loc5, loc6]
    ), "Volatile location should be in all aliasing locations' sets"
