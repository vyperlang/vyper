## Venom - An Intermediate representation language for Vyper

### Introduction

Venom serves as the next-gen intermediate representation language specifically tailored for use with the Vyper smart contract compiler. Drawing inspiration from LLVM IR, Venom has been adapted to be simpler, and to be architected towards emitting code for stack-based virtual machines. Designed with a Single Static Assignment (SSA) form, Venom allows for sophisticated analysis and optimizations, while accommodating the idiosyncrasies of the EVM architecture.

### Venom Form

In Venom, values are denoted as strings commencing with the `'%'` character, referred to as variables. Variables can only be assigned to at declaration (they remain immutable post-assignment). Constants are represented as decimal numbers (hexadecimal may be added in the future).

Reserved words include all the instruction opcodes and `'IRFunction'`, `'param'`, `'dbname'` and `'db'`.

Any content following the `';'` character until the line end is treated as a comment.

For instance, an example of incrementing a variable by one is as follows:

```llvm
%sum = add %x, 1  ; Add one to x
```

Each instruction is identified by its opcode and a list of input operands. In cases where an instruction produces a result, it is stored in a new variable, as indicated on the left side of the assignment character.

Code is organized into non-branching instruction blocks, known as _"Basic Blocks"_. Each basic block is defined by a label and contains its set of instructions. The final instruction of a basic block should either be a terminating instruction or a jump (conditional or unconditional) to other block(s).

Basic blocks are grouped into _functions_ that are named and dictate the first block to execute.

Venom employs two scopes: global and function level.

### Example code

```llvm
function global {
    global:
        %1 = calldataload 0
        %2 = shr 224, %1
        jmp @selector_bucket_0

    selector_bucket_0:
        %3 = xor %2, 1579456981
        %4 = iszero %3
        jnz %4, @true, @false

    false:
        jmp @fallback

    true:
        %5 = callvalue
        %6 = calldatasize
        %7 = lt 164, %6
        %8 = or %7, %5
        %9 = iszero %8
        assert %9
        stop

    fallback:
        revert 0, 0
}

data readonly {}
```

### Grammar

To see a definition of grammar see the [venom parser](./parser.py)

### Compiling Venom

Vyper ships with a venom compiler which compiles venom code to bytecode directly. It can be run by running `venom`, which is installed as a standalone binary when `vyper` is installed via `pip`.

## Implementation

In the current implementation the compiler was extended to incorporate a new pass responsible for translating the original s-expr based IR into Venom. Subsequently, the generated Venom code undergoes processing by the actual Venom compiler, ultimately converting it to assembly code. That final assembly code is then passed to the original assembler of Vyper to produce the executable bytecode.

Currently there is no implementation of the text format (that is, there is no front-end), although this is planned. At this time, Venom IR can only be constructed programmatically.

## Architecture

The Venom implementation is composed of several distinct passes that iteratively transform and optimize the Venom IR code until it reaches the assembly emitter, which produces the stack-based EVM assembly. The compiler is designed to be more-or-less pluggable, so passes can be written without too much knowledge of or dependency on other passes.

These passes encompass generic transformations that streamline the code (such as dead code elimination and normalization), as well as those generating supplementary information about the code, like liveness analysis and control-flow graph (CFG) construction. Some passes may rely on the output of others, requiring a specific execution order. For instance, the code emitter expects the execution of a normalization pass preceding it, and this normalization pass, in turn, requires the augmentation of the Venom IR with code flow information.

The primary categorization of pass types are:

- Transformation passes
- Analysis/augmentation passes
- Optimization passes

## Currently implemented passes

The Venom compiler currently implements the following passes.

### Control Flow Graph calculation

The compiler generates a fundamental data structure known as the Control Flow Graph (CFG). This graph illustrates the interconnections between basic blocks, serving as a foundational data structure upon which many subsequent passes depend.

### Data Flow Graph calculation

