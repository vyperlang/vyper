# Introduction to Vyper's IR

VyperIR is Vyper's current intermediate representation. It is used as "a high level assembly". While VyperIR could theoretically compile to any backend which shares enough intrinsics with the EVM, this document assumes the reader has a good understanding of the EVM's execution model.

# Structure of VyperIR

The grammar of VyperIR is `(s_expr)` where `s_expr` is one of

```
s_expr :=
  INT_LITERAL |
  IDENTIFIER |
  EVM_OPCODE *s_expr |
  PSEUDO_OPCODE *s_expr |
  "with" IDENTIFIER s_expr s_expr |
  "set" IDENTIFIER s_expr |
  "seq" *s_expr |
  "if" s_expr s_expr [s_expr] |
  "repeat" s_expr s_expr s_expr s_expr s_expr
```

An IR expression has a "valency" of 1 or 0. Valency of 1 means that it returns a stack item, valency of 0 means that it does not.

Vyper's current implementation of IR can be referenced, mainly in [vyper/codegen/ir\_node.py](../codegen/ir_node.py) (which describes the internal API for constructing IR) and in [vyper/ir/compile\_ir.py](../ir/compile_ir.py) (which describes how IR is compiled to assembly and then to bytecode). Vyper's IR output can be inspected by compiling a Vyper contract with `vyper -f ir <contract.vy>`. Vyper also comes with a tool, `vyper-ir` which can be used to compile IR (in Lisp syntax) directly to assembly or EVM bytecode.

In the following examples, `_sym_<label>` is a location in code which will be resolved as the last step during conversion to opcodes. If it occurs before a `JUMPDEST`, it is merely a marker in the code (and gets omitted in the bytecode). If it occurs anywhere else, it translates to `PUSH2 <location of jumpdest>`.

### INT\_LITERAL

An int literal compiles to `PUSH<N> int_literal`. It has a valency of 1.

Example:
```
(1)
```

Could compile to `PUSH1 1`

### IDENTIFIER

An identifier could either be a label, or a variable defined in a with-expression.

Example:
```
(x)
```
Resolves to the value of x. (See `WITH`)

Example:
```
(_sym_foo)
```
Resolves to an integer whose value is the location of `(label foo)` in the emitted bytecode.

NOTE: This will probably be replaced in the future by a specialized pseudo-opcode, `(literal_label)`, which will push a code location onto the stack (for consumption by JUMP or JUMPI).

### EVM\_OPCODE

An EVM opcode pushes its arguments onto the stack by evaluating them in reverse, recursively.

Example:
```
(sstore 1 2)
```

Could compile to:
```
PUSH1 2 PUSH1 1 SSTORE
```

Example (note the order of evaluation):
```
(sstore (sload 0) (call gas address 0 0 0 0))
```

Could compile to:
```
PUSH1 0 DUP1 DUP1 DUP1 DUP1 ADDRESS GAS CALL
PUSH1 0 SLOAD
SSTORE
```

### WITH

A with expression defines a scope and a variable for use in that scope. Its valency is defined to be the valency of its body. For instance,
```
(with x 1
  (return 0 x))
```

Could compile to `PUSH1 1 PUSH1 0 RETURN`, and has a valency of 0 (as `RETURN` does not return a stack item).

The liveness of a variable is restricted to the scope of the with expression. In other words, if variables are still live on the stack at the scope exit they should be popped.

Shadowing is allowed, for instance the expression

```
(with x 1
 (with y 2
  (with x y
   x)))
```
will evaluate to `2`.

### SET

A set expression modifies the value of a variable. Its valency is 0.

Example:
```
(with x 1
  (with y (add x 2)
    (seq
      (set x (add x y))
      (return x y))))
```
Could compile to:
```
PUSH1 1           // with x 1
PUSH1 2 DUP2 ADD  // with y (add x 2)
DUP1 DUP3 ADD     // add x y
SWAP2 POP         // set x
DUP1 DUP3 RETURN  // return x y
POP POP           // POP y, POP x
```

### SEQ

A seq expression ties together a sequence of IR operations. Its valency is defined as the valency of the last element in the sequence. If any of the intervening operations (besides the last one) has nonzero valency, the output is POPped. (Its output can be used as an argument to another expression.)

Example:
```
(seq 1 2 3)
```

Could compile to
```
PUSH1 1 POP
PUSH1 2 POP
PUSH1 3
```

Example:
```
(seq
 (call gas address 1 2 3 4 5)
 (call gas caller 1 2 3 4 5)
 )
```

Could compile to

```
PUSH1 5 PUSH1 4 PUSH1 3 PUSH1 2 PUSH1 1 ADDRESS GAS CALL POP
PUSH1 5 PUSH1 4 PUSH1 3 PUSH1 2 PUSH1 1 CALLER GAS CALL
```

### GOTO

jump to a label. VyperIR has two forms of goto, simple goto and goto with args. The latter form is useful for implementing subroutines.

Example:
```
(goto foo)
```

Could compile to:

```
_sym_foo JUMP
```

Example:
```
(goto foo 1 2 3)
```

Could compile to:
```
PUSH1 3 PUSH1 2 PUSH1 1 _sym_foo JUMP
```

