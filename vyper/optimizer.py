import operator
from typing import Any, List, Optional

from vyper.parser.parser_utils import LLLnode
from vyper.utils import LOADED_LIMITS


def get_int_at(args: List[LLLnode], pos: int, signed: bool = False) -> Optional[int]:
    value = args[pos].value

    if isinstance(value, int):
        o = value
    elif (
        value == "mload"
        and args[pos].args[0].value in LOADED_LIMITS.keys()
        and isinstance(args[pos].args[0].value, int)
    ):
        idx = int(args[pos].args[0].value)  # isinstance in if confirms type is int.
        o = LOADED_LIMITS[idx]
    else:
        return None

    if signed or o < 0:
        return ((o + 2 ** 255) % 2 ** 256) - 2 ** 255
    else:
        return o % 2 ** 256


def int_at(args: List[LLLnode], pos: int, signed: bool = False) -> Optional[int]:
    return get_int_at(args, pos, signed) is not None


arith = {
    "add": (operator.add, "+"),
    "sub": (operator.sub, "-"),
    "mul": (operator.mul, "*"),
    "div": (operator.floordiv, "/"),
    "mod": (operator.mod, "%"),
}


def _is_constant_add(node: LLLnode, args: List[LLLnode]) -> bool:
    return bool(
        (isinstance(node.value, str))
        and (node.value == "add" and int_at(args, 0))
        and (args[1].value == "add" and int_at(args[1].args, 0))
    )


def has_cond_arg(node):
    return node.value in ["if", "if_unchecked", "assert", "assert_reason"]


def optimize(lll_node: LLLnode) -> LLLnode:
    lll_node = apply_general_optimizations(lll_node)
    lll_node = filter_unused_sizelimits(lll_node)

    return lll_node