To enable the compiler to analyze the movement of data through the code during execution, a specialized graph, the Dataflow Graph (DFG), is generated. The compiler inspects the code, determining where each variable is defined (in one location) and all the places where it is utilized.

### Dataflow Transformation

This pass depends on the DFG construction, and reorders variable declarations to try to reduce stack traffic during instruction selection.

### Liveness analysis

This pass conducts a dataflow analysis, utilizing information from previous passes to identify variables that are live at each instruction in the Venom IR code. A variable is deemed live at a particular instruction if it holds a value necessary for future operations. Variables only alive for their assignment instructions are identified here and then eliminated by the dead code elimination pass.

### Dead code elimination

This pass eliminates all basic blocks that are not reachable from any other basic block, leveraging the CFG.

### Normalization

A Venom program may feature basic blocks with multiple CFG inputs and outputs. This currently can occur when multiple blocks conditionally direct control to the same target basic block. We define a Venom IR as "normalized" when it contains no basic blocks that have multiple inputs and outputs. The normalization pass is responsible for converting any Venom IR program to its normalized form. EVM assembly emission operates solely on normalized Venom programs, because the stack layout is not well defined for non-normalized basic blocks.

### Code emission

This final pass of the compiler aims to emit EVM assembly recognized by Vyper's assembler. It calculates the desired stack layout for every basic block, schedules items on the stack and selects instructions. It ensures that deploy code, runtime code, and data segments are arranged according to the assembler's expectations.

## Future planned passes

A number of passes that are planned to be implemented, or are implemented for immediately after the initial PR merge are below.

### Constant folding

### Instruction combination

### Dead store elimination

### Scalar evolution

### Loop invariant code motion

### Loop unrolling

### Code sinking

### Expression reassociation

### Stack to mem

### Mem to stack

### Function inlining

### Load-store elimination

---

## Structure of a venom program

### IRContext
An `IRContext` consists of multiple `IRFunctions`, with one designated as the main entry point of the program.
Additionally, the `IRContext` maintains its own representation of the data segment.

### IRFunction
An `IRFunction` is composed of a name and multiple `IRBasicBlocks`, with one marked as the entry point to the function.

### IRBasicBlock
An `IRBasicBlock` contains a label and a sequence of `IRInstructions`.
Each `IRBasicBlock` has a single entry point and exit point.
The exit point must be one of the following terminator instructions:
- `jmp` 
- `djmp` 
- `jnz` 
- `ret` 
- `return` 
- `stop` 
- `exit`

Normalized basic blocks cannot have multiple predecessors and successors. It has either one (or zero) predecessors and potentially multiple successors or vice versa.

### IRInstruction
An `IRInstruction` consists of an opcode, a list of operands, and an optional return value.
An operand can be a label, a variable, or a literal.

By convention, variables have a `%-` prefix, e.g. `%1` is a valid variable. However, the prefix is not required.

## Instructions
To enable Venom IR in Vyper, use the `--experimental-codegen` CLI flag or its alias `--venom`, or the corresponding pragma statements (e.g. `#pragma experimental-codegen`). To view the Venom IR output, use `-f bb_runtime` for the runtime code, or `-f bb` to see the deploy code. To get a dot file (for use e.g. with `xdot -`), use `-f cfg` or `-f cfg_runtime`.

Assembly can be inspected with `-f asm`, whereas an opcode view of the final bytecode can be seen with `-f opcodes` or `-f opcodes_runtime`, respectively.

### Special instructions

- `invoke`
  - ```
    invoke offset, @label
    ```
  - Causes control flow to jump to a function denoted by the `label`.
  - Return values are passed in the return buffer at the `offset` address.
  - Used for internal functions.
  - Effectively translates to `JUMP`, and marks the call site as a valid return destination (for callee to jump back to) by `JUMPDEST`.
- `alloca`
  - ```
    %out = alloca size, offset, id
    ```
  - Allocates memory of a given `size` at a given `offset` in memory.
  - The `id` argument is there to help debugging translation into venom
  - The output is the offset value itself.
  - Because the SSA form does not allow changing values of registers, handling mutable variables can be tricky. The `alloca` instruction is meant to simplify that.
  