### LABEL

(label foo) defines a label.

Example:
```
(label foo)
```

Could compile to:
```
_sym_foo JUMPDEST
```

### UNIQUE\_SYMBOL

`(unique_symbol l)` defines a "unique symbol". These are generated to help catch front-end bugs involving multiple execution of side-effects (which should be only executed once). They can be ignored, or to be strict, any backend should enforce that each `unique_symbol` only appears one time in the code.

### IF\_STMT

Branching statements. There are two forms, if with a single branch, and if with two branches.

Example:
```
(if 1 stop)
```

Could compile to:
```
PUSH1 1 ISZERO PUSH2 _sym_join1 JUMPI STOP _sym_join1 JUMPDEST
```

Example:
```
(if (lt calldatasize 4) (revert 0 0) (stop))
```

Could compile to:
```
PUSH1 4 CALLDATASIZE LT ISZERO _sym_fls JUMPI
_sym_tru JUMPDEST PUSH1 0 PUSH1 0 REVERT
_sym_fls JUMPDEST STOP
```

### REPEAT

`repeat <loop_varname> <start> <rounds> <rounds_bound> <body>` is a for loop. It creates a stack item whose starting value is `<start>`, and which can be accessed with `<loop_varname>`, repeating the body and incrementing the loop variable `<rounds>` times, i.e. until `<loop_varname> == <start> + <rounds>`. `<rounds_bound>` is provided as a compile-time constant; at the entrance to the loop, a runtime check is performed: `rounds <= rounds_bound`.

Example:
```
(with x 0 (repeat 320 1 8 (set x (add x (mload 320)))) // sum the numbers 1 through 7
```

Could compile to:
```
PUSH1 0                                        // with x 0
PUSH1 1 PUSH1 320 MSTORE                       // initialize loop variable
_sym_loop_start JUMPDEST                       // loop entrance
PUSH1 320 MLOAD PUSH1 8 EQ _sym_loop_end JUMPI // check loop condition
PUSH1 320 MLOAD DUP2 ADD SWAP1 POP             // set x (add x (mload 320))
PUSH1 320 MLOAD PUSH1 1 ADD PUSH1 320 MSTORE   // (mstore 320 (add 1 (mload 320))
_sym_loop_start JUMP
```

NOTE: in the future, the loop variable could change to be a stack variable instead of stored in memory. In other words, repeat may only take three arguments <start> <end> <body> instead of the current four.

### BREAK

Break out of a loop. This cleans up any loop state off the stack and jumps to the loop exit. Equivalent to
```
(seq
 (cleanup_repeat)
 (goto loop_exit))
```

### CLEANUP\_REPEAT

Similar to `break`, this cleans up any loop state off the stack, but does not jump to the loop exit. Usually used right before jumping out of an internal function.

(Note that depending on the implementation of `repeat`, there may not actually be anything to clean up, in which case this is a no-op.)

### CONTINUE

Increment the loop counter and continue to the loop entrance

### PASS

A no-op.

### PSEUDO\_OPCODE

A pseudo opcode behaves similarly to an EVM opcode but it is not actually an EVM opcode.

A full list of pseudo-opcodes is as follows.

#### ASSERT

`(assert condition)`

Equivalent to `(if (iszero (condition)) (revert 0 0))`.

### ASSERT\_UNREACHABLE

`(assert_unreachable condition)`

Equivalent to `(if (iszero (condition)) (invalid))`

### GE/LE/SGE/SLE

Compare or equal

| | | |
|---|---|---|
| `(ge x y)` | is equivalent to | `(iszero (lt x y))` |
| `(le x y)` | is equivalent to | `(iszero (gt x y))` |
| `(sge x y)` | is equivalent to | `(iszero (slt x y))` |
| `(sle x y)` | is equivalent to | `(iszero (sgt x y))` |


### NE

`(ne x y)` is equivalent to `(iszero (eq x y))`

### SELECT
`(select cond x y)` is similar to `(if cond x y)` but it may evaluate both branches. Whether or not both branches are taken is unspecified. If `cond` is not in `(0, 1)` the behavior is undefined. It is analogous to LLVM `select` and is intended to compile to branchless code.


### SHA3\_32, SHA3\_64

sha3\_32 and sha3\_64 are shortcuts to access the EVM sha3 opcode. They copy the inputs to reserved memory space and then sha3 the input.

`(sha3_32 x)` is equivalent to `(seq (mstore FREE_VAR_SPACE x) (sha3 FREE_VAR_SPACE 32))`, and `(sha3_64 x y)` is equivalent to `(seq (mstore FREE_VAR_SPACE2 y) (mstore FREE_VAR_SPACE x) (sha3 FREE_VAR_SPACE 64))`, where `FREE_VAR_SPACE` and `FREE_VAR_SPACE2` are memory locations reserved by the vyper compiler for scratch space. Their values are currently 0 and 32.


### CEIL32

ceil32 rounds its input up to the nearest multiple of 32. Its behavior is equivalent to the python function
```python
# Returns lowest multiple of 32 >= the input
def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)
```

In IR, `(ceil32 x)` is equivalent to `(and (add x 31) (not 31))`
