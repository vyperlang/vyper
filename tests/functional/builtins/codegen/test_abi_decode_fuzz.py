from dataclasses import dataclass

import hypothesis as hp
import pytest

import tests.fuzzing_strategies as vfz
from tests.evm_backends.base_env import EvmError
from vyper.codegen.core import calculate_type_for_external_return, needs_external_call_wrap
from vyper.semantics.types import (
    BytesT,
    DArrayT,
    HashMapT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
    VyperType,
)

from .abi_decode import DecodeError, spec_decode

pytestmark = pytest.mark.fuzzing

MAX_MUTATIONS = 33
PARALLELISM = 1

_settings = dict(
    report_multiple_bugs=False,
    # verbosity=hp.Verbosity.verbose,
    suppress_health_check=(
        hp.HealthCheck.data_too_large,
        hp.HealthCheck.too_slow,
        hp.HealthCheck.large_base_example,
        hp.HealthCheck.nested_given,
    ),
    phases=(
        hp.Phase.explicit,
        hp.Phase.reuse,
        hp.Phase.generate,
        hp.Phase.target,
        # Phase.shrink,  # can force long waiting for examples
        # Phase.explain,  # not helpful here
    ),
)


@dataclass(frozen=True)
class _TypeStats:
    nesting: int = 0
    num_dynamic_types: int = 0  # number of dynamic types in the type
    breadth: int = 0  # e.g. int16[50] has higher breadth than int16[1]
    width: int = 0  # size of type


def _type_stats(typ: VyperType) -> _TypeStats:
    def _finalize():  # little trick to save re-typing the arguments
        width = typ.memory_bytes_required
        return _TypeStats(
            nesting=nesting, num_dynamic_types=num_dynamic_types, breadth=breadth, width=width
        )

    if typ._is_prim_word:
        nesting = 0
        breadth = 1
        num_dynamic_types = 0
        return _finalize()

    if isinstance(typ, (BytesT, StringT)):
        nesting = 0
        breadth = 1  # idk
        num_dynamic_types = 1
        return _finalize()

    if isinstance(typ, TupleT):
        substats = [_type_stats(t) for t in typ.member_types]
        nesting = 1 + max(s.nesting for s in substats)
        breadth = max(typ.length, *[s.breadth for s in substats])
        num_dynamic_types = sum(s.num_dynamic_types for s in substats)
        return _finalize()

    if isinstance(typ, StructT):
        substats = [_type_stats(t) for t in typ.tuple_members()]
        nesting = 1 + max(s.nesting for s in substats)
        breadth = max(len(typ.member_types), *[s.breadth for s in substats])
        num_dynamic_types = sum(s.num_dynamic_types for s in substats)
        return _finalize()

    if isinstance(typ, DArrayT):
        substat = _type_stats(typ.value_type)
        nesting = 1 + substat.nesting
        breadth = max(typ.count, substat.breadth)
        num_dynamic_types = 1 + substat.num_dynamic_types
        return _finalize()

    if isinstance(typ, SArrayT):
        substat = _type_stats(typ.value_type)
        nesting = 1 + substat.nesting
        breadth = max(typ.count, substat.breadth)
        num_dynamic_types = substat.num_dynamic_types
        return _finalize()

    raise RuntimeError("unreachable")


@pytest.fixture(scope="module")
def payload_copier(get_contract_from_ir):
    # some contract which will return the buffer passed to it
    # note: hardcode the location of the bytestring
    ir = [
        "with",
        "length",
        ["calldataload", 36],
        ["seq", ["calldatacopy", 0, 68, "length"], ["return", 0, "length"]],
    ]
    return get_contract_from_ir(["deploy", 0, ir, 0])


PARALLELISM = 1  # increase on fuzzer box


