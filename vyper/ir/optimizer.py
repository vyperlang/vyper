import operator
from typing import List, Optional, Union

from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, StaticAssertionException
from vyper.utils import (
    ceil32,
    evm_div,
    evm_mod,
    int_bounds,
    int_log2,
    is_power_of_two,
    signed_to_unsigned,
    unsigned_to_signed,
)

SIGNED = False
UNSIGNED = True


# unsigned: convert python num to evm unsigned word
#   e.g. unsigned=True : -1 -> 0xFF...FF
#        unsigned=False: 0xFF...FF -> -1
def _evm_int(node: IRnode, unsigned: bool = True) -> Optional[int]:
    if isinstance(node.value, int):
        ret = node.value
    else:
        return None

    if unsigned and ret < 0:
        return signed_to_unsigned(ret, 256, strict=True)
    elif not unsigned and ret > 2 ** 255 - 1:
        return unsigned_to_signed(ret, 256, strict=True)

    return ret


def _is_int(node: IRnode) -> bool:
    return isinstance(node.value, int)


def _deep_contains(node_or_list, node):
    if isinstance(node_or_list, list):
        return any(_deep_contains(t, node) for t in node_or_list)
    return node is node_or_list


arith = {
    "add": (operator.add, "+", UNSIGNED),
    "sub": (operator.sub, "-", UNSIGNED),
    "mul": (operator.mul, "*", UNSIGNED),
    "div": (evm_div, "/", UNSIGNED),
    "sdiv": (evm_div, "/", SIGNED),
    "mod": (evm_mod, "%", UNSIGNED),
    "smod": (evm_mod, "%", SIGNED),
    "exp": (operator.pow, "**", UNSIGNED),
    "eq": (operator.eq, "==", UNSIGNED),
    "ne": (operator.ne, "!=", UNSIGNED),
    "lt": (operator.lt, "<", UNSIGNED),
    "le": (operator.le, "<=", UNSIGNED),
    "gt": (operator.gt, ">", UNSIGNED),
    "ge": (operator.ge, ">=", UNSIGNED),
    "slt": (operator.lt, "<", SIGNED),
    "sle": (operator.le, "<=", SIGNED),
    "sgt": (operator.gt, ">", SIGNED),
    "sge": (operator.ge, ">=", SIGNED),
    "or": (operator.or_, "|", UNSIGNED),
    "and": (operator.and_, "&", UNSIGNED),
    "xor": (operator.xor, "^", UNSIGNED),
}

# quick typedefs, maybe move these to IRnode
IRVal = Union[str, int]
IRArgs = List[IRnode]


COMMUTATIVE_OPS = {"add", "mul", "eq", "ne", "and", "or", "xor"}
COMPARISON_OPS = {"gt", "sgt", "ge", "sge", "lt", "slt", "le", "sle"}


def _flip_comparison_op(opname):
    assert opname in COMPARISON_OPS
    if "g" in opname:
        return opname.replace("g", "l")
    if "l" in opname:
        return opname.replace("l", "g")
    raise CompilerPanic(f"bad comparison op {opname}")


# some annotations are really long. shorten them (except maybe in "verbose" mode?)
def _shorten_annotation(annotation):
    if len(annotation) > 16:
        return annotation[:16] + "..."
    return annotation


def _wrap256(x, unsigned=UNSIGNED):
    x %= 2 ** 256
    # wrap in a signed way.
    if not unsigned:
        x = unsigned_to_signed(x, 256, strict=True)
    return x