- `palloca`
  - ```
    %out = palloca size, offset, id
    ```
  - Like the `alloca` instruction but only used for parameters of internal functions which are passed by memory.
- `calloca`
  - ```
    out = calloca size, offset, id, <callsite label>
    ```
  - Similar to the `calloca` instruction but only used for parameters of internal functions which are passed by memory. Used at the call-site of a call.
- `iload`
  - ```
    %out = iload offset
    ```
  - Loads value at an immutable section of memory denoted by `offset` into `out` variable.
  - The operand can be either a literal, which is a statically computed offset, or a variable.
  - Essentially translates to `MLOAD` on an immutable section of memory. So, for example 
     ```
     %op = 12
     %out = iload %op
    ```
    could compile into `PUSH1 12 _mem_deploy_end ADD MLOAD`.
  - When `offset` is a literal the location is computed statically during compilation from assembly to bytecode.
- `istore`
  - ```
    istore offset value
    ```
  - Represents a store into immutable section of memory.
  - Like in `iload`, the offset operand can be a literal.
  - Essentially translates to `MSTORE` on an immutable section of memory. For example,
     ```
     %op = 12
     istore 24 %op
     ```
     could compile to 
     `PUSH1 12 PUSH1 24 _mem_deploy_end ADD MSTORE`.
- `phi`
  - ```
    %out = phi @label_a, %var_a, @label_b, %var_b
    ```
  - Because in SSA form each variable is assigned just once, it is tricky to handle that variables may be assigned to something different based on which program path was taken.
  - Therefore, we use `phi` instructions. They are are magic instructions, used in basic blocks where the control flow path merges.
  - In this example, essentially the `%out` variable is set to `%var_a` if the program entered the current block from `@label_a` or to `%var_b` when it went through `@label_b`. Note that `%var_a%` must be defined in the `@label_a` block and `%var_b` must be defined in the `@label_b` block.
- `offset`
  - ```
    %ret = offset @label, op
    ```
  - Statically compute offset before compiling into bytecode. Useful for `mstore`, `mload` and such.
  - Basically `@label` + `op`.
  - The `asm` output could show something like `_OFST _sym_<op> label`.
- `param`
  - ```
    %out = param
    ```
  - The `param` instruction is used to represent function arguments passed by the stack.
  - We assume the argument is on the stack and the `param` instruction is used to ensure we represent the argument by the `out` variable.
- `store`
  - ```
    %out = op
    ```
  - Store variable value or literal into `out` variable.
- `dbname`
  - ```
    dbname label
    ```
  - Mark memory with a `label` in the data segment so it can be referenced.
- `db`
  - ```
    db data
    ```
  - Store `data` into data segment.
- `dloadbytes`
  - Alias for `codecopy` for legacy reasons. May be removed in future versions.
  - Translates to `CODECOPY`.
- `ret`
  - ```
    ret op
    ```
  - Represents return from an internal call.
  - Jumps to a location given by `op`.
  - If `op` is a label it can effectively translate into `op JUMP`.
- `exit`
  - ```
    exit
    ```
  - Similar to `stop`, but used for constructor exit. The assembler is expected to jump to a special initcode sequence which returns the runtime code.
  - Might translate to something like  `_sym__ctor_exit JUMP`.
- `sha3_64`
  - ```
    %out = sha3_64 x, y
    ```
  - Shortcut to access the `SHA3` EVM opcode where `%out` is the result.
  - Essentially translates to
    ```
    PUSH y PUSH FREE_VAR_SPACE MSTORE
    PUSH x PUSH FREE_VAR_SPACE2 MSTORE
    PUSH 64 PUSH FREE_VAR_SPACE SHA3
    ```
    where `FREE_VAR_SPACE` and `FREE_VAR_SPACE2` are locations reserved by the compiler, set to 0 and 32 respectively.

