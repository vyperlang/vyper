import operator
from typing import List, Optional, Tuple, Union

from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, StaticAssertionException
from vyper.utils import (
    ceil32,
    evm_div,
    evm_mod,
    evm_pow,
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
    elif not unsigned and ret > 2**255 - 1:
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
    "exp": (evm_pow, "**", UNSIGNED),
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
STRICT_COMPARISON_OPS = {t for t in COMPARISON_OPS if t.endswith("t")}
UNSTRICT_COMPARISON_OPS = {t for t in COMPARISON_OPS if t.endswith("e")}

assert not (STRICT_COMPARISON_OPS & UNSTRICT_COMPARISON_OPS)
assert STRICT_COMPARISON_OPS | UNSTRICT_COMPARISON_OPS == COMPARISON_OPS


def _flip_comparison_op(opname):
    assert opname in COMPARISON_OPS
    if "g" in opname:
        return opname.replace("g", "l")
    if "l" in opname:
        return opname.replace("l", "g")
    raise CompilerPanic(f"bad comparison op {opname}")  # pragma: nocover


# some annotations are really long. shorten them (except maybe in "verbose" mode?)
def _shorten_annotation(annotation):
    if len(annotation) > 16:
        return annotation[:16] + "..."
    return annotation


def _wrap256(x, unsigned=UNSIGNED):
    x %= 2**256
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

    # for comparison operators, we have three special boundary cases:
    # almost always, never and almost never.
    # almost_always is always true for the non-strict ("ge" and co)
    # comparators. for strict comparators ("gt" and co), almost_always
    # is true except for one case. never is never true for the strict
    # comparators. never is almost always false for the non-strict
    # comparators, except for one case. and almost_never is almost
    # never true (except one case) for the strict comparators.
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

    if is_strict and _int(args[1]) == almost_never:
        # (lt x 1), (gt x (MAX_UINT256 - 1)), (slt x (MIN_INT256 + 1))
        return ("eq", [args[0], never])

    # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
    if is_strict != prefer_strict and _is_int(args[1]):
        rhs = _int(args[1])

        if prefer_strict and rhs == never:
            # e.g. ge x MAX_UINT256, sle x MIN_INT256
            return ("eq", args)

        if not prefer_strict and rhs == almost_always:
            # e.g. gt x 0, slt x MAX_INT256
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
        # if the original had side effects which might not be in the
        # optimized output, roll back the optimization
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
        # wrap the result, since `fn` generally does not wrap.
        # (note: do not rely on wrapping/non-wrapping behavior for `fn`!
        # some ops, like evm_pow, ALWAYS wrap).
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
    # ARITHMETIC AND BITWISE OPS
    ##

    # for commutative ops, move the literal to the second
    # position to make the later logic cleaner
    if binop in COMMUTATIVE_OPS and _is_int(args[0]):
        args = [args[1], args[0]]

    if binop in {"add", "sub", "xor", "or"} and _int(args[1]) == 0:
        # x + 0 == x - 0 == x | 0 == x ^ 0 == x
        return finalize("seq", [args[0]])

    if binop in {"sub", "xor", "ne"} and _conservative_eq(args[0], args[1]):
        # (x - x) == (x ^ x) == (x != x) == 0
        return finalize(0, [])

    if binop in STRICT_COMPARISON_OPS and _conservative_eq(args[0], args[1]):
        # (x < x) == (x > x) == 0
        return finalize(0, [])

    if binop in {"eq"} | UNSTRICT_COMPARISON_OPS and _conservative_eq(args[0], args[1]):
        # (x == x) == (x >= x) == (x <= x) == 1
        return finalize(1, [])

    # TODO associativity rules

    # x * 0 == x / 0 == x % 0 == x & 0 == 0
    if binop in {"mul", "div", "sdiv", "mod", "smod", "and"} and _int(args[1]) == 0:
        return finalize(0, [])

    # x % 1 == 0
    if binop in {"mod", "smod"} and _int(args[1]) == 1:
        return finalize(0, [])

    # x * 1 == x / 1 == x
    if binop in {"mul", "div", "sdiv"} and _int(args[1]) == 1:
        return finalize("seq", [args[0]])

    # x * -1 == 0 - x
    if binop in {"mul", "sdiv"} and _int(args[1], SIGNED) == -1:
        return finalize("sub", [0, args[0]])

    if binop in {"and", "or", "xor"} and _int(args[1], SIGNED) == -1:
        assert unsigned == UNSIGNED
        if binop == "and":
            # -1 & x == x
            return finalize("seq", [args[0]])

        if binop == "xor":
            # -1 ^ x == ~x
            return finalize("not", [args[0]])

        if binop == "or":
            # -1 | x == -1
            return finalize(args[1].value, [])

        raise CompilerPanic("unreachable")  # pragma: nocover

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
            return finalize("seq", [args[0]])

    # TODO: check me! reduce codesize for negative numbers
    # if binop in {"add", "sub"} and _int(args[1], SIGNED) < 0:
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
        # x % 2**n == x & (2**n - 1)
        if binop == "mod":
            return finalize("and", [args[0], _int(args[1]) - 1])

        if binop == "div":
            # x / 2**n == x >> n
            # recall shr/shl have unintuitive arg order
            return finalize("shr", [int_log2(_int(args[1])), args[0]])

        # note: no rule for sdiv since it rounds differently from sar
        if binop == "mul":
            # x * 2**n == x << n
            return finalize("shl", [int_log2(_int(args[1])), args[0]])

        raise CompilerPanic("unreachable")  # pragma: no cover

    ##
    # COMPARISONS
    ##

    if binop == "eq" and _int(args[1]) == 0:
        return finalize("iszero", [args[0]])

    # can't improve gas but can improve codesize
    if binop == "ne" and _int(args[1]) == 0:
        return finalize("iszero", [["iszero", args[0]]])

    if binop == "eq" and _int(args[1], SIGNED) == -1:
        # equal gas, but better codesize
        # x == MAX_UINT256 => ~x == 0
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

        if binop == "ne" and parent_op == "iszero":
            # for iszero, trigger other optimizations
            # (for `if` and `assert`, `ne` will generate two ISZEROs
            # which will get optimized out during assembly)
            return finalize("iszero", [["eq", *args]])

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


def _check_symbols(symbols, ir_node):
    # sanity check that no `unique_symbol`s got optimized out.
    to_check = ir_node.unique_symbols
    if symbols != to_check:
        raise CompilerPanic(f"missing symbols: {symbols - to_check}")


def optimize(node: IRnode) -> IRnode:
    _, ret = _optimize(node, parent=None)
    return ret


def _optimize(node: IRnode, parent: Optional[IRnode]) -> Tuple[bool, IRnode]:
    starting_symbols = node.unique_symbols

    res = [_optimize(arg, node) for arg in node.args]
    argz: list
    if len(res) == 0:
        args_changed, argz = False, []
    else:
        changed_flags, argz = zip(*res)  # type: ignore
        args_changed = any(changed_flags)
        argz = list(argz)

    value = node.value
    typ = node.typ
    location = node.location
    ast_source = node.ast_source
    error_msg = node.error_msg
    annotation = node.annotation
    add_gas_estimate = node.add_gas_estimate
    is_self_call = node.is_self_call
    passthrough_metadata = node.passthrough_metadata

    changed = False

    # in general, we cannot enforce the symbols check. for instance,
    # the dead branch eliminator will almost always trip the symbols check.
    # but for certain operations, particularly binops, we want to do the check.
    should_check_symbols = False

    def finalize(val, args):
        if not changed and not args_changed:
            # skip IRnode.from_list, which may be (compile-time) expensive
            return False, node

        ir_builder = [val, *args]
        ret = IRnode.from_list(
            ir_builder,
            typ=typ,
            location=location,
            ast_source=ast_source,
            error_msg=error_msg,
            annotation=annotation,
            add_gas_estimate=add_gas_estimate,
            is_self_call=is_self_call,
            passthrough_metadata=passthrough_metadata,
        )

        if should_check_symbols:
            _check_symbols(starting_symbols, ret)

        _, ret = _optimize(ret, parent)
        return True, ret

    if value == "seq":
        changed |= _merge_memzero(argz)
        changed |= _merge_calldataload(argz)
        changed |= _merge_dload(argz)
        changed |= _rewrite_mstore_dload(argz)
        changed |= _merge_mload(argz)
        changed |= _remove_empty_seqs(argz)

        # (seq x) => (x) for cleanliness and
        # to avoid blocking other optimizations
        if len(argz) == 1:
            return True, _optimize(argz[0], parent)[1]

        return finalize(value, argz)

    if value in arith:
        parent_op = parent.value if parent is not None else None

        res = _optimize_binop(value, argz, annotation, parent_op)
        if res is not None:
            changed = True
            should_check_symbols = True
            value, argz, annotation = res  # type: ignore
            return finalize(value, argz)

    ###
    # BITWISE OPS
    ###

    # note, don't optimize these too much as these kinds of expressions
    # may be hand optimized for codesize. we can optimize bitwise ops
    # more, once we have a pipeline which optimizes for codesize.
    if value in ("shl", "shr", "sar") and argz[0].value == 0:
        # x >> 0 == x << 0 == x
        changed = True
        annotation = argz[1].annotation
        return finalize(argz[1].value, argz[1].args)

    if node.value == "ceil32" and _is_int(argz[0]):
        changed = True
        annotation = f"ceil32({argz[0].value})"
        return finalize(ceil32(argz[0].value), [])

    if value == "iszero" and _is_int(argz[0]):
        changed = True
        val = int(argz[0].value == 0)  # int(bool) == 1 if bool else 0
        return finalize(val, [])

    if node.value == "if":
        # optimize out the branch
        if _is_int(argz[0]):
            changed = True
            # if false
            if _evm_int(argz[0]) == 0:
                # return the else branch (or [] if there is no else)
                return finalize("seq", argz[2:])
            # if true
            else:
                # return the first branch
                return finalize("seq", [argz[1]])

        elif len(argz) == 3 and argz[0].value not in ("iszero", "ne"):
            # if(x) compiles to jumpi(_, iszero(x))
            # there is an asm optimization for the sequence ISZERO ISZERO..JUMPI
            # so we swap the branches here to activate that optimization.
            cond = argz[0]
            true_branch = argz[1]
            false_branch = argz[2]
            contra_cond = IRnode.from_list(["iszero", cond])

            argz = [contra_cond, false_branch, true_branch]
            changed = True
            return finalize("if", argz)

    if value in ("assert", "assert_unreachable") and _is_int(argz[0]):
        if _evm_int(argz[0]) == 0:
            raise StaticAssertionException(
                f"assertion found to fail at compile time. (hint: did you mean `raise`?) {node}",
                ast_source,
            )
        else:
            changed = True
            return finalize("seq", [])

    return finalize(value, argz)


def _merge_memzero(argz):
    # look for sequential mzero / calldatacopy operations that are zero'ing memory
    # and merge them into a single calldatacopy
    mstore_nodes: List = []
    initial_offset = 0
    total_length = 0
    changed = False
    idx = None
    for i, ir_node in enumerate(argz):
        is_last_iteration = i == len(argz) - 1

        if (
            ir_node.value == "mstore"
            and isinstance(ir_node.args[0].value, int)
            and ir_node.args[1].value == 0
        ):
            # mstore of a zero value
            offset = ir_node.args[0].value
            if not mstore_nodes:
                idx = i
                initial_offset = offset
            if initial_offset + total_length == offset:
                mstore_nodes.append(ir_node)
                total_length += 32
                # do not block the optimization if it continues thru
                # the end of the (seq) block
                if not is_last_iteration:
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
                idx = i
                initial_offset = offset
            if initial_offset + total_length == offset:
                mstore_nodes.append(ir_node)
                total_length += length
                # do not block the optimization if it continues thru
                # the end of the (seq) block
                if not is_last_iteration:
                    continue

        # if we get this far, the current node is not a zero'ing operation
        # it's time to apply the optimization if possible
        if len(mstore_nodes) > 1:
            changed = True
            new_ir = IRnode.from_list(
                ["calldatacopy", initial_offset, "calldatasize", total_length],
                ast_source=mstore_nodes[0].ast_source,
            )
            # replace first zero'ing operation with optimized node and remove the rest
            argz[idx] = new_ir
            # note: del xs[k:l] deletes l - k items
            del argz[idx + 1 : idx + len(mstore_nodes)]

        initial_offset = 0
        total_length = 0
        mstore_nodes.clear()

    return changed


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
    return _merge_load(argz, "calldataload", "calldatacopy")


def _merge_dload(argz):
    return _merge_load(argz, "dload", "dloadbytes")


def _rewrite_mstore_dload(argz):
    changed = False
    for i, arg in enumerate(argz):
        if arg.value == "mstore" and arg.args[1].value == "dload":
            dst = arg.args[0]
            src = arg.args[1].args[0]
            len_ = 32
            argz[i] = IRnode.from_list(["dloadbytes", dst, src, len_], ast_source=arg.ast_source)
            changed = True
    return changed


def _merge_mload(argz):
    if not version_check(begin="cancun"):
        return False
    return _merge_load(argz, "mload", "mcopy", allow_overlap=False)


def _merge_load(argz, _LOAD, _COPY, allow_overlap=True):
    # look for sequential operations copying from X to Y
    # and merge them into a single copy operation
    changed = False
    mstore_nodes: List = []
    initial_dst_offset = 0
    initial_src_offset = 0
    total_length = 0
    idx = None
    for i, ir_node in enumerate(argz):
        is_last_iteration = i == len(argz) - 1
        if (
            ir_node.value == "mstore"
            and isinstance(ir_node.args[0].value, int)
            and ir_node.args[1].value == _LOAD
            and isinstance(ir_node.args[1].args[0].value, int)
        ):
            # mstore of a zero value
            dst_offset = ir_node.args[0].value
            src_offset = ir_node.args[1].args[0].value
            if not mstore_nodes:
                initial_dst_offset = dst_offset
                initial_src_offset = src_offset
                idx = i

            # dst and src overlap, discontinue the optimization
            has_overlap = initial_src_offset < initial_dst_offset < src_offset + 32

            if (
                initial_dst_offset + total_length == dst_offset
                and initial_src_offset + total_length == src_offset
                and (allow_overlap or not has_overlap)
            ):
                mstore_nodes.append(ir_node)
                total_length += 32

                # do not block the optimization if it continues thru
                # the end of the (seq) block
                if not is_last_iteration:
                    continue

        # if we get this far, the current node is a different operation
        # it's time to apply the optimization if possible
        if len(mstore_nodes) > 1:
            changed = True
            new_ir = IRnode.from_list(
                [_COPY, initial_dst_offset, initial_src_offset, total_length],
                ast_source=mstore_nodes[0].ast_source,
            )
            # replace first copy operation with optimized node and remove the rest
            argz[idx] = new_ir
            # note: del xs[k:l] deletes l - k items
            del argz[idx + 1 : idx + len(mstore_nodes)]

        initial_dst_offset = 0
        initial_src_offset = 0
        total_length = 0
        mstore_nodes.clear()

    return changed
