# Redundant Memory Copy Forwarding Simplification

## Purpose

The pass removes a staging memory copy when every relevant read of the fresh
destination can instead read the original source without changing observable
behavior.

```text
%tmp = alloca N
mcopy %tmp, %src, N
... read from %tmp + offset ...
```

becomes:

```text
%tmp = alloca N
... read from %src + offset ...
```

The simplification reduces the proof surface of this transformation. The pass
now changes only the memory-read operands that need forwarding and deletes the
staging `mcopy`. It does not rewrite the destination's alias graph.

## Previous Shape

The earlier implementation could rewrite intermediate aliases derived from the
destination. That required the pass to reason about:

- Mutating `assign`, pointer arithmetic, and `phi` results.
- Dominance of the source at each rewritten alias definition.
- Phi-edge placement and control-flow-specific availability.
- The interaction between rewritten aliases and their other users.
- Whether a partial rewrite left any observable destination value behind.

Those concerns were coupled. A change to alias handling could affect dominance,
control flow, pointer observability, and memory safety at the same time.

## Simplified Shape

The pass now follows four explicit stages.

### 1. Establish a candidate

The candidate must be a bounded `mcopy` into a fixed region of a static local
allocation. The source must be either:

- A fixed region of a tracked static local allocation.
- An exclusively resolved readonly internal memory parameter.

Dynamic destination allocations, unknown local source roots, overlapping
source and destination regions, and copies larger than the policy limit are
rejected.

### 2. Classify every destination use

Aliases that point into the copied destination segment may be used only for:

- Pointer derivations already understood by `BasePtrAnalysis`.
- Memory-read address operands that refer to the copied segment.

Every other use of those aliases rejects the candidate. Reads through the
allocation root that are proved not to touch the copied segment remain
unchanged. In particular, a pointer used as a return size, log topic, stored
value, call argument, or other scalar is observable after memory concretization
and cannot be rewritten safely.

The plan records only direct read-site rewrites:

```text
(instruction, address operand index, offset within copied segment)
```

No alias-producing instruction is modified.

### 3. Prove memory stability

Before applying a plan, the pass uses MemSSA to prove that:

- The staged destination is not clobbered between the copy and any forwarded
  read.
- A tracked local source region is not clobbered between the copy and those
  reads.
- A readonly parameter source has no intervening unknown-base write that could
  modify caller-owned memory.
- Every planned read has a corresponding MemSSA use, so a missing analysis fact
  cannot silently look like "no clobber."

### 4. Rewrite only the reads

For each accepted read, the pass substitutes `%src + offset` into the read's
address operand. A nonzero offset is materialized immediately before that use.
The staging `mcopy` is then removed and all affected analyses are invalidated.

The pass applies one plan per analysis rebuild. This is less efficient than
batching, but keeps each proof independent of mutations made by another plan.

## Dynamic Read Bounds

A dynamic-size read is forwarded only when its maximum reachable size is
proved. The proof comes from either:

- `memory_read_max_size` metadata supplied by typed code generation.
- `VariableRangeAnalysis` when no frontend bound is available.

The proven maximum is used to check that the entire possible read is contained
within the staged segment. An unbounded dynamic read is rejected.

`memory_read_max_size` is path-sensitive. It describes the maximum size on an
execution that reaches the operation after its runtime guards. Constant
propagation may leave a larger literal in an unreachable, reverting path, so
the metadata is not required to be greater than every literal remaining in the
IR. When the size operand is already literal, the pass uses that exact literal
and therefore still rejects an oversized read.

The metadata is preserved by instruction copies and function inlining, and is
cleared when an instruction is changed to an opcode for which the bound is no
longer valid.

## Parameter Provenance

Readonly memory parameter reasoning was consolidated into
`MemoryParamRootResolver`. A single recursive result carries:

```text
ParamRoots(roots, exclusive)
```

- `roots` is the may-set of parameter indexes that can reach a value. It is
  used by readonly-argument inference.
- `exclusive` is true only when every reaching definition is composed solely
  from accepted parameter, `assign`, or `phi` edges. It is used when forwarding
  needs proof that no local or unknown root can reach the source.

All definitions are composed, including multiple definitions in pre-SSA input.
Cycles, literals, arbitrary producers, pointer arithmetic, and mixed roots fail
closed for the exclusive query.

This replaces separate provenance walks whose answers could drift apart.

## Base Pointer Safety

`BasePtrAnalysis` now treats pre-SSA facts monotonically and records untracked
roots for non-pointer or unsupported reassignments. For example, a variable
that first aliases `%tmp` and is later assigned a literal cannot be accepted as
a clean alias of `%tmp`.

The forwarding pass also rejects a tracked source allocation when any alias of
its pointer is used outside a recognized memory address position. This prevents
forwarding from extending the source allocation's lifetime and changing a
concrete pointer value observed as data.

## Complexity Removed

The simplification removed or replaced:

- Alias-definition rewrites.
- Phi-specific rewrite handling.
- Source-dominance checks for rewritten alias definitions.
- Coupled alias and direct-use rewrite plans.
- The assumption that a whole-allocation staging copy alone bounds every
  dynamic read.
- Separate readonly-root resolution algorithms.
- Optimistic handling of unsupported pre-SSA reassignments.

The resulting pass is conservative by design. Unsupported cases retain the
original `mcopy` rather than expanding the transformation's proof obligations.

## Intentional Limits

- Copy size is capped at 4096 bytes.
- A tracked source allocation is capped at 4096 bytes.
- Dynamic local source and destination allocations are rejected.
- Destination and source pointer escapes are rejected.
- `return` uses are not forwarded.
- Unknown offsets or unknown dynamic-size bounds are rejected.

The size limits protect memory-layout quality because the pass runs before
concrete allocation and does not yet have a lifetime or frame high-water cost
model.

## Review Map

The implementation can be reviewed in the same order as the proof:

1. `_candidate` establishes source, destination, allocation, and size
   eligibility.
2. `_build_forward_plan` proves that every destination use has an allowed
   shape.
3. `_is_allowed_memory_read_use` checks dominance, address position, aliasing,
   and bounds.
4. `_has_location_clobber_between` and
   `_has_unresolved_param_clobber_between` establish memory stability.
5. `_apply_forward_plan` performs only direct address substitutions.
6. `MemoryParamRootResolver` supplies shared interprocedural provenance facts.

## Validation

The simplified implementation and its follow-up corrections were checked with:

- Repository lint, formatting, and mypy.
- The full compiler unit suite.
- Focused Venom analysis, inliner, memory-location, and forwarding tests.
- Functional slice, bytes, concat, contract creation, and calling-convention
  suites.
- The full experimental O2/Prague/revm test configuration: 12,328 passed, 6
  skipped, and 50 expected failures.
- Snekmate gas measurement: 815 measured cases with no gas or status changes.
- The complete GitHub Actions matrix, including CodeQL and all experimental
  optimization levels.

The primary architectural simplification is commit `843babed6`. Follow-up
commits `290bf8fe1` and `e5acd248c` corrected the raw blueprint bound and the
path-sensitive metadata assertion respectively.
