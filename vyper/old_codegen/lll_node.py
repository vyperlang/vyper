import re
from typing import Any, List, Optional, Tuple, Union

from vyper.compiler.settings import VYPER_COLOR_OUTPUT
from vyper.evm.opcodes import get_comb_opcodes
from vyper.exceptions import CompilerPanic
from vyper.old_codegen.types import BaseType, NodeType, ceil32
from vyper.utils import VALID_LLL_MACROS

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
        typ: "BaseType" = None,
        location: str = None,
        pos: Optional[Tuple[int, int]] = None,
        annotation: Optional[str] = None,
        mutable: bool = True,
        add_gas_estimate: int = 0,
        valency: Optional[int] = None,
    ):
        if args is None:
            args = []

        self.value = value
        self.args = args
        self.typ = typ
        assert isinstance(self.typ, NodeType) or self.typ is None, repr(self.typ)
        self.location = location
        self.pos = pos
        self.annotation = annotation
        self.mutable = mutable
        self.add_gas_estimate = add_gas_estimate
        self.as_hex = AS_HEX_DEFAULT

        # Optional annotation properties for gas estimation
        self.total_gas = None
        self.func_name = None

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
                if len(self.args) != ins:
                    raise CompilerPanic(f"Number of arguments mismatched: {self.value} {self.args}")
                # We add 2 per stack height at push time and take it back
                # at pop time; this makes `break` easier to handle
                self.gas = gas + 2 * (outs - ins)
                for arg in self.args:
                    # pop and pass are used to push/pop values on the stack to be
                    # consumed for internal functions, therefore we whitelist this as a zero valency
                    # allowed argument.
                    zero_valency_whitelist = {"pass", "pop"}
                    if arg.valency == 0 and arg.value not in zero_valency_whitelist:
                        raise CompilerPanic(
                            "Can't have a zerovalent argument to an opcode or a pseudo-opcode! "
                            f"{arg.value}: {arg}. Please file a bug report."
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
                elif self.value.upper() in ("CALLDATACOPY", "CODECOPY"):
                    size = 34000
                    if isinstance(self.args[2].value, int):
                        size = self.args[2].value
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
                if not self.args[0].valency:
                    raise CompilerPanic(
                        "Can't have a zerovalent argument as a test to an if "
                        f"statement! {self.args[0]}"
                    )
                if len(self.args) not in (2, 3):
                    raise CompilerPanic("If can only have 2 or 3 arguments")
                self.valency = self.args[1].valency
            # With statements: with <var> <initial> <statement>
            elif self.value == "with":
                if len(self.args) != 3:
                    raise CompilerPanic("With statement must have 3 arguments")
                if len(self.args[0].args) or not isinstance(self.args[0].value, str):
                    raise CompilerPanic("First argument to with statement must be a variable")
                if not self.args[1].valency and self.args[1].value != "pass":
                    raise CompilerPanic(
                        (
                            "Second argument to with statement (initial value) "
                            f"cannot be zerovalent: {self.args[1]}"
                        )
                    )
                self.valency = self.args[2].valency
                self.gas = sum([arg.gas for arg in self.args]) + 5
            # Repeat statements: repeat <index_memloc> <startval> <rounds> <body>
            elif self.value == "repeat":
                is_invalid_repeat_count = any(
                    (
                        len(self.args[2].args),
                        not isinstance(self.args[2].value, int),
                        isinstance(self.args[2].value, int) and self.args[2].value <= 0,
                    )
                )

                if is_invalid_repeat_count:
                    raise CompilerPanic(
                        (
                            "Number of times repeated must be a constant nonzero "
                            f"positive integer: {self.args[2]}"
                        )
                    )
                if not self.args[0].valency:
                    raise CompilerPanic(
                        (
                            "First argument to repeat (memory location) cannot be "
                            f"zerovalent: {self.args[0]}"
                        )
                    )
                if not self.args[1].valency:
                    raise CompilerPanic(
                        (
                            "Second argument to repeat (start value) cannot be "
                            f"zerovalent: {self.args[1]}"
                        )
                    )
                if self.args[3].valency:
                    raise CompilerPanic(
                        (
                            "Third argument to repeat (clause to be repeated) must "
                            f"be zerovalent: {self.args[3]}"
                        )
                    )
                self.valency = 0
                rounds: int
                if self.args[1].value in ("calldataload", "mload") or self.args[1].value == "sload":
                    if isinstance(self.args[2].value, int):
                        rounds = self.args[2].value
                    else:
                        raise CompilerPanic(f"Unsupported rounds argument type. {self.args[2]}")
                else:
                    if isinstance(self.args[2].value, int) and isinstance(self.args[1].value, int):
                        rounds = abs(self.args[2].value - self.args[1].value)
                    else:
                        raise CompilerPanic(f"Unsupported second argument types. {self.args}")
                self.gas = rounds * (self.args[3].gas + 50) + 30
            # Seq statements: seq <statement> <statement> ...
            elif self.value == "seq":
                self.valency = self.args[-1].valency if self.args else 0
                self.gas = sum([arg.gas for arg in self.args]) + 30
            # Multi statements: multi <expr> <expr> ...
            elif self.value == "multi":
                for arg in self.args:
                    if not arg.valency:
                        raise CompilerPanic(
                            f"Multi expects all children to not be zerovalent: {arg}"
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
                self.gas = 5
                if self.value == "seq_unchecked":
                    self.gas = sum([arg.gas for arg in self.args]) + 30
                if self.value == "if_unchecked":
                    self.gas = self.args[0].gas + self.args[1].gas + 17
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

    def __getitem__(self, i):
        return self.to_list()[i]

    def __len__(self):
        return len(self.to_list())

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
        typ: "BaseType" = None,
        location: str = None,
        pos: Tuple[int, int] = None,
        annotation: Optional[str] = None,
        mutable: bool = True,
        add_gas_estimate: int = 0,
        valency: Optional[int] = None,
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
            )
