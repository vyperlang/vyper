import operator
from typing import List, Optional, Union

from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, StaticAssertionException
from vyper.utils import (
    ceil32,
    evm_div,
    evm_mod,
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


arith = {
    "add": (operator.add, "+", UNSIGNED),
    "sub": (operator.sub, "-", UNSIGNED),
    "mul": (operator.mul, "*", UNSIGNED),
    "div": (evm_div, "/", UNSIGNED),
    "sdiv": (evm_div, "/", SIGNED),
    "mod": (evm_mod, "%", UNSIGNED),
    "smod": (evm_mod, "%", SIGNED),
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


# def _optimize_arith(
#    binop: str, args: IRArgs, ann: Optional[str], parent_op: Any = None
# ) -> Tuple[IRVal, IRArgs, Optional[str]]:
def _optimize_arith(binop, args, ann, parent_op):
    fn, symb, unsigned = arith[binop]

    # local version of _evm_int which defaults to the current binop's signedness
    def _int(x, unsigned=unsigned):
        return _evm_int(x, unsigned=unsigned)

    def _wrap(x, unsigned=unsigned):
        x %= 2 ** 256
        # wrap in a signed way.
        if not unsigned:
            x = unsigned_to_signed(x, 256, strict=True)
        return x

    new_ann = None
    if ann is not None:
        l_ann = args[0].annotation or str(args[0])
        r_ann = args[1].annotation or str(args[1])
        new_ann = l_ann + symb + r_ann
        new_ann = f"{ann} ({new_ann})"

    if _is_int(args[0]) and _is_int(args[1]):
        # compile-time arithmetic
        left, right = _int(args[0]), _int(args[1])
        new_val = fn(left, right)
        new_val = _wrap(new_val)
        return False, new_val, [], new_ann

    new_val = None
    new_args = None

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

    if binop in COMPARISON_OPS and _is_int(args[0]):
        binop = _flip_comparison_op(binop)
        args = [args[1], args[0]]

    if binop in {"add", "sub", "xor", "or"} and _int(args[1]) == 0:
        # x + 0 == x - 0 == x | 0 == x ^ 0 == x
        new_val = args[0].value
        new_args = args[0].args

    elif binop in {"sub", "xor"} and _conservative_eq(args[0], args[1]):
        # x - x == x ^ x == 0
        new_val = 0
        new_args = []

    # TODO associativity rules

    elif binop in {"mul", "div", "sdiv", "mod", "smod", "and"} and _int(args[1]) == 0:
        new_val = 0
        new_args = []

    elif binop in {"mod", "smod"} and _int(args[1]) == 1:
        new_val = 0
        new_args = []

    elif binop in {"mul", "div", "sdiv"} and _int(args[1]) == 1:
        new_val = args[0].value
        new_args = args[0].args

    # x * -1 == 0 - x
    elif binop in {"mul", "sdiv"} and _int(args[1], SIGNED) == -1:
        new_val = "sub"
        new_args = [0, args[0]]

    # maybe OK:
    # elif binop == "div" and _int(args[1], UNSIGNED) == MAX_UINT256:
    #    # (div x (2**256 - 1)) == (eq x (2**256 - 1))
    #    new_val = "eq"
    #    args = args

    elif binop in {"mod", "div", "mul"} and _is_int(args[1]) and is_power_of_two(_int(args[1])):
        assert unsigned == UNSIGNED, "something's not right."
        # shave two gas off mod/div/mul for powers of two
        if binop == "mod":
            new_val = "and"
            new_args = [args[0], _int(args[1]) - 1]
        if binop == "div" and version_check(begin="constantinople"):
            new_val = "shr"
            # recall shr/shl have unintuitive arg order
            new_args = [int_log2(_int(args[1])), args[0]]
        # note: no rule for sdiv since it rounds differently from sar
        if binop == "mul" and version_check(begin="constantinople"):
            new_val = "shl"
            new_args = [int_log2(_int(args[1])), args[0]]

    elif binop in {"and", "or", "xor"} and _int(args[1]) == 2 ** 256 - 1:
        if binop == "and":
            new_val = args[0].value
            new_args = args[0].args
        elif binop == "xor":
            new_val = "not"
            new_args = [args[0]]
        elif binop == "or":
            new_val = args[1].value
            new_args = []
        else:  # pragma: nocover
            raise CompilerPanic("unreachable")

    ##
    # COMPARISONS
    ##

    # note: in places where truthy is accepted, sequences of
    # ISZERO ISZERO will be optimized out, so we try to rewrite
    # some operations to include iszero
    # (note ordering; truthy optimizations should come first
    # to avoid getting clobbered by other branches)
    # TODO: rethink structure of is_truthy optimizations.
    elif is_truthy:
        if binop == "eq":
            # x == 0xff...ff => ~x == 0
            if _int(args[1], UNSIGNED) == 2 ** 256 - 1:
                new_val = "iszero"
                new_args = [["not", args[0]]]
            else:
                # (eq x y) has the same truthyness as (iszero (sub x y))
                new_val = "iszero"
                new_args = [["sub", *args]]
        # no rule needed for "ne" as it will get compiled to
        # `(iszero (eq x y))` anyways.

        # TODO can we do this?
        # if val == "div":
        #    val = "gt"
        #    args = ["iszero", args]

        elif binop in {"sgt", "gt", "slt", "lt"} and _is_int(args[1]):
            assert unsigned == (not binop.startswith("s")), "signed opcodes should start with s"
            op_is_gt = binop.endswith("gt")
            rhs = _int(args[1])

            # x > 1 => x >= 2
            # x < 1 => x <= 0
            new_rhs = rhs + 1 if op_is_gt else rhs - 1

            if _wrap(new_rhs) != new_rhs:
                # always false. ex. (gt x MAX_UINT256)
                # note that the wrapped version (ge x 0) is always true.
                new_val = 0
                new_args = []

            else:
                # e.g. "sgt" => "sge"
                new_val = binop.replace("t", "e")
                new_args = [args[0], new_rhs]

        elif binop == "or" and _is_int(args[1]):
            # (x | y != 0) for any (y != 0)
            if _int(args[1]) != 0:
                new_val = 1
                new_args = []

    # (le x 0) seems like a linting issue actually
    elif binop in {"eq", "le"} and _int(args[1]) == 0:
        new_val = "iszero"
        new_args = [args[0]]

    # TODO: these comparisons are incomplete, e.g. slt x MIN_INT256.
    # figure out if we can combine with the logic in is_truthy to be
    # more generic
    elif binop == "ge" and _int(args[1]) == 0:
        new_val = 1
        new_args = []

    elif binop == "lt":
        if _int(args[1]) == 0:
            new_val = 0
            new_args = []
        if _int(args[1]) == 1:
            new_val = "iszero"
            new_args = [args[0]]

    # gt x 0 => x != 0
    elif binop == "gt" and _int(args[1]) == 0:
        new_val = "iszero"
        new_args = [["iszero", args[0]]]

    if new_val is None:
        return False, binop, args, ann

    return True, new_val, new_args, new_ann


def optimize(node: IRnode, parent: Optional[IRnode] = None) -> IRnode:
    argz = [optimize(arg, node) for arg in node.args]

    value = node.value
    typ = node.typ
    location = node.location
    source_pos = node.source_pos
    annotation = node.annotation
    add_gas_estimate = node.add_gas_estimate

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
        optimize_more, value, argz, annotation = _optimize_arith(value, argz, annotation, parent_op)

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
                return optimize(IRnode("seq", argz[2:]), parent)
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
    # maybe should optimize the tree in-place
    ret = IRnode.from_list(
        [value, *argz],
        typ=typ,
        location=location,
        source_pos=source_pos,
        annotation=annotation,
        add_gas_estimate=add_gas_estimate,
    )

    if optimize_more:
        ret = optimize(ret, parent=parent)
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
