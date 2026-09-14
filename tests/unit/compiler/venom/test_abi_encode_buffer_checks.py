import pytest

from vyper.codegen_venom.abi import abi_encode_to_buf, abi_encode_values_to_buf
from vyper.codegen_venom.context import VenomCodegenContext
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import INF, BytesT, TupleT
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext

BOUNDED_T = TupleT((BytesT(10),))
UNBOUNDED_T = TupleT((BytesT(INF),))


@pytest.fixture
def ctx():
    irctx = IRContext()
    fn = irctx.create_function("t")
    return VenomCodegenContext(module_ctx=None, builder=VenomBuilder(irctx, fn))


def _encode(ctx, typ, bufsz):
    b = ctx.builder
    return abi_encode_to_buf(ctx, b.alloca(64), b.alloca(64), typ, bufsz)


def _encode_values(ctx, typ, bufsz):
    b = ctx.builder
    member_t = typ.member_types[0]
    if typ is UNBOUNDED_T:
        member = ctx.dynamic_memory_value(b.alloca(64), member_t)
    else:
        member = ctx.new_temporary_value(member_t)
    return abi_encode_values_to_buf(ctx, b.alloca(64), [member], typ, bufsz)


@pytest.mark.parametrize("encode", [_encode, _encode_values])
def test_buffer_smaller_than_size_bound_panics(ctx, encode):
    size_bound = BOUNDED_T.abi_type.size_bound()
    with pytest.raises(CompilerPanic, match="buffer provided to abi_encode not large enough"):
        encode(ctx, BOUNDED_T, size_bound - 1)


@pytest.mark.parametrize("encode", [_encode, _encode_values])
def test_static_buffer_for_unbounded_type_panics(ctx, encode):
    with pytest.raises(CompilerPanic, match="unbounded type"):
        encode(ctx, UNBOUNDED_T, 64)


@pytest.mark.parametrize("encode", [_encode, _encode_values])
def test_buffer_of_exactly_size_bound_is_accepted(ctx, encode):
    encode(ctx, BOUNDED_T, BOUNDED_T.abi_type.size_bound())


@pytest.mark.parametrize("encode", [_encode, _encode_values])
@pytest.mark.parametrize("typ", [BOUNDED_T, UNBOUNDED_T])
def test_runtime_sized_buffer_is_not_checked(ctx, encode, typ):
    encode(ctx, typ, None)
