import operator
from typing import List, Optional, Union

from vyper.codegen.ir_node import CLAMP_OP_NAMES, IRnode
from vyper.evm.opcodes import version_check
from vyper.exceptions import StaticAssertionException
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
        o = node.value
    else:
        return None

    if unsigned:
        return signed_to_unsigned(o, 256, strict=True)
    else:
        return unsigned_to_signed(o, 256, strict=True)


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
}

# quick typedefs, maybe move these to IRnode
IRVal = Union[str, int]
IRArgs = List[IRnode]


# def _optimize_binop(
#    binop: str, args: IRArgs, ann: Optional[str], parent_op: Any = None
# ) -> Tuple[IRVal, IRArgs, Optional[str]]:
def _optimize_binop(binop, args, ann, parent_op):

    fn, symb, unsigned = arith[binop]

    # local version of _evm_int which defaults to the current binop's signedness
    def _int(x, unsigned=unsigned):
        return _evm_int(x, unsigned=unsigned)

    l_ann = args[0].annotation or str(args[0])
    r_ann = args[1].annotation or str(args[1])
    new_ann = l_ann + symb + r_ann
    if ann is not None:
        new_ann = f"{ann} ({new_ann})"

    if _is_int(args[0]) and _is_int(args[1]):
        # compile-time arithmetic
        left, right = _int(args[0]), _int(args[1])
        new_val = fn(left, right)
        # wrap.
        new_val = new_val % 2**256
        # wrap signedly
        if not unsigned:
            new_val = unsigned_to_signed(new_val, strict=True)
        return new_val, [], new_ann

    new_val = None
    new_args = None

    # we can return truthy values instead of actual math
    is_truthy = parent_op in {"if", "assert", "iszero"}

    ##
    # ARITHMETIC
    ##

    # if the op is commutative, move the literal to the second position
    # to make the later logic cleaner
    if binop in {"add", "mul"} and _is_int(args[0]):
        args = [args[1], args[0]]

    if binop in {"add", "sub"} and _int(args[1]) == 0:
        new_val = args[0].value
        new_args = args[0].args

    elif binop in {"mul", "div", "sdiv", "mod", "smod"} and _int(args[1]) == 0:
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
            new_args = [args[0], int_log2(_int(args[1]))]
        if binop == "div" and version_check(begin="constantinople"):
            new_val = "shr"
            # recall shr/shl have unintuitive arg order
            new_args = [int_log2(_int(args[1])), args[0]]
        # note: no rule for sdiv since it rounds differently from sar
        if binop == "mul" and version_check(begin="constantinople"):
            new_val = "shl"
            new_args = [int_log2(_int(args[1])), args[0]]

    ##
    # COMPARISONS
    ##

    # (le x 0) seems like a linting issue actually
    elif binop in {"eq", "le"} and _int(args[1]) == 0:
        new_val = "iszero"
        new_args = [args[0]]

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


    # note: in places where truthy is accepted, sequences of
    # ISZERO ISZERO will be optimized out, so we try to rewrite
    # some operations to include iszero
    elif is_truthy:
        if binop == "eq":
            # x == 0xff...ff => ~x == 0
            if _int(args[1], UNSIGNED) == 2 ** 256 - 1:
                new_val = "iszero"
                new_args = [["not", args[0]]]
            else:
                # (eq x y) has the same truthyness as (iszero (xor x y))
                new_val = "iszero"
                new_args = [["xor", *args]]
        # no rule needed for "ne" as it will get compiled to
        # `(iszero (eq x y))` anyways.

        # TODO can we do this?
        # if val == "div":
        #    val = "gt"
        #    args = ["iszero", args]

        elif binop in ("sgt", "gt") and _is_int(args[1]):
            new_val = "sge" if binop == "sgt" else "ge"
            new_args = [args[0], _int(args[1]) + 1]

        elif binop in ("slt", "lt") and _is_int(args[1]):
            new_val = "sle" if binop == "slt" else "le"
            new_args = [args[0], _int(args[1]) - 1]

    ##
    # BITWISE OPS
    ##

    # x >> 0 == x << 0 == x
    elif binop in ("shl", "shr", "sar") and _int(args[0]) == 0:
        new_val = args[1].value
        new_ann = args[1].annotation
        new_args = args[1].args

    if new_val is None:
        return binop, args, ann

    return new_val, new_args, new_ann


def _optimize_clamps(clamp_op, args, parent):
    if clamp_op in ("clamp", "uclamp"):
        clample = clamp_op + "le"
        inner = [clample, args[0], args[1]]
        outer = [clample, inner, args[2]]
        to_optimize = IRnode.from_list(outer)

    else:
        # extract last two chars of the op, e.g. "clamplt" -> "lt"
        compare_op = clamp_op[-2:]

        unsigned = clamp_op.startswith("u")
        if not unsigned:
            # e.g., "lt" -> "slt"
            compare_op = "s" + compare_op

        with args[0].cache_when_complex("clamp_arg") as (b1, arg):
            to_optimize = ["seq", ["assert", [compare_op, arg, args[1]]], arg]
            to_optimize = b1.resolve(IRnode.from_list(to_optimize))

    return optimize(to_optimize, parent)


def optimize(node: IRnode, parent: Optional[IRnode] = None) -> IRnode:
    argz = [optimize(arg, node) for arg in node.args]

    value = node.value
    typ = node.typ
    location = node.location
    source_pos = node.source_pos
    annotation = node.annotation
    add_gas_estimate = node.add_gas_estimate
    valency = node.valency

    if value == "seq":
        _merge_memzero(argz)
        _merge_calldataload(argz)

    if value in arith:
        parent_op = parent.value if parent is not None else None
        value, argz, annotation = _optimize_binop(value, argz, annotation, parent_op)

    elif node.value in CLAMP_OP_NAMES:
        return _optimize_clamps(node.value, argz, parent)

    # TODO just expand this
    elif node.value == "ceil32" and _is_int(argz[0]):
        t = argz[0]
        annotation = f"ceil32({t.value})"
        argz = []
        value = ceil32(t.value)

    elif node.value == "if" and len(argz) == 3:
        # if(x) compiles to jumpi(_, iszero(x))
        # there is an asm optimization for the sequence ISZERO ISZERO..JUMPI
        # so we swap the branches here to activate that optimization.
        cond = argz[0]
        true_branch = argz[1]
        false_branch = argz[2]
        contra_cond = IRnode.from_list(["iszero", cond])

        argz = [contra_cond, false_branch, true_branch]

    elif node.value in ("assert", "assert_unreachable") and _is_int(argz[0]):
        if _evm_int(argz[0]) == 0:
            raise StaticAssertionException(
                f"assertion found to fail at compile time: {node}", source_pos
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
        valency=valency,
    )
    if node.total_gas is not None:
        ret.total_gas = node.total_gas - node.gas + ret.gas
        ret.func_name = node.func_name

    return ret


def _merge_memzero(argz):
    # look for sequential mzero / calldatacopy operations that are zero'ing memory
    # and merge them into a single calldatacopy
    mstore_nodes: List = []
    initial_offset = 0
    total_length = 0
    for ir_node in [i for i in argz if i.value != "pass"]:
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


def _merge_calldataload(argz):
    # look for sequential operations copying from calldata to memory
    # and merge them into a single calldatacopy operation
    mstore_nodes: List = []
    initial_mem_offset = 0
    initial_calldata_offset = 0
    total_length = 0
    for ir_node in [i for i in argz if i.value != "pass"]:
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