def _comparison_helper(binop, args, prefer_strict=False):
    assert binop in COMPARISON_OPS

    if _is_int(args[0]):
        binop = _flip_comparison_op(binop)
        args = [args[1], args[0]]

    unsigned = not binop.startswith("s")
    is_strict = binop.endswith("t")
    is_gt = "g" in binop

    # local version of _evm_int which defaults to the current binop's signedness
    def _int(x):
        return _evm_int(x, unsigned=unsigned)

    lo, hi = int_bounds(bits=256, signed=not unsigned)

    if is_gt:
        almost_always, never = lo, hi
        almost_never = hi - 1
    else:
        almost_always, never = hi, lo
        almost_never = lo + 1

    if is_strict and _int(args[1]) == never:
        # e.g. gt x MAX_UINT256, slt x MIN_INT256
        return (0, [])

    if not is_strict and _int(args[1]) == almost_always:
        # e.g. ge x MIN_UINT256, sle x MAX_INT256
        return (1, [])

    # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
    if (is_strict != prefer_strict and _is_int(args[1])):
        rhs = _int(args[1])

        if not is_strict and rhs == never:
            # e.g. ge x MAX_UINT256 <0>, sle x MIN_INT256
            return ("eq", args)

        if is_strict and rhs == almost_never:
            # (lt x 1)
            return ("ne", [args[0], never])

        if is_strict and rhs == almost_always:
            # e.g. gt x MIN_UINT256 <0>, slt x MAX_INT256
            return ("ne", args)

        if is_gt == is_strict:
            # x > 1 => x >= 2
            # x <= 1 => x < 2
            new_rhs = rhs + 1
        else:
            # x >= 1 => x > 0
            # x < 1 => x <= 0
            new_rhs = rhs - 1

        # if args[1] is OOB, it should have been handled above
        # in the always/never cases
        assert _wrap256(new_rhs, unsigned) == new_rhs, "bad optimizer step"

        # change the strictness of the op
        if prefer_strict:
            # e.g. "sge" => "sgt"
            new_op = binop.replace("e", "t")
        else:
            # e.g. "sgt" => "sge"
            new_op = binop.replace("t", "e")

        return (new_op, [args[0], new_rhs])

    # special cases that are not covered by others:

    if binop == "gt" and _int(args[1]) == 0:
        # improve codesize (not gas), and maybe trigger
        # downstream optimizations
        return ("iszero", [["iszero", args[0]]])