- `assert`
  - ```
    assert op
    ```
  - Assert that `op` is zero. If it is not, revert.
  - Calls that terminate this way receive a gas refund.
  - For example
    ``` 
    %op = 13
    assert %op
    ```
    could compile to
    `PUSH1 13 ISZERO _sym___revert JUMPI`.
- `assert_unreachable`
  - ```
    assert_unreachable op
    ```
  - Check that `op` is zero. If it is not, terminate with `0xFE` ("INVALID" opcode).
  - Calls that end this way do not receive a gas refund.
  - Could translate to `op reachable JUMPI INVALID reachable JUMPDEST`.
  - For example
    ``` 
    %op = 13
    assert_unreachable %op
    ```
    could compile to
    ```
    PUSH1 13 _sym_reachable1 JUMPI
    INVALID
    _sym_reachable1 JUMPDEST
    ```
- `log`
  - ```
    log offset, size, [topic] * topic_count , topic_count
    ```
  - Corresponds to the `LOGX` instruction in EVM.
  - Depending on the `topic_count` value (which can be only from 0 to 4) translates to `LOG0` ... `LOG4`.
  - The rest of the operands correspond to the `LOGX` instructions.
  - For example
    ```
    log %53, 32, 64, %56, 2
    ```
    could translate to:
    ```
    %56, 64, 32, %53 LOG2
    ```
- `nop`
  - ```
    nop
    ```
  - No operation, does nothing.
- `offset`
  - ```
    %2 = offset %1 @label1
  - Similar to `add`, but takes a label as the second argument. If the first argument is a literal, the addition will get optimized at assembly time.

### Jump instructions

- `jmp`
  - ```
    jmp @label
    ```
  - Unconditional jump to code denoted by given `label`.
  - Translates to `label JUMP`.
- `jnz`
   - ```
     jnz op, @label1, @label2
     ```
  - A conditional jump depending on the value of `op`.
  - Jumps to `label2` when `op` is not zero, otherwise jumps to `label1`.
  - For example
    ```
    %op = 15
    jnz %op, @label1, @label2
    ```
    could translate to: `PUSH1 15 label2 JUMPI label1 JUMP`.
- `djmp`
  - ```
    djmp %var, @label1, @label2, ..., @labeln
    ```
  - Dynamic jump to an address specified by the variable operand, constrained to the provided labels.
  - Accepts a variable number of labels.
  - The target is not a fixed label but rather a value stored in a variable, making the jump dynamic.
  - The jump target can be any of the provided labels.
  - Translates to `JUMP`.

### EVM instructions

The following instructions map one-to-one with [EVM instructions](https://www.evm.codes/).
Operands correspond to stack inputs in the same order. Stack outputs are the instruction's output.
Instructions have the same effects.
- `return`
- `revert`
- `coinbase`
- `calldatasize`
- `calldatacopy`
- `mcopy`
- `calldataload`
- `gas`
- `gasprice`
- `gaslimit`
- `chainid`
- `address`
- `origin`
- `number`
- `extcodesize`
- `extcodehash`
- `extcodecopy`
- `returndatasize`
- `returndatacopy`
- `callvalue`
- `selfbalance`
- `sload`
- `sstore`
- `mload`
- `mstore`
- `tload`
- `tstore`
- `timestamp`
- `caller`
- `blockhash`
- `selfdestruct`
- `signextend`
- `stop`
- `shr`
- `shl`
- `sar`
- `and`
- `xor`
- `or`
- `add`
- `sub`
- `mul`
- `div`
- `smul`
- `sdiv`
- `mod`
- `smod`
- `exp`
- `addmod`
- `mulmod`
- `eq`
- `iszero`
- `not`
- `lt`
- `gt`
- `slt`
- `sgt`
- `create`
- `create2`
- `msize`
- `balance`
- `call`
- `staticcall`
- `delegatecall`
- `codesize`
- `basefee`
- `blobhash`
- `blobbasefee`
- `prevrandao`
- `difficulty`
- `invalid`
- `sha3`
