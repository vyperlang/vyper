from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Sequence, Union

from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.function import IRFunction

if TYPE_CHECKING:
    from vyper.semantics.data_locations import DataLocation
    from vyper.venom.context import IRContext

# IROperand is the base class for IRVariable, IRLiteral, IRLabel
Operand = Union[IROperand, int]


class VenomBuilder:
    """Clean API for building Venom IR.

    Wraps IRContext/IRFunction/IRBasicBlock to provide explicit,
    type-safe instruction emission.
    """

    ctx: IRContext
    fn: IRFunction
    _current_bb: IRBasicBlock

    def __init__(self, ctx: IRContext, fn: IRFunction):
        self.ctx = ctx
        self.fn = fn
        self._current_bb = fn.entry

    # === Block Management ===
    @property
    def current_block(self) -> IRBasicBlock:
        """Get current emission target block."""
        return self._current_bb

    def create_block(self, suffix: str = "") -> IRBasicBlock:
        """Create new block with auto-generated label. Does NOT switch to it or append it."""
        label = self.ctx.get_next_label(suffix)
        return IRBasicBlock(label, self.fn)

    def append_block(self, bb: IRBasicBlock) -> None:
        """Append block to function (must be done before emitting to it)."""
        self.fn.append_basic_block(bb)

    def set_block(self, bb: IRBasicBlock) -> None:
        """Switch emission target to given block."""
        self._current_bb = bb

    def is_terminated(self) -> bool:
        """Check if current block has a terminator instruction."""
        return self._current_bb.is_terminated

    def create_and_switch_block(self, suffix: str = "") -> IRBasicBlock:
        """Create, append, and switch to new block. Convenience method."""
        bb = self.create_block(suffix)
        self.append_block(bb)
        self.set_block(bb)
        return bb

    def new_variable(self) -> IRVariable:
        """Create fresh SSA variable without emitting any instruction.

        Useful for ternary expressions and multi-return patterns where
        you need a target variable before the value is computed.
        """
        return self.fn.get_next_variable()

    # === Arithmetic ===
    def add(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("add", a, b)

    def sub(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("sub", a, b)

    def mul(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("mul", a, b)

    def div(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("div", a, b)

    def sdiv(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("sdiv", a, b)

    def mod(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("mod", a, b)

    def smod(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("smod", a, b)

    def exp(self, base: Operand, exponent: Operand) -> IRVariable:
        return self._emit1_evm("exp", base, exponent)

    def addmod(self, a: Operand, b: Operand, n: Operand) -> IRVariable:
        return self._emit1_evm("addmod", a, b, n)

    def mulmod(self, a: Operand, b: Operand, n: Operand) -> IRVariable:
        return self._emit1_evm("mulmod", a, b, n)

    def signextend(self, byte_width: Operand, val: Operand) -> IRVariable:
        return self._emit1_evm("signextend", byte_width, val)

    # === Bitwise ===
    def and_(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("and", a, b)

    def or_(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("or", a, b)

    def xor(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("xor", a, b)

    def not_(self, a: Operand) -> IRVariable:
        return self._emit1_evm("not", a)

    def shl(self, bits: Operand, val: Operand) -> IRVariable:
        return self._emit1_evm("shl", bits, val)

    def shr(self, bits: Operand, val: Operand) -> IRVariable:
        return self._emit1_evm("shr", bits, val)

    def sar(self, bits: Operand, val: Operand) -> IRVariable:
        return self._emit1_evm("sar", bits, val)

    # === Comparison ===
    def eq(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("eq", a, b)

    def lt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("lt", a, b)

    def gt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("gt", a, b)

    def slt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("slt", a, b)

    def sgt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1_evm("sgt", a, b)

    def iszero(self, a: Operand) -> IRVariable:
        return self._emit1_evm("iszero", a)

    # === Memory ===
    def mload(self, ptr: Operand) -> IRVariable:
        return self._emit1_evm("mload", ptr)

    def mstore(self, ptr: Operand, val: Operand) -> None:
        """Store val at memory[ptr]."""
        self._emit_evm("mstore", ptr, val)

    def mcopy(self, dst: Operand, src: Operand, size: Operand) -> None:
        """Copy size bytes from memory[src] to memory[dst]."""
        self._emit_evm("mcopy", dst, src, size)

    def msize(self) -> IRVariable:
        return self._emit1_evm("msize")

    def alloca(self, size: int, alloca_id: int) -> IRVariable:
        """Allocate abstract memory. Returns pointer. (IR-specific)"""
        return self._emit1("alloca", size, alloca_id)

    def palloca(self, size: int, alloca_id: int) -> IRVariable:
        """Allocate parameter memory in callee frame. Returns pointer. (IR-specific)"""
        return self._emit1("palloca", size, alloca_id)

    def calloca(self, size: int, alloca_id: int, callsite: IRLabel) -> IRVariable:
        """Allocate argument staging memory at call site. Returns pointer. (IR-specific)

        Used for memory-passed arguments when calling internal functions.
        The callsite label links this allocation to a specific invoke.
        """
        return self._emit1("calloca", size, alloca_id, callsite)

    def gep(self, ptr: Operand, offset: Operand) -> IRVariable:
        """Get element pointer into memory region. (IR-specific)

        Used for accessing elements within abstract memory (e.g., immutables).
        """
        return self._emit1("gep", ptr, offset)

    # === Storage ===
    def sload(self, slot: Operand) -> IRVariable:
        return self._emit1_evm("sload", slot)

    def sstore(self, slot: Operand, val: Operand) -> None:
        """Store val at storage[slot]."""
        self._emit_evm("sstore", slot, val)

    def tload(self, slot: Operand) -> IRVariable:
        return self._emit1_evm("tload", slot)

    def tstore(self, slot: Operand, val: Operand) -> None:
        """Store val at transient[slot]."""
        self._emit_evm("tstore", slot, val)

    # === Location-aware load/store ===
    def load(self, ptr: Operand, location: "DataLocation") -> IRVariable:
        """Load from ptr, dispatching based on data location."""
        from vyper.semantics.data_locations import DataLocation

        if location == DataLocation.STORAGE:
            return self.sload(ptr)
        elif location == DataLocation.TRANSIENT:
            return self.tload(ptr)
        elif location == DataLocation.MEMORY:
            return self.mload(ptr)
        elif location == DataLocation.CALLDATA:
            return self.calldataload(ptr)
        elif location == DataLocation.CODE:
            return self.dload(ptr)
        else:
            raise CompilerPanic(f"Cannot load from location: {location}")

    def store(self, ptr: Operand, val: Operand, location: "DataLocation") -> None:
        """Store val to ptr, dispatching based on data location."""
        from vyper.semantics.data_locations import DataLocation

        if location == DataLocation.STORAGE:
            self.sstore(ptr, val)
        elif location == DataLocation.TRANSIENT:
            self.tstore(ptr, val)
        elif location == DataLocation.MEMORY:
            self.mstore(ptr, val)
        else:
            raise CompilerPanic(f"Cannot store to location: {location}")

    def copy_to_memory(
        self, dst: Operand, src: Operand, size: Operand, src_location: "DataLocation"
    ) -> None:
        """Copy size bytes from src_location to memory at dst."""
        from vyper.semantics.data_locations import DataLocation

        if src_location == DataLocation.MEMORY:
            from vyper.evm.opcodes import version_check

            if version_check(begin="cancun"):
                self.mcopy(dst, src, size)
            else:
                # Pre-Cancun: use identity precompile (address 4)
                gas = self.gas()
                success = self.staticcall(gas, IRLiteral(4), src, size, dst, size)
                self.assert_(success)
        elif src_location == DataLocation.CALLDATA:
            self.calldatacopy(dst, src, size)
        elif src_location == DataLocation.CODE:
            self.dloadbytes(dst, src, size)
        else:
            raise CompilerPanic(f"Cannot copy from location: {src_location}")

    # === Immutables / Data Section ===
    def dload(self, offset: Operand) -> IRVariable:
        """Load 32 bytes from data section. (IR-specific)"""
        return self._emit1("dload", offset)

    def dloadbytes(self, dst: Operand, src: Operand, size: Operand) -> None:
        """Copy size bytes from data section (src) to memory (dst). (IR-specific)"""
        # Use _emit_evm for consistent operand order with codecopy
        # Stored as [size, src, dst] (reversed from semantic order)
        self._emit_evm("dloadbytes", dst, src, size)

    def iload(self, offset: Operand) -> IRVariable:
        """Load from immutable memory region. (IR-specific)"""
        return self._emit1("iload", offset)

    def istore(self, offset: Operand, val: Operand) -> None:
        """Store val to immutable memory region at offset (deploy-time only). (IR-specific)"""
        self._emit("istore", offset, val)

    def offset(self, operand: Operand, label: IRLabel) -> IRVariable:
        """Compute static offset from label. Used for code position calculations. (IR-specific)

        Computes label + operand. Args order matches Venom IR: offset operand, @label
        """
        return self._emit1("offset", operand, label)

    # === Control Flow (IR-specific) ===
    def jmp(self, target: IRLabel) -> None:
        """Unconditional jump. Terminates block."""
        self._emit("jmp", target)

    def jnz(self, cond: Operand, then_label: IRLabel, else_label: IRLabel) -> None:
        """Conditional branch. Terminates block."""
        self._emit("jnz", cond, then_label, else_label)

    def djmp(self, target: Operand, *labels: IRLabel) -> None:
        """Dynamic jump to one of labels based on target. Terminates block."""
        self._emit("djmp", target, *labels)

    def ret(self, *values: Operand) -> None:
        """Return from internal function. Terminates block."""
        self._emit("ret", *values)

    # === EVM Terminators ===
    def return_(self, offset: Operand, size: Operand) -> None:
        """Return from external call (EVM RETURN). Terminates block."""
        self._emit_evm("return", offset, size)

    def stop(self) -> None:
        """Halt execution. Terminates block."""
        self._emit_evm("stop")

    def revert(self, offset: Operand, size: Operand) -> None:
        """Revert execution. Terminates block."""
        self._emit_evm("revert", offset, size)

    def invalid(self) -> None:
        """Invalid opcode. Terminates block."""
        self._emit_evm("invalid")

    # === Assertions (IR-specific) ===
    def assert_(self, cond: Operand) -> None:
        """Assert condition (reverts if false)."""
        self._emit("assert", cond)

    def assert_unreachable(self, cond: Operand) -> None:
        """Assert unreachable code path."""
        self._emit("assert_unreachable", cond)

    # === Internal Calls (IR-specific) ===
    def invoke(
        self, target: IRLabel, args: Sequence[Operand], returns: int = 0
    ) -> list[IRVariable]:
        """Call internal function. Returns list of output variables."""
        all_args = [target] + list(args)
        return self._current_bb.append_invoke_instruction(all_args, returns=returns)

    def param(self) -> IRVariable:
        """Declare function parameter (must be at block start)."""
        return self._emit1("param")

    # === External Calls ===
    def call(
        self,
        gas: Operand,
        addr: Operand,
        val: Operand,
        argsptr: Operand,
        argsz: Operand,
        retptr: Operand,
        retsz: Operand,
    ) -> IRVariable:
        """EVM CALL: call(gas, addr, value, argsOffset, argsSize, retOffset, retSize)."""
        return self._emit1_evm("call", gas, addr, val, argsptr, argsz, retptr, retsz)

    def staticcall(
        self,
        gas: Operand,
        addr: Operand,
        argsptr: Operand,
        argsz: Operand,
        retptr: Operand,
        retsz: Operand,
    ) -> IRVariable:
        """EVM STATICCALL: staticcall(gas, addr, argsOffset, argsSize, retOffset, retSize)."""
        return self._emit1_evm("staticcall", gas, addr, argsptr, argsz, retptr, retsz)

    def delegatecall(
        self,
        gas: Operand,
        addr: Operand,
        argsptr: Operand,
        argsz: Operand,
        retptr: Operand,
        retsz: Operand,
    ) -> IRVariable:
        """EVM DELEGATECALL: delegatecall(gas, addr, argsOffset, argsSize, retOffset, retSize)."""
        return self._emit1_evm("delegatecall", gas, addr, argsptr, argsz, retptr, retsz)

    def create(self, val: Operand, offset: Operand, size: Operand) -> IRVariable:
        """EVM CREATE: create(value, offset, size)."""
        return self._emit1_evm("create", val, offset, size)

    def create2(self, val: Operand, offset: Operand, size: Operand, salt: Operand) -> IRVariable:
        """EVM CREATE2: create2(value, offset, size, salt)."""
        return self._emit1_evm("create2", val, offset, size, salt)

    # === Crypto ===
    def sha3(self, ptr: Operand, size: Operand) -> IRVariable:
        return self._emit1_evm("sha3", ptr, size)

    def sha3_64(self, a: Operand, b: Operand) -> IRVariable:
        """Hash two 32-byte values (optimized keccak). (IR-specific)"""
        return self._emit1("sha3_64", a, b)

    # === Data Copy ===
    def calldatacopy(self, dst: Operand, src: Operand, size: Operand) -> None:
        """Copy size bytes from calldata[src] to memory[dst]."""
        self._emit_evm("calldatacopy", dst, src, size)

    def codecopy(self, dst: Operand, src: Operand, size: Operand) -> None:
        """Copy size bytes from code[src] to memory[dst]."""
        self._emit_evm("codecopy", dst, src, size)

    def extcodecopy(self, addr: Operand, dst: Operand, src: Operand, size: Operand) -> None:
        """Copy size bytes from addr's code[src] to memory[dst]."""
        self._emit_evm("extcodecopy", addr, dst, src, size)

    def returndatacopy(self, dst: Operand, src: Operand, size: Operand) -> None:
        """Copy size bytes from returndata[src] to memory[dst]."""
        self._emit_evm("returndatacopy", dst, src, size)

    # === Environment ===
    def caller(self) -> IRVariable:
        return self._emit1_evm("caller")

    def callvalue(self) -> IRVariable:
        return self._emit1_evm("callvalue")

    def calldatasize(self) -> IRVariable:
        return self._emit1_evm("calldatasize")

    def calldataload(self, offset: Operand) -> IRVariable:
        return self._emit1_evm("calldataload", offset)

    def address(self) -> IRVariable:
        return self._emit1_evm("address")

    def balance(self, addr: Operand) -> IRVariable:
        return self._emit1_evm("balance", addr)

    def selfbalance(self) -> IRVariable:
        return self._emit1_evm("selfbalance")

    def origin(self) -> IRVariable:
        return self._emit1_evm("origin")

    def gas(self) -> IRVariable:
        return self._emit1_evm("gas")

    def gasprice(self) -> IRVariable:
        return self._emit1_evm("gasprice")

    def codesize(self) -> IRVariable:
        return self._emit1_evm("codesize")

    def extcodesize(self, addr: Operand) -> IRVariable:
        return self._emit1_evm("extcodesize", addr)

    def extcodehash(self, addr: Operand) -> IRVariable:
        return self._emit1_evm("extcodehash", addr)

    def returndatasize(self) -> IRVariable:
        return self._emit1_evm("returndatasize")

    # === Block Info ===
    def blockhash(self, block_num: Operand) -> IRVariable:
        return self._emit1_evm("blockhash", block_num)

    def coinbase(self) -> IRVariable:
        return self._emit1_evm("coinbase")

    def timestamp(self) -> IRVariable:
        return self._emit1_evm("timestamp")

    def number(self) -> IRVariable:
        return self._emit1_evm("number")

    def prevrandao(self) -> IRVariable:
        return self._emit1_evm("prevrandao")

    def difficulty(self) -> IRVariable:
        """Deprecated: use prevrandao."""
        return self._emit1_evm("difficulty")

    def gaslimit(self) -> IRVariable:
        return self._emit1_evm("gaslimit")

    def chainid(self) -> IRVariable:
        return self._emit1_evm("chainid")

    def basefee(self) -> IRVariable:
        return self._emit1_evm("basefee")

    def blobhash(self, index: Operand) -> IRVariable:
        return self._emit1_evm("blobhash", index)

    def blobbasefee(self) -> IRVariable:
        return self._emit1_evm("blobbasefee")

    # === Logging ===
    def log(self, topic_count: int, offset: Operand, size: Operand, *topics: Operand) -> None:
        """Emit log with N topics.

        Args:
            topic_count: Number of topics (0-4)
            offset: Memory offset of data
            size: Size of data to log
            topics: topic0, topic1, ... (in logical order)

        Matches EVM LOG opcode order: LOG(offset, size, topic0, ...).
        """
        # Venom IR format: log topic_count, topic_n-1, ..., topic0, size, offset
        # _emit_evm reverses args, so pass in reverse of target IR order
        self._emit_evm("log", offset, size, *topics, topic_count)

    # === Other ===
    def selfdestruct(self, addr: Operand) -> None:
        self._emit_evm("selfdestruct", addr)

    def nop(self) -> None:
        """No operation. Placeholder instruction. (IR-specific)"""
        self._emit("nop")

    # === Helpers (IR-specific) ===
    def assign(self, val: Operand) -> IRVariable:
        """Copy value to new variable (SSA phi-like)."""
        return self._emit1("assign", val)

    def assign_to(self, val: Operand, target: IRVariable) -> None:
        """Assign value to existing variable (for loop counters etc)."""
        self._current_bb.append_instruction("assign", val, ret=target)

    def literal(self, val: int) -> IRLiteral:
        """Create literal operand (convenience, can also just pass int)."""
        return IRLiteral(val)

    def label(self, name: str, is_symbol: bool = False) -> IRLabel:
        """Create a label."""
        return IRLabel(name, is_symbol)

    def select(self, cond: Operand, true_val: Operand, false_val: Operand) -> IRVariable:
        """
        Conditional selection: returns true_val if cond is nonzero, else false_val.

        Equivalent to: cond ? true_val : false_val

        Uses: xor(b, mul(cond, xor(a, b)))
        Requires cond to be exactly 0 or 1 (which Vyper comparisons guarantee).
        """
        diff = self.xor(true_val, false_val)
        scaled = self.mul(cond, diff)
        return self.xor(false_val, scaled)

    # === Source Tracking ===
    @contextmanager
    def source_context(self, ast_node):
        """Track source location for error messages.

        Usage:
            with b.source_context(node):
                b.add(x, y)  # Instructions get source info
        """
        self.fn.push_source(ast_node)
        try:
            yield
        finally:
            self.fn.pop_source()

    @contextmanager
    def error_context(self, error_msg: str):
        """Track error message for source map generation.

        Usage:
            with b.error_context("safeadd"):
                b.assert_(ok)  # Instruction gets error_msg
        """
        self.fn.push_error_msg(error_msg)
        try:
            yield
        finally:
            self.fn.pop_error_msg()

    # === Internal Implementation ===
    def _emit(self, opcode: str, *args: Operand) -> None:
        """Emit instruction with no output. Args passed directly to IR."""
        self._current_bb.append_instruction(opcode, *args)

    def _emit1(self, opcode: str, *args: Operand) -> IRVariable:
        """Emit instruction with output. Args passed directly to IR."""
        return self._current_bb.append_instruction1(opcode, *args)

    def _emit_evm(self, opcode: str, *args: Operand) -> None:
        """Emit EVM instruction. Args in semantic order, reversed for IR stack order."""
        self._current_bb.append_instruction(opcode, *reversed(args))

    def _emit1_evm(self, opcode: str, *args: Operand) -> IRVariable:
        """Emit EVM instruction with output. Args in semantic order, reversed for IR."""
        return self._current_bb.append_instruction1(opcode, *reversed(args))
