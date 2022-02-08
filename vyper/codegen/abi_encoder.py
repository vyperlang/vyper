from vyper.codegen.core import (
    add_ofst,
    get_dyn_array_count,
    get_element_ptr,
    make_setter,
    store_op,
    zero_pad,
)
from vyper.codegen.lll_node import LLLnode
from vyper.codegen.types import BaseType, ByteArrayLike, DArrayType, SArrayType, TupleLike
from vyper.exceptions import CompilerPanic


# turn an lll node into a list, based on its type.
def _deconstruct_complex_type(lll_node, pos=None):
    lll_t = lll_node.typ
    assert isinstance(lll_t, (TupleLike, SArrayType))

    if lll_node.value == "multi":  # is literal
        return lll_node.args

    if isinstance(lll_t, TupleLike):
        ks = lll_t.tuple_keys()
    else:
        ks = [LLLnode.from_list(i, "uint256") for i in range(lll_t.count)]

    ret = []
    for k in ks:
        ret.append(get_element_ptr(lll_node, k, pos, array_bounds_check=False))
    return ret


# encode a child element of a complex type
def _encode_child_helper(buf, child, static_ofst, dyn_ofst, context, pos=None):
    child_abi_t = child.typ.abi_type

    static_loc = add_ofst(LLLnode.from_list(buf), static_ofst)

    ret = ["seq"]

    if not child_abi_t.is_dynamic():
        # easy
        ret.append(abi_encode(static_loc, child, context, pos=pos, returns_len=False))
    else:
        # hard
        ret.append(["mstore", static_loc, dyn_ofst])

        # TODO optimize: special case where there is only one dynamic
        # member, the location is statically known.
        child_dst = ["add", buf, dyn_ofst]

        child_len = abi_encode(child_dst, child, context, pos=pos, returns_len=True)

        # increment dyn ofst for return_len
        # (optimization note:
        #   if non-returning and this is the last dyn member in
        #   the tuple, this set can be elided.)
        ret.append(["set", dyn_ofst, ["add", dyn_ofst, child_len]])

    return ret


def _encode_dyn_array_helper(dst, lll_node, context, pos):
    # if it's a literal, first serialize to memory as we
    # don't have a compile-time abi encoder
    # TODO handle this upstream somewhere
    if lll_node.value == "multi":
        buf = context.new_internal_variable(dst.typ)
        buf = LLLnode.from_list(buf, typ=dst.typ, location="memory")
        return [
            "seq",
            make_setter(buf, lll_node, pos),
            ["set", "dyn_ofst", abi_encode(dst, buf, context, pos, returns_len=True)],
        ]

    subtyp = lll_node.typ.subtype
    child_abi_t = subtyp.abi_type

    ret = ["seq"]

    len_ = get_dyn_array_count(lll_node)
    with len_.cache_when_complex("len") as (b, len_):
        # set the length word
        ret.append([store_op(dst.location), dst, len_])

        # prepare the loop
        t = BaseType("uint256")
        i = LLLnode.from_list(context.fresh_varname("ix"), typ=t)

        # offset of the i'th element in lll_node
        child_location = get_element_ptr(lll_node, i, array_bounds_check=False, pos=pos)

        # offset of the i'th element in dst
        dst = add_ofst(dst, 32)  # jump past length word
        static_elem_size = child_abi_t.embedded_static_size()
        static_ofst = ["mul", i, static_elem_size]
        loop_body = _encode_child_helper(
            dst, child_location, static_ofst, "dyn_child_ofst", context, pos=pos
        )
        loop = ["repeat", i, 0, len_, lll_node.typ.count, loop_body]

        x = ["seq", loop, "dyn_child_ofst"]
        start_dyn_ofst = ["mul", len_, static_elem_size]
        run_children = ["with", "dyn_child_ofst", start_dyn_ofst, x]
        new_dyn_ofst = ["add", "dyn_ofst", run_children]
        # size of dynarray is size of encoded children + size of the length word
        # TODO optimize by adding 32 to the initial value of dyn_ofst
        new_dyn_ofst = ["add", 32, new_dyn_ofst]
        ret.append(["set", "dyn_ofst", new_dyn_ofst])

        return b.resolve(ret)