# def _optimize_arith(
#    binop: str, args: IRArgs, ann: Optional[str], parent_op: Any = None
# ) -> Tuple[IRVal, IRArgs, Optional[str]]:
def _optimize_binop(binop, args, ann, parent_op):
    fn, symb, unsigned = arith[binop]

    # local version of _evm_int which defaults to the current binop's signedness
    def _int(x, unsigned=unsigned):
        return _evm_int(x, unsigned=unsigned)

    def _wrap(x):
        return _wrap256(x, unsigned=unsigned)

    new_ann = None
    if ann is not None:
        l_ann = _shorten_annotation(args[0].annotation or str(args[0]))
        r_ann = _shorten_annotation(args[1].annotation or str(args[1]))
        new_ann = l_ann + symb + r_ann
        new_ann = f"{ann} ({new_ann})"

    def finalize(new_val, new_args):
        rollback = (args[0].is_complex_ir and not _deep_contains(new_args, args[0])) or (
            args[1].is_complex_ir and not _deep_contains(new_args, args[1])
        )

        if rollback:
            return None

        return new_val, new_args, new_ann

    if _is_int(args[0]) and _is_int(args[1]):
        # compile-time arithmetic
        left, right = _int(args[0]), _int(args[1])
        new_val = fn(left, right)
        new_val = _wrap(new_val)
        return finalize(new_val, [])

    # we can return truthy values instead of actual math
    is_truthy = parent_op in {"if", "assert", "iszero"}

    def _conservative_eq(x, y):
        # whether x evaluates to the same value as y at runtime.
        # TODO we can do better than this check, but we need to be
        # conservative in case x has side effects.
        return x.args == y.args == [] and x.value == y.value and not x.is_complex_ir

    ##
    # ARITHMETIC
    ##

    # for commutative or comparison ops, move the literal to the second
    # position to make the later logic cleaner
    if binop in COMMUTATIVE_OPS and _is_int(args[0]):
        args = [args[1], args[0]]

    ##
    # ARITHMETIC AND BITWISE OPS
    ##

    if binop in {"add", "sub", "xor", "or"} and _int(args[1]) == 0:
        # x + 0 == x - 0 == x | 0 == x ^ 0 == x
        return finalize(args[0].value, args[0].args)

    if binop in {"sub", "xor", "eq", "ne"} and _conservative_eq(args[0], args[1]):
        if binop == "eq":
            # (x == x) == 1
            return finalize(1, [])
        else:
            # x - x == x ^ x == x != x == 0
            return finalize(0, [])

    # TODO associativity rules

    if binop in {"mul", "div", "sdiv", "mod", "smod", "and"} and _int(args[1]) == 0:
        return finalize(0, [])

    if binop in {"mod", "smod"} and _int(args[1]) == 1:
        return finalize(0, [])

    if binop in {"mul", "div", "sdiv"} and _int(args[1]) == 1:
        return finalize(args[0].value, args[0].args)

    # x * -1 == 0 - x
    if binop in {"mul", "sdiv"} and _int(args[1], SIGNED) == -1:
        return finalize("sub", [0, args[0]])

    if binop in {"and", "or", "xor"} and _int(args[1], SIGNED) == -1:
        assert unsigned == UNSIGNED
        if binop == "and":
            # -1 & x == x
            return finalize(args[0].value, args[0].args)

        if binop == "xor":
            # -1 ^ x == ~x
            return finalize("not", [args[0]])

        if binop == "or":
            # -1 | x == -1
            return finalize(args[1].value, [])

        raise CompilerPanic("unreachable")  # pragma: notest

    # -1 - x == ~x (definition of two's complement)
    if binop == "sub" and _int(args[0], SIGNED) == -1:
        return finalize("not", [args[1]])

    if binop == "exp":
        # n ** 0 == 1 (forall n)
        # 1 ** n == 1
        if _int(args[1]) == 0 or _int(args[0]) == 1:
            return finalize(1, [])
        # 0 ** n == (1 if n == 0 else 0)
        if _int(args[0]) == 0:
            return finalize("iszero", [args[1]])
        # n ** 1 == n
        if _int(args[1]) == 1:
            return finalize(args[0].value, args[0].args)

    # TODO: check me! reduce codesize for negative numbers
    # if binop in {"add", "sub"} and _int(args[0], SIGNED) < 0:
    #     flipped = "add" if binop == "sub" else "sub"
    #     return finalize(flipped, [args[0], -args[1]])

    # TODO maybe OK:
    # elif binop == "div" and _int(args[1], UNSIGNED) == MAX_UINT256:
    #    # (div x (2**256 - 1)) == (eq x (2**256 - 1))
    #    new_val = "eq"
    #    args = args

    if binop in {"mod", "div", "mul"} and _is_int(args[1]) and is_power_of_two(_int(args[1])):
        assert unsigned == UNSIGNED, "something's not right."
        # shave two gas off mod/div/mul for powers of two
        if binop == "mod":
            return finalize("and", [args[0], _int(args[1]) - 1])

        if binop == "div" and version_check(begin="constantinople"):
            # recall shr/shl have unintuitive arg order
            return finalize("shr", [int_log2(_int(args[1])), args[0]])

        # note: no rule for sdiv since it rounds differently from sar
        if binop == "mul" and version_check(begin="constantinople"):
            return finalize("shl", [int_log2(_int(args[1])), args[0]])

        raise CompilerPanic("unreachable")  # pragma: notest

    ##
    # COMPARISONS
    ##

    if binop == "ne":
        # trigger other optimizations
        return finalize("iszero", ["eq", args])

    if binop == "eq" and _int(args[1]) == 0:
        return finalize("iszero", [args[0]])

    if binop == "eq" and _int(args[1], SIGNED) == -1:
        # equal gas, but better codesize
        return finalize("iszero", [["not", args[0]]])

    # note: in places where truthy is accepted, sequences of
    # ISZERO ISZERO will be optimized out, so we try to rewrite
    # some operations to include iszero
    # (note ordering; truthy optimizations should come first
    # to avoid getting clobbered by other branches)
    if is_truthy:
        if binop == "eq":
            assert unsigned == UNSIGNED
            # (eq x y) has the same truthyness as (iszero (xor x y))
            # it also has the same truthyness as (iszero (sub x y)),
            # but xor is slightly easier to optimize because of being
            # commutative.
            # note that (xor (-1) x) has its own rule
            return finalize("iszero", [["xor", args[0], args[1]]])

        # no rule needed for "ne" as it will get compiled to
        # `(iszero (eq x y))` anyways.

        # TODO can we do this?
        # if val == "div":
        #     return finalize("gt", ["iszero", args])

        if binop == "or" and _is_int(args[1]) and _int(args[1]) != 0:
            # (x | y != 0) for any (y != 0)
            return finalize(1, [])

    if binop in COMPARISON_OPS:
        prefer_strict = not is_truthy
        res = _comparison_helper(binop, args, prefer_strict=prefer_strict)
        if res is None:
            return res
        new_op, new_args = res
        return finalize(new_op, new_args)

    # no optimization happened
    return None