# NOTE: this is a heavy test. 100 types * 100 payloads per type can take
# 3-4minutes on a regular CPU core.
@pytest.mark.parametrize("_n", list(range(PARALLELISM)))
# TODO should we control the nesting?
@hp.given(typ=vfz.vyper_type(skip=[HashMapT]))
@hp.settings(max_examples=100, **_settings)
def test_abi_decode_fuzz(_n, typ, get_contract, tx_failed, payload_copier, env):
    source_fragments, typ = typ
    # import time
    # t0 = time.time()
    # print("ENTER", typ)

    wrapped_type = calculate_type_for_external_return(typ)

    stats = _type_stats(typ)
    # for k, v in asdict(stats).items():
    #     event(k, v)
    hp.target(stats.num_dynamic_types)
    # hp.target(typ.abi_type.is_dynamic() + typ.abi_type.is_complex_type()))

    # add max_mutations bytes worth of padding so we don't just get caught
    # by bytes length check at function entry
    type_bound = wrapped_type.abi_type.size_bound()
    buffer_bound = type_bound + MAX_MUTATIONS

    preamble = "\n\n".join(source_fragments)
    type_str = str(typ)  # annotation in vyper code

    code = f"""
{preamble}

@external
def run(xs: Bytes[{buffer_bound}]) -> {type_str}:
    ret: {type_str} = abi_decode(xs, {type_str})
    return ret

interface Foo:
    def foo(xs: Bytes[{buffer_bound}]) -> {type_str}: view  # STATICCALL
    def bar(xs: Bytes[{buffer_bound}]) -> {type_str}: nonpayable  # CALL

@external
def run2(xs: Bytes[{buffer_bound}], copier: Foo) -> {type_str}:
    assert len(xs) <= {type_bound}
    return staticcall copier.foo(xs)

@external
def run3(xs: Bytes[{buffer_bound}], copier: Foo) -> {type_str}:
    assert len(xs) <= {type_bound}
    return (extcall copier.bar(xs))
    """
    try:
        c = get_contract(code)
    except EvmError as e:
        if env.contract_size_limit_error in str(e):
            hp.assume(False)
    # print(code)
    hp.note(code)
    c = get_contract(code)

    @hp.given(data=vfz.payload_from(wrapped_type))
    @hp.settings(max_examples=100, **_settings)
    def _fuzz(data):
        hp.note(f"type: {typ}")
        hp.note(f"abi_t: {wrapped_type.abi_type.selector_name()}")
        hp.note(data.hex())

        try:
            expected = spec_decode(wrapped_type, data)

            # unwrap if necessary
            if needs_external_call_wrap(typ):
                assert isinstance(expected, tuple)
                (expected,) = expected

            hp.note(f"expected {expected}")
            assert expected == c.run(data)
            assert expected == c.run2(data, payload_copier.address)
            assert expected == c.run3(data, payload_copier.address)

        except DecodeError:
            # note EvmError includes reverts *and* exceptional halts.
            # we can get OOG during abi decoding due to how
            # `_abi_payload_size()` works
            hp.note("expect failure")
            with tx_failed(EvmError):
                c.run(data)
            with tx_failed(EvmError):
                c.run2(data, payload_copier.address)
            with tx_failed(EvmError):
                c.run3(data, payload_copier.address)

    _fuzz()

    # t1 = time.time()
    # print(f"elapsed {t1 - t0}s")


@pytest.mark.parametrize("_n", list(range(PARALLELISM)))
@hp.given(typ=vfz.vyper_type(skip=[HashMapT]))
@hp.settings(max_examples=100, **_settings)
def test_abi_decode_no_wrap_fuzz(_n, typ, get_contract, tx_failed, env):
    source_fragments, typ = typ
    # import time
    # t0 = time.time()
    # print("ENTER", typ)

    stats = _type_stats(typ)
    hp.target(stats.num_dynamic_types)

    # add max_mutations bytes worth of padding so we don't just get caught
    # by bytes length check at function entry
    type_bound = typ.abi_type.size_bound()
    buffer_bound = type_bound + MAX_MUTATIONS

    type_str = str(typ)  # annotation in vyper code
    preamble = "\n\n".join(source_fragments)

    code = f"""
{preamble}

@external
def run(xs: Bytes[{buffer_bound}]) -> {type_str}:
    ret: {type_str} = abi_decode(xs, {type_str}, unwrap_tuple=False)
    return ret
    """
    try:
        c = get_contract(code)
    except EvmError as e:
        if env.contract_size_limit_error in str(e):
            hp.assume(False)

    @hp.given(data=vfz.payload_from(typ))
    @hp.settings(max_examples=100, **_settings)
    def _fuzz(data):
        hp.note(code)
        hp.note(data.hex())
        try:
            expected = spec_decode(typ, data)
            hp.note(f"expected {expected}")
            assert expected == c.run(data)
        except DecodeError:
            hp.note("expect failure")
            with tx_failed(EvmError):
                c.run(data)

    _fuzz()

    # t1 = time.time()
    # print(f"elapsed {t1 - t0}s")
