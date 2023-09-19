import contextlib
import re
from enum import Enum, auto
from functools import cached_property
from typing import Any, List, Optional, Tuple, Union

from vyper.compiler.settings import VYPER_COLOR_OUTPUT
from vyper.evm.address_space import AddrSpace
from vyper.evm.opcodes import get_ir_opcodes
from vyper.exceptions import CodegenPanic, CompilerPanic
from vyper.semantics.types import VyperType
from vyper.utils import VALID_IR_MACROS, ceil32

# Set default string representation for ints in IR output.
AS_HEX_DEFAULT = False

if VYPER_COLOR_OUTPUT:
    OKBLUE = "\033[94m"
    OKMAGENTA = "\033[35m"
    OKLIGHTMAGENTA = "\033[95m"
    OKLIGHTBLUE = "\033[94m"
    ENDC = "\033[0m"
else:
    OKBLUE = ""
    OKMAGENTA = ""
    OKLIGHTMAGENTA = ""
    OKLIGHTBLUE = ""
    ENDC = ""


class NullAttractor(int):
    def __add__(self, other: int) -> "NullAttractor":
        return NullAttractor()

    def __repr__(self) -> str:
        return "None"

    __radd__ = __add__
    __mul__ = __add__


class Encoding(Enum):
    # vyper encoding, default for memory variables
    VYPER = auto()
    # abi encoded, default for args/return values from external funcs
    ABI = auto()
    # future: packed


# create multiple with scopes if any of the items are complex, to force
# ordering of side effects.
# CMC 2023-08-10 this is horrible! remove this _as soon as_ we have
# real variables in IR (that we can declare without explicit scoping -
# needs liveness analysis).
@contextlib.contextmanager
def scope_multi(ir_nodes, names):
    assert len(ir_nodes) == len(names)

    should_scope = any(s._optimized.is_complex_ir for s in ir_nodes)

    class _Builder:
        def resolve(self, body):
            if not should_scope:
                # uses of the variable have already been inlined
                return body

            ret = body
            # build with scopes from inside-out (hence reversed)
            for arg, name in reversed(list(zip(ir_nodes, names))):
                ret = ["with", name, arg, ret]

            if isinstance(body, IRnode):
                return IRnode.from_list(
                    ret, typ=body.typ, location=body.location, encoding=body.encoding
                )
            else:
                return ret

    b = _Builder()
    if should_scope:
        ir_vars = tuple(
            IRnode.from_list(name, typ=arg.typ, location=arg.location, encoding=arg.encoding)
            for (arg, name) in zip(ir_nodes, names)
        )
        yield b, ir_vars
    else:
        # inline them
        yield b, ir_nodes


# this creates a magical block which maps to IR `with`
class _WithBuilder:
    def __init__(self, ir_node, name, should_inline=False):
        if should_inline and ir_node._optimized.is_complex_ir:
            # this can only mean trouble
            raise CompilerPanic("trying to inline a complex IR node")

        self.ir_node = ir_node

        # whether or not to inline the ir_node
        self.should_inline = should_inline

        # a named IR variable which represents the
        # output of `ir_node`
        self.ir_var = IRnode.from_list(
            name, typ=ir_node.typ, location=ir_node.location, encoding=ir_node.encoding
        )

    def __enter__(self):
        if self.should_inline:
            # return the value instead of the named variable
            # so it can be inlined
            return self, self.ir_node
        else:
            # return the named variable
            return self, self.ir_var

    def __exit__(self, *args):
        pass

    # MUST be called at the end of building the expression
    # in order to make sure the expression gets wrapped correctly
    def resolve(self, body):
        if self.should_inline:
            # uses of the variable have already been inlined
            return body

        ret = ["with", self.ir_var, self.ir_node, body]
        if isinstance(body, IRnode):
            return IRnode.from_list(
                ret, typ=body.typ, location=body.location, encoding=body.encoding
            )
        else:
            return ret


