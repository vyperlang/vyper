import re
from enum import Enum, auto
from typing import Any, List, Optional, Tuple, Union

from vyper.codegen.types import BaseType, NodeType, ceil32
from vyper.compiler.settings import VYPER_COLOR_OUTPUT
from vyper.evm.opcodes import get_comb_opcodes
from vyper.exceptions import CompilerPanic
from vyper.utils import VALID_LLL_MACROS, cached_property

# Set default string representation for ints in LLL output.
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


def push_label_to_stack(labelname: str) -> str:
    #  items prefixed with `_sym_` are ignored until asm phase
    return "_sym_" + labelname


class Encoding(Enum):
    # vyper encoding, default for memory variables
    VYPER = auto()
    # abi encoded, default for args/return values from external funcs
    ABI = auto()
    # abi encoded, same as ABI but no clamps for bytestrings
    JSON_ABI = auto()
    # future: packed


# Data structure for LLL parse tree
class LLLnode:
    repr_show_gas = False
    gas: int
    valency: int
    args: List["LLLnode"]
    value: Union[str, int]

    def __init__(
        self,
        value: Union[str, int],
        args: List["LLLnode"] = None,
        typ: NodeType = None,
        location: str = None,
        pos: Optional[Tuple[int, int]] = None,
        annotation: Optional[str] = None,
        mutable: bool = True,
        add_gas_estimate: int = 0,
        valency: Optional[int] = None,
        encoding: Encoding = Encoding.VYPER,
    ):
        if args is None:
            args = []

        self.value = value
        self.args = args
        # TODO remove this sanity check once mypy is more thorough
        assert isinstance(typ, NodeType) or typ is None, repr(typ)
        self.typ = typ
        self.location = location
        self.pos = pos
        self.annotation = annotation
        self.mutable = mutable
        self.add_gas_estimate = add_gas_estimate
        self.encoding = encoding
        self.as_hex = AS_HEX_DEFAULT

        # Optional annotation properties for gas estimation
        self.total_gas = None
        self.func_name = None

        def _check(condition, err):
            if not condition:
                raise CompilerPanic(str(err))

        # Determine this node's valency (1 if it pushes a value on the stack,
        # 0 otherwise) and checks to make sure the number and valencies of
        # children are correct. Also, find an upper bound on gas consumption
        # Numbers
        if isinstance(self.value, int):
            self.valency = 1
            self.gas = 5
        elif isinstance(self.value, str):
            # Opcodes and pseudo-opcodes (e.g. clamp)
            if self.value.upper() in get_comb_opcodes():
                _, ins, outs, gas = get_comb_opcodes()[self.value.upper()]
                self.valency = outs
                _check(
                    len(self.args) == ins,
                    f"Number of arguments mismatched: {self.value} {self.args}",
                )
                # We add 2 per stack height at push time and take it back
                # at pop time; this makes `break` easier to handle
                self.gas = gas + 2 * (outs - ins)
                for arg in self.args:
                    # pop and pass are used to push/pop values on the stack to be
                    # consumed for internal functions, therefore we whitelist this as a zero valency
                    # allowed argument.
                    zero_valency_whitelist = {"pass", "pop"}
                    _check(
                        arg.valency == 1 or arg.value in zero_valency_whitelist,
                        f"invalid argument to opcode or pseudo-opcode: {arg}",
                    )
                    self.gas += arg.gas
                # Dynamic gas cost: 8 gas for each byte of logging data
                if self.value.upper()[0:3] == "LOG" and isinstance(self.args[1].value, int):
                    self.gas += self.args[1].value * 8
                # Dynamic gas cost: non-zero-valued call
                if self.value.upper() == "CALL" and self.args[2].value != 0:
                    self.gas += 34000
                # Dynamic gas cost: filling sstore (ie. not clearing)
                elif self.value.upper() == "SSTORE" and self.args[1].value != 0:
                    self.gas += 15000
                # Dynamic gas cost: calldatacopy
                elif self.value.upper() in ("CALLDATACOPY", "CODECOPY", "EXTCODECOPY"):
                    size = 34000
                    size_arg_index = 3 if self.value.upper() == "EXTCODECOPY" else 2
                    size_arg = self.args[size_arg_index]
                    if isinstance(size_arg.value, int):
                        size = size_arg.value
                    self.gas += ceil32(size) // 32 * 3
                # Gas limits in call
                if self.value.upper() == "CALL" and isinstance(self.args[0].value, int):
                    self.gas += self.args[0].value
            # If statements
            elif self.value == "if":
                if len(self.args) == 3:
                    self.gas = self.args[0].gas + max(self.args[1].gas, self.args[2].gas) + 3
                if len(self.args) == 2:
                    self.gas = self.args[0].gas + self.args[1].gas + 17
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
                self.gas = sum([arg.gas for arg in self.args]) + 5
            # Repeat statements: repeat <index_memloc> <startval> <rounds> <body>
            elif self.value == "repeat":
                repeat_count = None
                if len(self.args) == 4:
                    counter_ptr = self.args[0]
                    start = self.args[1]
                    repeat_bound = self.args[2].value  # constant int
                    body = self.args[3]
                elif len(self.args) == 5:
                    counter_ptr = self.args[0]
                    start = self.args[1]
                    repeat_count = self.args[2]
                    repeat_bound = self.args[3].value  # constant int
                    body = self.args[4]
                _check(
                    isinstance(repeat_bound, int) and repeat_bound > 0,
                    f"repeat bound must be a compile-time positive integer: {self.args[2]}",
                )
                _check(repeat_count is None or repeat_count.valency == 1, repeat_count)
                _check(counter_ptr.valency == 1, counter_ptr)
                _check(start.valency == 1, start)
                _check(body.valency == 0, body)
                self.valency = 0

                self.gas = counter_ptr.gas + start.gas
                self.gas += 3  # gas for repeat_bound
                repeat_bound = int(repeat_bound)  # mypy complaint
                self.gas += repeat_bound * (body.gas + 50) + 30
                if repeat_count is not None:
                    self.gas += repeat_count.gas
                    # gas to calculate min(repeat_count, repeat_bound)
                    self.gas += 29

            # Seq statements: seq <statement> <statement> ...
            elif self.value == "seq":
                self.valency = self.args[-1].valency if self.args else 0
                self.gas = sum([arg.gas for arg in self.args]) + 30

            # GOTO is a jump with args
            # e.g. (goto my_label x y z) will push x y and z onto the stack,
            # then JUMP to my_label.
            elif self.value == "goto":
                for arg in self.args:
                    _check(
                        arg.valency == 1 or arg.value == "pass",
                        f"zerovalent argument to goto {arg}",
                    )

                self.valency = 0
                self.gas = sum([arg.gas for arg in self.args])
            # Multi statements: multi <expr> <expr> ...
            elif self.value == "multi":
                for arg in self.args:
                    _check(
                        arg.valency > 0, f"Multi expects all children to not be zerovalent: {arg}"
                    )
                self.valency = sum([arg.valency for arg in self.args])
                self.gas = sum([arg.gas for arg in self.args])
            # LLL brackets (don't bother gas counting)
            elif self.value == "lll":
                self.valency = 1
                self.gas = NullAttractor()
            # Stack variables
            else:
                self.valency = 1
                self.gas = 3
        elif self.value is None:
            self.valency = 1
            # None LLLnodes always get compiled into something else, e.g.
            # mzero or PUSH1 0, and the gas will get re-estimated then.
            self.gas = 3
        else:
            raise CompilerPanic(f"Invalid value for LLL AST node: {self.value}")
        assert isinstance(self.args, list)

        if valency is not None:
            self.valency = valency

        self.gas += self.add_gas_estimate

    # the LLL should be cached.
    @property
    def is_complex_lll(self):
        return isinstance(self.value, str) and (
            self.value.lower() in VALID_LLL_MACROS or self.value.upper() in get_comb_opcodes()
        )

    # This function is slightly confusing but abstracts a common pattern:
    # when an LLL value needs to be computed once and then cached as an
    # LLL value (if it is expensive, or more importantly if its computation
    # includes side-effcts), cache it as an LLL variable named with the
    # `name` param, and execute the `body` with the cached value. Otherwise,
    # run the `body` without caching the LLL variable.
    # Note that this may be an unneeded abstraction in the presence of an
    # arbitrarily powerful optimization framework (which can detect unneeded
    # caches) but for now still necessary - CMC 2021-12-11.
    # usage:
    # ```
    # with lll_node.cache_when_complex("foo") as builder, foo:
    #   ret = some_function(foo)
    #   return builder.resolve(ret)
    # ```
    def cache_when_complex(self, name):
        # this creates a magical block which maps to LLL `with`
        class _WithBuilder:
            def __init__(self, lll_node, name):
                self.lll_node = lll_node
                # a named LLL variable which represents the
                # output of `lll_node`
                self.lll_var = LLLnode.from_list(
                    name, typ=lll_node.typ, location=lll_node.location, encoding=lll_node.encoding
                )

            def __enter__(self):
                if self.lll_node.is_complex_lll:
                    # return the named cache
                    return self, self.lll_var
                else:
                    # it's a constant, just return that
                    return self, self.lll_node

            def __exit__(self, *args):
                pass

            # MUST be called at the end of building the expression
            # in order to make sure the expression gets wrapped correctly
            def resolve(self, body):
                if self.lll_node.is_complex_lll:
                    ret = ["with", self.lll_var, self.lll_node, body]
                    if isinstance(body, LLLnode):
                        return LLLnode.from_list(
                            ret, typ=body.typ, location=body.location, encoding=body.encoding
                        )
                    else:
                        return ret
                else:
                    return body

        return _WithBuilder(self, name)

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
            and self.pos == other.pos
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
        if val.lower() in VALID_LLL_MACROS:  # highlight macro
            return OKLIGHTMAGENTA + val + ENDC
        elif val.upper() in get_comb_opcodes().keys():
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
        prev_lineno = self.pos[0] if self.pos else None
        arg_lineno = None
        annotated = False
        has_inner_newlines = False
        for arg in self.args:
            o += ",\n  "
            arg_lineno = arg.pos[0] if arg.pos else None
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
        typ: NodeType = None,
        location: str = None,
        pos: Tuple[int, int] = None,
        annotation: Optional[str] = None,
        mutable: bool = True,
        add_gas_estimate: int = 0,
        valency: Optional[int] = None,
        encoding: Encoding = Encoding.VYPER,
    ) -> "LLLnode":
        if isinstance(typ, str):
            typ = BaseType(typ)

        if isinstance(obj, LLLnode):
            # note: this modify-and-returnclause is a little weird since
            # the input gets modified. CC 20191121.
            if typ is not None:
                obj.typ = typ
            if obj.pos is None:
                obj.pos = pos
            if obj.location is None:
                obj.location = location
            if obj.encoding is None:
                obj.encoding = encoding

            return obj
        elif not isinstance(obj, list):
            return cls(
                obj,
                [],
                typ,
                location=location,
                pos=pos,
                annotation=annotation,
                mutable=mutable,
                add_gas_estimate=add_gas_estimate,
                valency=valency,
                encoding=encoding,
            )
        else:
            return cls(
                obj[0],
                [cls.from_list(o, pos=pos) for o in obj[1:]],
                typ,
                location=location,
                pos=pos,
                annotation=annotation,
                mutable=mutable,
                add_gas_estimate=add_gas_estimate,
                valency=valency,
                encoding=encoding,
            )
