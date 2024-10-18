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
IRFunction: global

global:
    %1 = calldataload 0
    %2 = shr 224, %1
    jmp label %selector_bucket_0

selector_bucket_0:
    %3 = xor %2, 1579456981
    %4 = iszero %3
    jnz label %1, label %2, %4

1:  IN=[selector_bucket_0] OUT=[9]
    jmp label %fallback

2:
    %5 = callvalue
    %6 = calldatasize
    %7 = lt %6, 164
    %8 = or %5, %7
    %9 = iszero %8
    assert %9
    stop

fallback:
    revert 0, 0
```

### Grammar

Below is a (not-so-complete) grammar to describe the text format of Venom IR:

```llvm
program              ::= function_declaration*

function_declaration ::= "IRFunction:" identifier input_list? output_list? "=>" block

input_list           ::= "IN=" "[" (identifier ("," identifier)*)? "]"
output_list          ::= "OUT=" "[" (identifier ("," identifier)*)? "]"

block                ::= label ":" input_list? output_list? "=>{" operation* "}"

operation            ::= "%" identifier "=" opcode operand ("," operand)*
                     |  opcode operand ("," operand)*

opcode               ::= "calldataload" | "shr" | "shl" | "and" |  "add" | "codecopy" | "mload" | "jmp" | "xor" | "iszero" |  "jnz" | "label" | "lt" | "or" | "assert" | "callvalue" | "calldatasize" | "alloca" | "calldatacopy" |  "invoke" | "gt" | ...

operand              ::= "%" identifier | label | integer | "label" "%" identifier
label                ::= "%" identifier

identifier           ::= [a-zA-Z_][a-zA-Z0-9_]*
integer              ::= [0-9]+
```

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

Normalized basic blocks can not have multiple predecessors and successors. It has either one (or zero) predecessors and potentially multiple successors or vice versa.

### IRInstruction
An `IRInstruction` consists of an opcode, a list of operands, and an optional return value.
An operand can be a label, a variable, or a literal.

## Instructions

### Special instructions

- `invoke`
  - Cause control flow to jump to a function denoted by the label.
  - Return values are passed in the return buffer at the offset address.
  - Practically only used for internal functions.
  - Effectively translates to `JUMP` and therefore changes the program counter value.
  - ```
    invoke offset, label
    ```
- `alloca`
  - Allocates memory of a given size at a given offset in memory.
  - The output is the offset itself.
  - Because the SSA form does not allow changing values of registers, handling mutable variables can be tricky. The `alloca` instruction is meant to simplify that.
  - ```
    out = alloca size, offset
    ```
- `palloca`
  - Like the `alloca` instruction but only used for parameters of internal functions.
  - ```
    out = palloca size, offset
    ```
- `iload`
  - Load value at immutable section of memory denoted by `offset` into `out` variable.
  - The operand can be either a literal, which is a statically computed offset, or a variable.
  - ```
    out = iload offset
    ```
- `istore`
  - The instruction represents a store into immutable section of memory.
  - Like in `iload`, the offset operand can be a literal.
  - ```
    istore offset value
    ```
- phi
  - label, variable, basic phi
  - ```
    %out = phi %61:2, label_a, %61, label %__main_entry
    ```
- `offset`
  - Statically compute offset. Useful for `mstore`, `mload` and such.
  - Basically `label` + `op`.
  - ```
    ret = offset label, op
    ```
- `param`
  - The `param` instruction is used to represent function arguments passed by the stack.
  - We assume the argument is on the stack and the `param` instruction is used to ensure we represent the argument by the `out` variable.
  - ```
    out = param
    ```
- `store`
  - Store variable value or literal into `out` variable.
  - ```
    out = op
    ```
- dbname
  - make and mark a data segment (one data segment in context - so maybe section it?) dunno
- db
  - db stores into the data segment some label? hmm
- dloadbytes
  - aparently the same `codecopy`-everything handled the same way. Maybe historical reasons?
- `ret`
  - Represents a return from an internal call.
  - Jumps to a location given by `op`, hence modifies the program counter.
  - ```
    ret op
    ```
- exit
  - similar like return, but jumps to one predetermined section.
  - Used for constrcutor exit? chec why in fallback
  - ```
    exit
    ```
- sha3_64
- `assert`
  - Assert that `op` is zero. If it is not, revert.
  - Calls that terminate this way do receive a gas refund.
  - ```
    assert op
    ```
- `assert_unreachable`
  - Check that `op` is zero. If it is not, terminate.
  - Calls that end this way do not receive a gas refund.
  - ```
    assert_unreachable op
    ```
- log
  - topic in 0 to 4 meant for logging, translates to EVM Log0..log4 instructions
  - ```
    log offset, size, {topic}max4 , topic_count
    ```
- `nop`
  - No operation, does nothing.
  - ```
    nop
    ```

### Jump instructions

- `jmp`
  - Unconditional jump to code denoted by given `label`.
  - Changes the program counter.
  - ```
    jmp label
    ```
- `jnz`
  - A conditional jump depending on `op` value.
  - Jumps to `label2` when `op` is not zero, otherwise jumps to `label1`.
  - Changes the program counter.
  - ```
    jnz label1, label2, op
    ```
- `djmp`
  - Dynamic jump to an address specified by the variable operand.
  - The target is not a fixed label but rather a value stored in a variable, making the jump dynamic.
  - Changes the program counter.
  - ```
    djmp var
    ```

### EVM instructions
The following instructions map one-to-one with [EVM instructions](https://www.evm.codes/).
Operands correspond to stack inputs in the same order. Stack outputs are instruction output.
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
---

### TODO
- Describe the architecture of analyses and passes a bit more. mention the distiction between analysis and pass (optimisation or transformation).
- mention how to compile into it , bb(deploy), bb_runtime
- perhaps add some flag to skip the store expansion pass? for readers of the code
- some of the evm opcodes are from older versions - should comment on that? instructions like difficulty that changed into prevrandao
- if it is meant for using venom, then i should mention api for passes and analyses - should i do that?
  - analysis by ir_analysis_cache - request, invalidate, force - type of analysis and additional params
  - pass - run_pass

Perhaps mention that functions:
- each function starts as if with empty stack
- alloca and palloca(interf) for some args
- param for args by stack

ask harry or someone:
- _mem_deploy_end is it immutable after that??