# Data structure for IR parse tree
class IRnode:
    repr_show_gas = False
    _gas: int
    valency: int
    args: List["IRnode"]
    value: Union[str, int]

    def __init__(
        self,
        value: Union[str, int],
        args: List["IRnode"] = None,
        typ: VyperType = None,
        location: Optional[AddrSpace] = None,
        source_pos: Optional[Tuple[int, int]] = None,
        annotation: Optional[str] = None,
        error_msg: Optional[str] = None,
        mutable: bool = True,
        add_gas_estimate: int = 0,
        encoding: Encoding = Encoding.VYPER,
    ):
        if args is None:
            args = []

        self.value = value
        self.args = args
        # TODO remove this sanity check once mypy is more thorough
        assert isinstance(typ, VyperType) or typ is None, repr(typ)
        self.typ = typ
        self.location = location
        self.source_pos = source_pos
        self.error_msg = error_msg
        self.annotation = annotation
        self.mutable = mutable
        self.add_gas_estimate = add_gas_estimate
        self.encoding = encoding
        self.as_hex = AS_HEX_DEFAULT

        def _check(condition, err):
            if not condition:
                raise CompilerPanic(str(err))

        _check(self.value is not None, "None is not allowed as IRnode value")

        # Determine this node's valency (1 if it pushes a value on the stack,
        # 0 otherwise) and checks to make sure the number and valencies of
        # children are correct. Also, find an upper bound on gas consumption
        # Numbers
        if isinstance(self.value, int):
            _check(len(self.args) == 0, "int can't have arguments")

            # integers must be in the range (MIN_INT256, MAX_UINT256)
            _check(-(2**255) <= self.value < 2**256, "out of range")

            self.valency = 1
            self._gas = 5
        elif isinstance(self.value, bytes):
            # a literal bytes value, probably inside a "data" node.
            _check(len(self.args) == 0, "bytes can't have arguments")

            self.valency = 0
            self._gas = 0

        elif isinstance(self.value, str):
            # Opcodes and pseudo-opcodes (e.g. clamp)
            if self.value.upper() in get_ir_opcodes():
                _, ins, outs, gas = get_ir_opcodes()[self.value.upper()]
                self.valency = outs
                _check(
                    len(self.args) == ins,
                    f"Number of arguments mismatched: {self.value} {self.args}",
                )
                # We add 2 per stack height at push time and take it back
                # at pop time; this makes `break` easier to handle
                self._gas = gas + 2 * (outs - ins)
                for arg in self.args:
                    # pop and pass are used to push/pop values on the stack to be
                    # consumed for internal functions, therefore we whitelist this as a zero valency
                    # allowed argument.
                    zero_valency_whitelist = {"pass", "pop"}
                    _check(
                        arg.valency == 1 or arg.value in zero_valency_whitelist,
                        f"invalid argument to `{self.value}`: {arg}",
                    )
                    self._gas += arg.gas
                # Dynamic gas cost: 8 gas for each byte of logging data
                if self.value.upper()[0:3] == "LOG" and isinstance(self.args[1].value, int):
                    self._gas += self.args[1].value * 8
                # Dynamic gas cost: non-zero-valued call
                if self.value.upper() == "CALL" and self.args[2].value != 0:
                    self._gas += 34000
                # Dynamic gas cost: filling sstore (ie. not clearing)
                elif self.value.upper() == "SSTORE" and self.args[1].value != 0:
                    self._gas += 15000
                # Dynamic gas cost: calldatacopy
                elif self.value.upper() in ("CALLDATACOPY", "CODECOPY", "EXTCODECOPY"):
                    size = 34000
                    size_arg_index = 3 if self.value.upper() == "EXTCODECOPY" else 2
                    size_arg = self.args[size_arg_index]
                    if isinstance(size_arg.value, int):
                        size = size_arg.value
                    self._gas += ceil32(size) // 32 * 3
                # Gas limits in call
                if self.value.upper() == "CALL" and isinstance(self.args[0].value, int):
                    self._gas += self.args[0].value
            # If statements
            elif self.value == "if":
                if len(self.args) == 3:
                    self._gas = self.args[0].gas + max(self.args[1].gas, self.args[2].gas) + 3
                if len(self.args) == 2:
                    self._gas = self.args[0].gas + self.args[1].gas + 17
                _check(
                    self.args[0].valency > 0,
                    f"zerovalent argument as a test to an if statement: {self.args[0]}",
                )
                _check(len(self.args) in (2, 3), "if statement can only have 2 or 3 arguments")
                self.valency = self.args[1].valency
            # With statements: with <var> <initial> <statement>
            elif self.value == "with":
                _check(len(self.args) == 3, self)
                _check(
                    len(self.args[0].args) == 0 and isinstance(self.args[0].value, str),
                    f"first argument to with statement must be a variable name: {self.args[0]}",
                )
                _check(
                    self.args[1].valency == 1 or self.args[1].value == "pass",
                    f"zerovalent argument to with statement: {self.args[1]}",
                )
                self.valency = self.args[2].valency
                self._gas = sum([arg.gas for arg in self.args]) + 5
            # Repeat statements: repeat <index_name> <startval> <rounds> <rounds_bound> <body>
            elif self.value == "repeat":
                _check(
                    len(self.args) == 5, "repeat(index_name, startval, rounds, rounds_bound, body)"
                )

                counter_ptr = self.args[0]
                start = self.args[1]
                repeat_count = self.args[2]
                repeat_bound = self.args[3]
                body = self.args[4]

                _check(
                    isinstance(repeat_bound.value, int) and repeat_bound.value > 0,
                    f"repeat bound must be a compile-time positive integer: {self.args[2]}",
                )
                _check(repeat_count.valency == 1, repeat_count)
                _check(counter_ptr.valency == 1, counter_ptr)
                _check(start.valency == 1, start)

                self.valency = 0

                self._gas = counter_ptr.gas + start.gas
                self._gas += 3  # gas for repeat_bound
                int_bound = int(repeat_bound.value)
                self._gas += int_bound * (body.gas + 50) + 30

                if repeat_count != repeat_bound:
                    # gas for assert(repeat_count <= repeat_bound)
                    self._gas += 18

            # Seq statements: seq <statement> <statement> ...
            elif self.value == "seq":
                self.valency = self.args[-1].valency if self.args else 0
                self._gas = sum([arg.gas for arg in self.args]) + 30

            # GOTO is a jump with args
            # e.g. (goto my_label x y z) will push x y and z onto the stack,
            # then JUMP to my_label.
            elif self.value in ("goto", "exit_to"):
                for arg in self.args:
                    _check(
                        arg.valency == 1 or arg.value == "pass",
                        f"zerovalent argument to goto {arg}",
                    )

                self.valency = 0
                self._gas = sum([arg.gas for arg in self.args])
            elif self.value == "label":
                _check(
                    self.args[1].value == "var_list",
                    f"2nd argument to label must be var_list, {self}",
                )
                _check(len(args) == 3, f"label should have 3 args but has {len(args)}, {self}")
                self.valency = 0
                self._gas = 1 + sum(t.gas for t in self.args)
            elif self.value == "unique_symbol":
                # a label which enforces uniqueness, and does not appear
                # in generated bytecode. this is useful for generating
                # internal assertions that a particular IR fragment only
                # occurs a single time in a program. note that unique_symbol
                # must be distinct from all `unique_symbol`s AS WELL AS all
                # `label`s, otherwise IR-to-assembly will raise an exception.
                self.valency = 0
                self._gas = 0

            # var_list names a variable number stack variables
            elif self.value == "var_list":
                for arg in self.args:
                    if not isinstance(arg.value, str) or len(arg.args) > 0:
                        raise CodegenPanic(f"var_list only takes strings: {self.args}")
                self.valency = 0
                self._gas = 0

            # Multi statements: multi <expr> <expr> ...
            elif self.value == "multi":
                for arg in self.args:
                    _check(
                        arg.valency > 0, f"Multi expects all children to not be zerovalent: {arg}"
                    )
                self.valency = sum([arg.valency for arg in self.args])
                self._gas = sum([arg.gas for arg in self.args])
            elif self.value == "deploy":
                self.valency = 0
                _check(len(self.args) == 3, f"`deploy` should have three args {self}")
                self._gas = NullAttractor()  # unknown
            # Stack variables
            else:
                self.valency = 1
                self._gas = 3
        elif self.value is None:
            self.valency = 1
            # None IRnodes always get compiled into something else, e.g.
            # mzero or PUSH1 0, and the gas will get re-estimated then.
            self._gas = 3
        else:
            raise CompilerPanic(f"Invalid value for IR AST node: {self.value}")
        assert isinstance(self.args, list)

    # TODO would be nice to rename to `gas_estimate` or `gas_bound`
    @property
    def gas(self):
        return self._gas + self.add_gas_estimate

    # the IR should be cached.
    # TODO make this private. turns out usages are all for the caching
    # idiom that cache_when_complex addresses
    @property
    def is_complex_ir(self):
        # list of items not to cache. note can add other env variables
        # which do not change, e.g. calldatasize, coinbase, etc.
        do_not_cache = {"~empty", "calldatasize", "callvalue"}

        return (
            isinstance(self.value, str)
            and (self.value.lower() in VALID_IR_MACROS or self.value.upper() in get_ir_opcodes())
            and self.value.lower() not in do_not_cache
        )

    # set an error message and push down into all children.
    # useful for overriding an error message generated by a helper
    # function with a more specific error message.
    def set_error_msg(self, error_msg: str) -> None:
        self.error_msg = error_msg
        for arg in self.args:
            arg.set_error_msg(error_msg)

    # get the unique symbols contained in this node, which provides
    # sanity check invariants for the optimizer.
    # cache because it's a perf hotspot. note that this (and other cached
    # properties!) can get borked if `self.args` are mutated in such a way
    # which changes the child `.unique_symbols`. in the future it would
    # be good to tighten down the hatches so it is harder to modify
    # IRnode member variables.
    @cached_property
    def unique_symbols(self):
        ret = set()
        if self.value == "unique_symbol":
            ret.add(self.args[0].value)

        children = self.args
        if self.value == "deploy":
            children = [self.args[0], self.args[2]]
        for arg in children:
            s = arg.unique_symbols
            non_uniques = ret.intersection(s)
            assert len(non_uniques) == 0, f"non-unique symbols {non_uniques}"
            ret |= s
        return ret

    @property
    def is_literal(self):
        return isinstance(self.value, int) or self.value == "multi"

    @property
    def is_pointer(self):
        # not used yet but should help refactor/clarify downstream code
        # eventually
        return self.location is not None

    @property  # probably could be cached_property but be paranoid
    def _optimized(self):
        # TODO figure out how to fix this circular import
        from vyper.ir.optimizer import optimize

        return optimize(self)

    # This function is slightly confusing but abstracts a common pattern:
    # when an IR value needs to be computed once and then cached as an
    # IR value (if it is expensive, or more importantly if its computation
    # includes side-effects), cache it as an IR variable named with the
    # `name` param, and execute the `body` with the cached value. Otherwise,
    # run the `body` without caching the IR variable.
    # Note that this may be an unneeded abstraction in the presence of an
    # arbitrarily powerful optimization framework (which can detect unneeded
    # caches) but for now still necessary - CMC 2021-12-11.
    # usage:
    # ```
    # with ir_node.cache_when_complex("foo") as builder, foo:
    #   ret = some_function(foo)
    #   return builder.resolve(ret)
    # ```
    def cache_when_complex(self, name):
        # for caching purposes, see if the ir_node will be optimized
        # because a non-literal expr could turn into a literal,
        # (e.g. `(add 1 2)`)
        # TODO this could really be moved into optimizer.py
        should_inline = not self._optimized.is_complex_ir

        return _WithBuilder(self, name, should_inline)

    @cached_property
    def referenced_variables(self):
        ret = set()
        for arg in self.args:
            ret |= arg.referenced_variables

        ret |= getattr(self, "_referenced_variables", set())

        return ret

    @cached_property
    def contains_self_call(self):
        return getattr(self, "is_self_call", False) or any(x.contains_self_call for x in self.args)

    def __getitem__(self, i):
        return self.to_list()[i]

    def __len__(self):
        return len(self.to_list())

    # TODO this seems like a not useful and also confusing function
    # check if dead code and remove - CMC 2021-12-13
    def to_list(self):
        return [self.value] + [a.to_list() for a in self.args]

    def __eq__(self, other):
        return (
            self.value == other.value
            and self.args == other.args
            and self.typ == other.typ
            and self.location == other.location
            and self.source_pos == other.source_pos
            and self.annotation == other.annotation
            and self.mutable == other.mutable
            and self.add_gas_estimate == other.add_gas_estimate
            and self.valency == other.valency
        )

    @property
    def repr_value(self):
        if isinstance(self.value, int) and self.as_hex:
            return hex(self.value)
        if not isinstance(self.value, str):
            return str(self.value)
        return self.value

    @staticmethod
    def _colorise_keywords(val):
        if val.lower() in VALID_IR_MACROS:  # highlight macro
            return OKLIGHTMAGENTA + val + ENDC
        elif val.upper() in get_ir_opcodes().keys():
            return OKMAGENTA + val + ENDC
        return val

    def repr(self) -> str:
        if not len(self.args):
            if self.annotation:
                return f"{self.repr_value} " + OKLIGHTBLUE + f"<{self.annotation}>" + ENDC
            else:
                return str(self.repr_value)
        # x = repr(self.to_list())
        # if len(x) < 80:
        #     return x
        o = ""
        if self.annotation:
            o += f"/* {self.annotation} */ \n"
        if self.repr_show_gas and self.gas:
            o += OKBLUE + "{" + ENDC + str(self.gas) + OKBLUE + "} " + ENDC  # add gas for info.
        o += "[" + self._colorise_keywords(self.repr_value)
        prev_lineno = self.source_pos[0] if self.source_pos else None
        arg_lineno = None
        annotated = False
        has_inner_newlines = False
        for arg in self.args:
            o += ",\n  "
            arg_lineno = arg.source_pos[0] if arg.source_pos else None
            if arg_lineno is not None and arg_lineno != prev_lineno and self.value in ("seq", "if"):
                o += f"# Line {(arg_lineno)}\n  "
                prev_lineno = arg_lineno
                annotated = True
            arg_repr = arg.repr()
            if "\n" in arg_repr:
                has_inner_newlines = True
            sub = arg_repr.replace("\n", "\n  ").strip(" ")
            o += self._colorise_keywords(sub)
        output = o.rstrip(" ") + "]"
        output_on_one_line = re.sub(r",\n *", ", ", output).replace("\n", "")

        should_output_single_line = (
            (len(output_on_one_line) < 80 or len(self.args) == 1) and not annotated
        ) and not has_inner_newlines

        if should_output_single_line:
            return output_on_one_line
        else:
            return output

    def __repr__(self):
        return self.repr()

    @classmethod
    def from_list(
        cls,
        obj: Any,
        typ: VyperType = None,
        location: Optional[AddrSpace] = None,
        source_pos: Optional[Tuple[int, int]] = None,
        annotation: Optional[str] = None,
        error_msg: Optional[str] = None,
        mutable: bool = True,
        add_gas_estimate: int = 0,
        encoding: Encoding = Encoding.VYPER,
    ) -> "IRnode":
        if isinstance(typ, str):
            raise CompilerPanic(f"Expected type, not string: {typ}")

        if isinstance(obj, IRnode):
            # note: this modify-and-returnclause is a little weird since
            # the input gets modified. CC 20191121.
            if typ is not None:
                obj.typ = typ
            if obj.source_pos is None:
                obj.source_pos = source_pos
            if obj.location is None:
                obj.location = location
            if obj.encoding is None:
                obj.encoding = encoding
            if obj.error_msg is None:
                obj.error_msg = error_msg

            return obj
        elif not isinstance(obj, list):
            return cls(
                obj,
                [],
                typ,
                location=location,
                annotation=annotation,
                mutable=mutable,
                add_gas_estimate=add_gas_estimate,
                source_pos=source_pos,
                encoding=encoding,
                error_msg=error_msg,
            )
        else:
            return cls(
                obj[0],
                [cls.from_list(o, source_pos=source_pos) for o in obj[1:]],
                typ,
                location=location,
                annotation=annotation,
                mutable=mutable,
                source_pos=source_pos,
                add_gas_estimate=add_gas_estimate,
                encoding=encoding,
                error_msg=error_msg,
            )
