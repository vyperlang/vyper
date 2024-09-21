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
