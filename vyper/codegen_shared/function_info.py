"""
Shared function metadata used by both codegen pipelines.

If codegen_legacy is removed, consider refactoring — some fields
(ir_node, func_ir, frame_info) are only used by the legacy pipeline
and can be removed at that point.
"""

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, Optional

from vyper.semantics.types.function import ContractFunctionT

if TYPE_CHECKING:
    from vyper.venom.basicblock import IRVariable


@dataclass
class _FuncIRInfo:
    func_t: ContractFunctionT
    gas_estimate: Optional[int] = None
    frame_info: Optional[Any] = None  # FrameInfo (legacy-only)
    func_ir: Optional[Any] = None  # InternalFuncIR (legacy-only)
    # For venom codegen: maps kwarg names to alloca IRVariables for sharing between entry points
    kwarg_alloca_vars: Optional[dict[str, "IRVariable"]] = None

    @property
    def visibility(self):
        return "internal" if self.func_t.is_internal else "external"

    @property
    def exit_sequence_label(self) -> str:
        return self.ir_identifier + "_cleanup"

    @cached_property
    def ir_identifier(self) -> str:
        argz = ",".join([str(argtyp) for argtyp in self.func_t.argument_types])

        name = self.func_t.name
        function_id = self.func_t._function_id
        assert function_id is not None

        # include module id in the ir identifier to disambiguate functions
        # with the same name but which come from different modules
        return f"{self.visibility} {function_id} {name}({argz})"

    def set_frame_info(self, frame_info: Any) -> None:
        if self.frame_info is not None:
            assert frame_info == self.frame_info
        else:
            self.frame_info = frame_info

    def set_func_ir(self, func_ir: Any) -> None:
        assert self.func_t.is_internal or self.func_t.is_deploy
        self.func_ir = func_ir

    @property
    # common entry point for external function with kwargs
    def external_function_base_entry_label(self) -> str:
        assert not self.func_t.is_internal, "uh oh, should be external"
        return self.ir_identifier + "_common"

    def internal_function_label(self, is_ctor_context: bool = False) -> str:
        f = self.func_t
        assert f.is_internal or f.is_constructor, "uh oh, should be internal"

        if f.is_constructor:
            # sanity check - imported init functions only callable from main init
            assert is_ctor_context

        suffix = "_deploy" if is_ctor_context else "_runtime"
        return self.ir_identifier + suffix


@dataclass
class EntryPointInfo:
    func_t: ContractFunctionT
    min_calldatasize: int  # the min calldata required for this entry point
    ir_node: Optional[Any] = None  # the ir for this entry point (None for venom codegen)

    def __post_init__(self):
        # sanity check ABI v2 properties guaranteed by the spec.
        assert self.min_calldatasize >= 4
        assert (self.min_calldatasize - 4) % 32 == 0


def init_ir_info(func_t: ContractFunctionT):
    """Initialize IRInfo on the function type."""
    func_t._ir_info = _FuncIRInfo(func_t)