def apply_general_optimizations(node: LLLnode) -> LLLnode:
    # TODO refactor this into several functions
    argz = [apply_general_optimizations(arg) for arg in node.args]

    if node.value == "seq":
        # look for sequential mzero / calldatacopy operations that are zero'ing memory
        # and merge them into a single calldatacopy
        mzero_nodes: List = []
        initial_offset = 0
        total_length = 0
        for lll_node in [i for i in argz if i.value != "pass"]:
            if (
                lll_node.value == "mstore"
                and isinstance(lll_node.args[0].value, int)
                and lll_node.args[1].value == 0
            ):
                # mstore of a zero value
                offset = lll_node.args[0].value
                if not mzero_nodes:
                    initial_offset = offset
                if initial_offset + total_length == offset:
                    mzero_nodes.append(lll_node)
                    total_length += 32
                    continue

            if (
                lll_node.value == "calldatacopy"
                and isinstance(lll_node.args[0].value, int)
                and lll_node.args[1].value == "calldatasize"
                and isinstance(lll_node.args[2].value, int)
            ):
                # calldatacopy from the end of calldata - efficient zero'ing via `empty()`
                offset, length = lll_node.args[0].value, lll_node.args[2].value
                if not mzero_nodes:
                    initial_offset = offset
                if initial_offset + total_length == offset:
                    mzero_nodes.append(lll_node)
                    total_length += length
                    continue

            # if we get this far, the current node is not a zero'ing operation
            # it's time to apply the optimization if possible
            if len(mzero_nodes) > 1:
                new_lll = LLLnode.from_list(
                    ["calldatacopy", initial_offset, "calldatasize", total_length],
                    pos=mzero_nodes[0].pos,
                )
                # replace first zero'ing operation with optimized node and remove the rest
                idx = argz.index(mzero_nodes[0])
                argz[idx] = new_lll
                for i in mzero_nodes[1:]:
                    argz.remove(i)

            initial_offset = 0
            total_length = 0
            mzero_nodes.clear()

    if node.value in arith and int_at(argz, 0) and int_at(argz, 1):
        left, right = get_int_at(argz, 0), get_int_at(argz, 1)
        # `node.value in arith` implies that `node.value` is a `str`
        calcer, symb = arith[str(node.value)]
        new_value = calcer(left, right)
        if argz[0].annotation and argz[1].annotation:
            annotation = argz[0].annotation + symb + argz[1].annotation
        elif argz[0].annotation or argz[1].annotation:
            annotation = (
                (argz[0].annotation or str(left)) + symb + (argz[1].annotation or str(right))
            )
        else:
            annotation = ""
        return LLLnode(
            new_value,
            [],
            node.typ,
            None,
            node.pos,
            annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
    elif _is_constant_add(node, argz):
        # `node.value in arith` implies that `node.value` is a `str`
        calcer, symb = arith[str(node.value)]
        if argz[0].annotation and argz[1].args[0].annotation:
            annotation = argz[0].annotation + symb + argz[1].args[0].annotation
        elif argz[0].annotation or argz[1].args[0].annotation:
            annotation = (
                (argz[0].annotation or str(argz[0].value))
                + symb
                + (argz[1].args[0].annotation or str(argz[1].args[0].value))
            )
        else:
            annotation = ""
        return LLLnode(
            "add",
            [
                LLLnode(int(argz[0].value) + int(argz[1].args[0].value), annotation=annotation),
                argz[1].args[1],
            ],
            node.typ,
            None,
            annotation=node.annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
    elif node.value == "add" and get_int_at(argz, 0) == 0:
        return LLLnode(
            argz[1].value,
            argz[1].args,
            node.typ,
            node.location,
            node.pos,
            annotation=argz[1].annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
    elif node.value == "add" and get_int_at(argz, 1) == 0:
        return LLLnode(
            argz[0].value,
            argz[0].args,
            node.typ,
            node.location,
            node.pos,
            argz[0].annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
    elif node.value == "clamp" and int_at(argz, 0) and int_at(argz, 1) and int_at(argz, 2):
        if get_int_at(argz, 0, True) > get_int_at(argz, 1, True):  # type: ignore
            raise Exception("Clamp always fails")
        elif get_int_at(argz, 1, True) > get_int_at(argz, 2, True):  # type: ignore
            raise Exception("Clamp always fails")
        else:
            return argz[1]
    elif node.value == "clamp" and int_at(argz, 0) and int_at(argz, 1):
        if get_int_at(argz, 0, True) > get_int_at(argz, 1, True):  # type: ignore
            raise Exception("Clamp always fails")
        else:
            return LLLnode(
                "clample",
                [argz[1], argz[2]],
                node.typ,
                node.location,
                node.pos,
                node.annotation,
                add_gas_estimate=node.add_gas_estimate,
                valency=node.valency,
            )
    elif node.value == "clamp_nonzero" and int_at(argz, 0):
        if get_int_at(argz, 0) != 0:
            return LLLnode(
                argz[0].value,
                [],
                node.typ,
                node.location,
                node.pos,
                node.annotation,
                add_gas_estimate=node.add_gas_estimate,
                valency=node.valency,
            )
        else:
            raise Exception("Clamp always fails")
    # [eq, x, 0] is the same as [iszero, x].
    elif node.value == "eq" and int_at(argz, 1) and argz[1].value == 0:
        return LLLnode(
            "iszero",
            [argz[0]],
            node.typ,
            node.location,
            node.pos,
            node.annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
    # [ne, x, y] has the same truthyness as [xor, x, y]
    # rewrite 'ne' as 'xor' in places where truthy is accepted.
    elif has_cond_arg(node) and argz[0].value == "ne":
        argz[0] = LLLnode.from_list(["xor"] + argz[0].args)  # type: ignore
        return LLLnode.from_list(
            [node.value] + argz,  # type: ignore
            typ=node.typ,
            location=node.location,
            pos=node.pos,
            annotation=node.annotation,
            # let from_list handle valency and gas_estimate
        )
    elif node.value == "seq":
        xs: List[Any] = []
        for arg in argz:
            if arg.value == "seq":
                xs.extend(arg.args)
            else:
                xs.append(arg)
        return LLLnode(
            node.value,
            xs,
            node.typ,
            node.location,
            node.pos,
            node.annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
    elif node.total_gas is not None:
        o = LLLnode(
            node.value,
            argz,
            node.typ,
            node.location,
            node.pos,
            node.annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )
        o.total_gas = node.total_gas - node.gas + o.gas
        o.func_name = node.func_name
        return o
    else:
        return LLLnode(
            node.value,
            argz,
            node.typ,
            node.location,
            node.pos,
            node.annotation,
            add_gas_estimate=node.add_gas_estimate,
            valency=node.valency,
        )


def filter_unused_sizelimits(lll_node: LLLnode) -> LLLnode:
    # recursively search the LLL for mloads of the size limits, and then remove
    # the initial mstore operations for size limits that are never referenced
    expected_offsets = set(LOADED_LIMITS)
    seen_offsets = _find_mload_offsets(lll_node, expected_offsets, set())
    if expected_offsets == seen_offsets:
        return lll_node

    unseen_offsets = expected_offsets.difference(seen_offsets)
    _remove_mstore(lll_node, unseen_offsets)

    return lll_node


def _find_mload_offsets(lll_node: LLLnode, expected_offsets: set, seen_offsets: set) -> set:
    for node in lll_node.args:
        if node.value == "mload" and node.args[0].value in expected_offsets:
            location = next(i for i in expected_offsets if i == node.args[0].value)
            seen_offsets.add(location)
        else:
            seen_offsets.update(_find_mload_offsets(node, expected_offsets, seen_offsets))

    return seen_offsets


def _remove_mstore(lll_node: LLLnode, offsets: set) -> None:
    for node in lll_node.args.copy():
        if node.value == "mstore" and node.args[0].value in offsets:
            lll_node.args.remove(node)
        else:
            _remove_mstore(node, offsets)