def optimize(node: IRnode) -> IRnode:
    initial_symbols = node.unique_symbols()

    ret = _optimize(node, parent=None)

    if ret.unique_symbols() != initial_symbols:
        diff = initial_symbols - ret.unique_symbols()
        raise CompilerPanic(f"Bad optimizer pass, missing {diff}")

    return ret


def _optimize(node: IRnode, parent: Optional[IRnode]) -> IRnode:
    argz = [_optimize(arg, node) for arg in node.args]

    value = node.value
    typ = node.typ
    location = node.location
    source_pos = node.source_pos
    annotation = node.annotation
    add_gas_estimate = node.add_gas_estimate

    def finalize(ir_builder):
        return IRnode.from_list(
            ir_builder,
            typ=typ,
            location=location,
            source_pos=source_pos,
            annotation=annotation,
            add_gas_estimate=add_gas_estimate,
        )

    optimize_more = False

    if value == "seq":
        _merge_memzero(argz)
        _merge_calldataload(argz)
        optimize_more = _remove_empty_seqs(argz)

        # (seq x) => (x) for cleanliness and
        # to avoid blocking other optimizations
        if len(argz) == 1:
            return argz[0]

    elif value in arith:
        parent_op = parent.value if parent is not None else None

        res = _optimize_binop(value, argz, annotation, parent_op)
        if res is not None:
            optimize_more = True
            value, argz, annotation = res

    ###
    # BITWISE OPS
    ###
    # note, don't optimize these too much as these kinds of expressions
    # may be hand optimized for codesize. we can optimize bitwise ops
    # more, once we have a pipeline which optimizes for codesize.
    elif value in ("shl", "shr", "sar") and argz[0].value == 0:
        # x >> 0 == x << 0 == x
        optimize_more = True
        value = argz[1].value
        annotation = argz[1].annotation
        argz = argz[1].args

    # TODO just expand this
    elif node.value == "ceil32" and _is_int(argz[0]):
        t = argz[0]
        annotation = f"ceil32({t.value})"
        argz = []
        value = ceil32(t.value)

    elif value == "iszero" and _is_int(argz[0]):
        value = int(argz[0].value == 0)  # int(bool) == 1 if bool else 0
        argz = []

    elif node.value == "if":
        # optimize out the branch
        if _is_int(argz[0]):
            # if false
            if _evm_int(argz[0]) == 0:
                # return the else branch (or [] if there is no else)
                return _optimize(IRnode("seq", argz[2:]), parent)
            # if true
            else:
                # return the first branch
                return argz[1]

        elif len(argz) == 3 and argz[0].value != "iszero":
            # if(x) compiles to jumpi(_, iszero(x))
            # there is an asm optimization for the sequence ISZERO ISZERO..JUMPI
            # so we swap the branches here to activate that optimization.
            cond = argz[0]
            true_branch = argz[1]
            false_branch = argz[2]
            contra_cond = IRnode.from_list(["iszero", cond])

            argz = [contra_cond, false_branch, true_branch]
            # set optimize_more = True?

    elif node.value in ("assert", "assert_unreachable") and _is_int(argz[0]):
        if _evm_int(argz[0]) == 0:
            raise StaticAssertionException(
                f"assertion found to fail at compile time. (hint: did you mean `raise`?) {node}",
                source_pos,
            )
        else:
            value = "seq"
            argz = []

    # NOTE: this is really slow (compile-time).
    # ideal would be to optimize the tree in-place
    ret = finalize([value, *argz])

    if optimize_more:
        ret = _optimize(ret, parent=parent)

    return ret


