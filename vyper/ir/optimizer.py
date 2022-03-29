import operator
from typing import List, Optional

from vyper.codegen.ir_node import IRnode
from vyper.utils import ceil32, evm_div, evm_mod


def get_int_at(args: List[IRnode], pos: int, signed: bool = False) -> Optional[int]:
    value = args[pos].value

    if isinstance(value, int):
        o = value
    else:
        return None

    if signed or o < 0:
        return ((o + 2 ** 255) % 2 ** 256) - 2 ** 255
    else:
        return o % 2 ** 256


def int_at(args: List[IRnode], pos: int, signed: bool = False) -> Optional[int]:
    return get_int_at(args, pos, signed) is not None


arith = {
    "add": (operator.add, "+"),
    "sub": (operator.sub, "-"),
    "mul": (operator.mul, "*"),
    "div": (evm_div, "/"),
    "mod": (evm_mod, "%"),
}


def _is_constant_add(node: IRnode, args: List[IRnode]) -> bool:
    return bool(
        (isinstance(node.value, str))
        and (node.value == "add" and int_at(args, 0))
        and (args[1].value == "add" and int_at(args[1].args, 0))
    )


def optimize(node: IRnode) -> IRnode:
    # TODO add rules for modulus powers of 2
    # TODO refactor this into several functions

    argz = [optimize(arg) for arg in node.args]

    value = node.value
    typ = node.typ
    location = node.location
    source_pos = node.source_pos
    annotation = node.annotation
    add_gas_estimate = node.add_gas_estimate
    valency = node.valency

    if node.value == "seq":
        _merge_memzero(argz)
        _merge_calldataload(argz)

    if node.value in arith and int_at(argz, 0) and int_at(argz, 1):
        # compile-time arithmetic
        left, right = get_int_at(argz, 0), get_int_at(argz, 1)
        # `node.value in arith` implies that `node.value` is a `str`
        fn, symb = arith[str(node.value)]
        value = fn(left, right)
        if argz[0].annotation and argz[1].annotation:
            annotation = argz[0].annotation + symb + argz[1].annotation
        elif argz[0].annotation or argz[1].annotation:
            annotation = (
                (argz[0].annotation or str(left)) + symb + (argz[1].annotation or str(right))
            )
        else:
            annotation = ""

        argz = []

    elif node.value == "ceil32" and int_at(argz, 0):
        t = argz[0]
        annotation = f"ceil32({t.value})"
        argz = []
        value = ceil32(t.value)

    # x >> 0 == x << 0 == x
    elif node.value in ("shl", "shr", "sar") and get_int_at(argz, 0) == 0:
        value = argz[1].value
        annotation = argz[1].annotation
        argz = argz[1].args

    elif (node.value == "add" and get_int_at(argz, 0) == 0) or (
        node.value == "mul" and get_int_at(argz, 0) == 1
    ):
        value = argz[1].value
        annotation = argz[1].annotation
        argz = argz[1].args

    elif (node.value == "add" and get_int_at(argz, 1) == 0) or (
        node.value == "mul" and get_int_at(argz, 1) == 1
    ):
        value = argz[0].value
        annotation = argz[0].annotation
        argz = argz[0].args

    elif (
        node.value in ("clamp", "uclamp")
        and int_at(argz, 0)
        and int_at(argz, 1)
        and int_at(argz, 2)
    ):
        if get_int_at(argz, 0, True) > get_int_at(argz, 1, True):  # type: ignore
            raise Exception("Clamp always fails")
        elif get_int_at(argz, 1, True) > get_int_at(argz, 2, True):  # type: ignore
            raise Exception("Clamp always fails")
        else:
            return argz[1]

    elif node.value in ("clamp", "uclamp") and int_at(argz, 0) and int_at(argz, 1):
        if get_int_at(argz, 0, True) > get_int_at(argz, 1, True):  # type: ignore
            raise Exception("Clamp always fails")
        else:
            # i.e., clample or uclample
            value += "le"  # type: ignore
            argz = [argz[1], argz[2]]

    elif node.value == "uclamplt" and int_at(argz, 0) and int_at(argz, 1):
        if get_int_at(argz, 0, True) >= get_int_at(argz, 1, True):  # type: ignore
            raise Exception("Clamp always fails")
        value = argz[0].value
        argz = []

    elif node.value == "clamp_nonzero" and int_at(argz, 0):
        if get_int_at(argz, 0) != 0:
            value = argz[0].value
            argz = []
        else:
            raise Exception("Clamp always fails")

    # TODO: (uclampgt 0 x) -> (iszero (iszero x))
    # TODO: more clamp rules

    # [eq, x, 0] is the same as [iszero, x].
    # TODO handle (ne 0 x) as well
    elif node.value == "eq" and int_at(argz, 1) and argz[1].value == 0:
        value = "iszero"
        argz = [argz[0]]

    # TODO handle (ne -1 x) as well
    elif node.value == "eq" and int_at(argz, 1) and argz[1].value == -1:
        value = "iszero"
        argz = [IRnode.from_list(["not", argz[0]])]

    elif node.value == "iszero" and int_at(argz, 0):
        value = 1 if get_int_at(argz, 0) == 0 else 0
        annotation = f"iszero({annotation})"
        argz = []

    # (eq x y) has the same truthyness as (iszero (xor x y))
    # rewrite 'eq' as 'xor' in places where truthy is accepted.
    # (the sequence (if (iszero (xor x y))) will be translated to
    #  XOR ISZERO ISZERO ..JUMPI and the ISZERO ISZERO will be
    #  optimized out)
    elif node.value in ("if", "assert") and argz[0].value == "eq":
        argz[0] = ["iszero", ["xor", *argz[0].args]]  # type: ignore

    elif node.value == "if" and len(argz) == 3:
        # if(x) compiles to jumpi(_, iszero(x))
        # there is an asm optimization for the sequence ISZERO ISZERO..JUMPI
        # so we swap the branches here to activate that optimization.
        cond = argz[0]
        true_branch = argz[1]
        false_branch = argz[2]
        contra_cond = IRnode.from_list(["iszero", cond])

        argz = [contra_cond, false_branch, true_branch]

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


def _find_mload_offsets(ir_node: IRnode, expected_offsets: set, seen_offsets: set) -> set:
    for node in ir_node.args:
        if node.value == "mload" and node.args[0].value in expected_offsets:
            location = next(i for i in expected_offsets if i == node.args[0].value)
            seen_offsets.add(location)
        else:
            seen_offsets.update(_find_mload_offsets(node, expected_offsets, seen_offsets))

    return seen_offsets


def _remove_mstore(ir_node: IRnode, offsets: set) -> None:
    for node in ir_node.args.copy():
        if node.value == "mstore" and node.args[0].value in offsets:
            ir_node.args.remove(node)
        else:
            _remove_mstore(node, offsets)