# assume dst is a pointer to a buffer located in memory which has at
# least static_size + dynamic_size_bound allocated.
# The basic strategy is this:
#   First, it is helpful to keep track of what variables are location
#   dependent and which are location independent (offsets). Independent
#   locations will be denoted with variables named `_ofst`.
#   We keep at least one stack variable to keep track of our location
#   in the dynamic section. We keep a compiler variable `static_ofst`
#   keeping track of our current offset from the beginning of the static
#   section. (And if the destination is not known at compile time, we
#   allocate a stack item `dst` to keep track of it). So, 1-2 stack
#   variables for each level of "nesting" (as defined in the spec).
#   For each element `elem` of the lll_node:
#   - If `elem` is static, write its value to `dst + static_ofst` and
#     increment `static_ofst` by the size of `elem`.
#   - If it is dynamic, ensure we have initialized a pointer (a stack
#     variable named `dyn_ofst` set to the start of the dynamic section
#     (i.e. static_size of lll_node). Write the 'tail' of `elem` to the
#     dynamic section, then write current `dyn_ofst` to `dst_loc`, and
#     then increment `dyn_ofst` by the number of bytes written. Note
#     that in this step we may recurse, and the child call should return
#     a stack item representing how many bytes were written.
#     WARNING: abi_encode(bytes) != abi_encode((bytes,)) (a tuple
#     with a single bytes member). The former is encoded as <len> <data>,
#     the latter is encoded as <ofst> <len> <data>.
# performance note: takes O(n^2) compilation time
# where n is depth of data type, could be optimized but unlikely
# that users will provide deeply nested data.
# returns_len is a calling convention parameter; if set to true,
# the abi_encode routine will push the output len onto the stack,
# otherwise it will return 0 items to the stack.
def abi_encode(dst, lll_node, context, pos=None, bufsz=None, returns_len=False):

    dst = LLLnode.from_list(dst, typ=lll_node.typ, location="memory")
    abi_t = dst.typ.abi_type
    size_bound = abi_t.size_bound()

    if bufsz is not None and bufsz < size_bound:
        raise CompilerPanic("buffer provided to abi_encode not large enough")

    if size_bound < dst.typ.memory_bytes_required:
        raise CompilerPanic("Bad ABI size calc")

    annotation = f"abi_encode {lll_node.typ}"
    lll_ret = ["seq"]

    # fastpath: if there is no dynamic data, we can optimize the
    # encoding by using make_setter, since our memory encoding happens
    # to be identical to the ABI encoding.
    if not abi_t.is_dynamic():
        lll_ret.append(make_setter(dst, lll_node, pos=pos))
        if returns_len:
            lll_ret.append(abi_t.embedded_static_size())
        return LLLnode.from_list(lll_ret, pos=pos, annotation=annotation)

    # contains some computation, we need to only do it once.
    with lll_node.cache_when_complex("to_encode") as (b1, lll_node), dst.cache_when_complex(
        "dst"
    ) as (b2, dst):

        dyn_ofst = "dyn_ofst"  # current offset in the dynamic section

        if isinstance(lll_node.typ, BaseType):
            lll_ret.append(make_setter(dst, lll_node, pos=pos))
        elif isinstance(lll_node.typ, ByteArrayLike):
            # TODO optimize out repeated ceil32 calculation
            lll_ret.append(make_setter(dst, lll_node, pos=pos))
            lll_ret.append(zero_pad(dst))
        elif isinstance(lll_node.typ, DArrayType):
            lll_ret.append(_encode_dyn_array_helper(dst, lll_node, context, pos))

        elif isinstance(lll_node.typ, (TupleLike, SArrayType)):
            static_ofst = 0
            elems = _deconstruct_complex_type(lll_node)
            for e in elems:
                encode_lll = _encode_child_helper(dst, e, static_ofst, dyn_ofst, context, pos=pos)
                lll_ret.extend(encode_lll)
                static_ofst += e.typ.abi_type.embedded_static_size()

        else:
            raise CompilerPanic(f"unencodable type: {lll_node.typ}")

        # declare LLL variables.
        if returns_len:
            if not abi_t.is_dynamic():
                lll_ret.append(abi_t.embedded_static_size())
            elif isinstance(lll_node.typ, ByteArrayLike):
                # for abi purposes, return zero-padded length
                calc_len = ["ceil32", ["add", 32, ["mload", dst]]]
                lll_ret.append(calc_len)
            elif abi_t.is_complex_type():
                lll_ret.append("dyn_ofst")
            else:
                raise CompilerPanic("unknown type {lll_node.typ}")

        if abi_t.is_dynamic() and abi_t.is_complex_type():
            dyn_section_start = abi_t.static_size()
            lll_ret = ["with", dyn_ofst, dyn_section_start, lll_ret]
        else:
            pass  # skip dyn_ofst allocation if we don't need it

        return b1.resolve(b2.resolve(LLLnode.from_list(lll_ret, pos=pos, annotation=annotation)))