def _merge_memzero(argz):
    # look for sequential mzero / calldatacopy operations that are zero'ing memory
    # and merge them into a single calldatacopy
    mstore_nodes: List = []
    initial_offset = 0
    total_length = 0
    for ir_node in argz:
        if (
            ir_node.value == "mstore"
            and isinstance(ir_node.args[0].value, int)
            and ir_node.args[1].value == 0
        ):
            # mstore of a zero value
            offset = ir_node.args[0].value
            if not mstore_nodes:
                initial_offset = offset
            if initial_offset + total_length == offset:
                mstore_nodes.append(ir_node)
                total_length += 32
                continue

        if (
            ir_node.value == "calldatacopy"
            and isinstance(ir_node.args[0].value, int)
            and ir_node.args[1].value == "calldatasize"
            and isinstance(ir_node.args[2].value, int)
        ):
            # calldatacopy from the end of calldata - efficient zero'ing via `empty()`
            offset, length = ir_node.args[0].value, ir_node.args[2].value
            if not mstore_nodes:
                initial_offset = offset
            if initial_offset + total_length == offset:
                mstore_nodes.append(ir_node)
                total_length += length
                continue

        # if we get this far, the current node is not a zero'ing operation
        # it's time to apply the optimization if possible
        if len(mstore_nodes) > 1:
            new_ir = IRnode.from_list(
                ["calldatacopy", initial_offset, "calldatasize", total_length],
                source_pos=mstore_nodes[0].source_pos,
            )
            # replace first zero'ing operation with optimized node and remove the rest
            idx = argz.index(mstore_nodes[0])
            argz[idx] = new_ir
            for i in mstore_nodes[1:]:
                argz.remove(i)

        initial_offset = 0
        total_length = 0
        mstore_nodes.clear()


# remove things like [seq, seq, seq] because they interfere with
# other optimizer steps
def _remove_empty_seqs(argz):
    changed = False
    i = 0
    while i < len(argz) - 1:
        if argz[i].value in ("seq", "pass") and len(argz[i].args) == 0:
            changed = True
            del argz[i]
        else:
            i += 1
    return changed


def _merge_calldataload(argz):
    # look for sequential operations copying from calldata to memory
    # and merge them into a single calldatacopy operation
    mstore_nodes: List = []
    initial_mem_offset = 0
    initial_calldata_offset = 0
    total_length = 0
    for ir_node in argz:
        if (
            ir_node.value == "mstore"
            and isinstance(ir_node.args[0].value, int)
            and ir_node.args[1].value == "calldataload"
            and isinstance(ir_node.args[1].args[0].value, int)
        ):
            # mstore of a zero value
            mem_offset = ir_node.args[0].value
            calldata_offset = ir_node.args[1].args[0].value
            if not mstore_nodes:
                initial_mem_offset = mem_offset
                initial_calldata_offset = calldata_offset
            if (
                initial_mem_offset + total_length == mem_offset
                and initial_calldata_offset + total_length == calldata_offset
            ):
                mstore_nodes.append(ir_node)
                total_length += 32
                continue

        # if we get this far, the current node is a different operation
        # it's time to apply the optimization if possible
        if len(mstore_nodes) > 1:
            new_ir = IRnode.from_list(
                ["calldatacopy", initial_mem_offset, initial_calldata_offset, total_length],
                source_pos=mstore_nodes[0].source_pos,
            )
            # replace first copy operation with optimized node and remove the rest
            idx = argz.index(mstore_nodes[0])
            argz[idx] = new_ir
            for i in mstore_nodes[1:]:
                argz.remove(i)

        initial_mem_offset = 0
        initial_calldata_offset = 0
        total_length = 0
        mstore_nodes.clear()
