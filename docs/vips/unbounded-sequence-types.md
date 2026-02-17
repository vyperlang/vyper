# Unbounded Sequence Types

## Introduction

### Parameters and arguments

Parameters are the inputs as defined by the function, arguments are the values or expressions effectively passed to the input:
```python
#       v parameter
def foo(x: uint256)...

#   v argument
foo(4)
```

### Bounded sequence types

We define bounded sequence types to be the types taking as type parameter their maximum length:

1. `Bytes[n]`
2. `String[n]`
3. `DynArray[T, n]`

Notably this list does not include fixed-size lists (`T[n]` where `T` is any type except `Bytes[n]`, `String[n]`, flag types), since there the `n` is not an upper bound, but the actual length of the sequence.

For bounded sequence types, variables with a smaller bound can be assigned to variables with a bigger bound:
```python
def foo() -> None:
	s1: String[10] = "Hi" # valid since "Hi" has 2 characters, so fits into "at most 10"
	s2: String[20] = s1 # valid since "at most 10" fits into "at most 20"
	s3: String[2]  = s1 # invalid since "at most 10" does not fit into "at most 2"
	return
```
In other words, for all `n1 <= n2`, `String[n1]` is a subtype of `String[n2]`: `String[n1] <: String[n2]`.


### Data locations

The EVM contains essentially 4 locations where data can be located:

1. Calldata
2. Memory
3. Transient storage
4. Storage

(There are also others like the stack and the contract bytecode itself, but those are not relevant for this discussion.)

Calldata contains the parameters to an external function, and is immutable.
Memory contains parameters to internal functions, as well as temporary variables (ones defined inside functions).
Transient storage and storage store persistent data, for example contract variables (which can be accessed with `self`).

Memory, while cheaper than storage, is not free.
The total cost depends on the highest index allocated, and is quadratic.
This means allocating more memory than needed can be _extremely_ expensive.

## Motivation

Currently, before a function's arguments are passed, memory is allocated to fit the expected type into memory.
If a function has a `String[1000]` as parameter, even if the argument is `String[10]`, we allocate the full 1000 chars worth of memory !

And of course you cannot pass a `String[11]` as an argument for a `String[10]` parameter, as that could break assumptions on the other end.

This leads to a dilemma: How big do I make that sequence type ?
1. If you make it too small, this heavily contrains users in what they can do
2. If you make it too big, the cost will get astronomical, even if the user calls the method with a small instance

This is a big limitation that Vyper has that Solidity doesn't, and stops us from implementing a lot of useful patterns, for example:
1. Multicall: A contract which calls the contracts as defined in its parameter, and aggregates the results.
2. Virtual Machine: Like a multicall, but the output of calling another contract's method can be used to decide which contract to call next, and with what arguments.
3. Forwarding parameters from one contract's method to another contract's method.

The goal of this proposal is thus to remove this dilemma, in the simplest and clearest manner.

## Overview

The idea is to add new types which represent sequences of any lengths, for example `String[INF]`:

```python
@external
def size(s: String[INF]) -> uint256:
	self.compute_size(s)

def compute_size(s: String[INF]) -> uint256:
    return len(s)
```

As you can see, this avoids the dilemma completely: the size of `s` will depend on what it is called with.

## Spec

### Front-end

Unbounded versions of bounded sequence types are added:
1. `String[INF]`
2. `Bytes[INF]`
3. `DynArray[T, INF]`

(optional) Structs can contain fields of unbounded types, this makes them unbounded structs.

(optional) Unbounded structs can be elements of fixed-size lists, the generated type is unbounded.

Unbounded types are unbounded sequence types and unbounded structs.

For the following examples, assume:
```python
struct MyStruct: # Not an unbounded type
    i: uint256
```

Examples of unbounded types:
```python
# Unbounded because no bound

String[INF]
uint256[INF]
DynArray[MyStruct, INF]

# If unbounded structs are allowed:
struct MyUnboundedStruct:
    bytes: Bytes[INF]

# Unbounded because contains unbounded struct

DynArray[MyUnboundedStruct, 4]
DynArray[MyUnboundedStruct, INF]

# If unbounded structs can are valid for fixed-size lists:
MyUnboundedStruct[4]
```

Unbounded types are _only_ valid as:
1. method parameters types
2. method return types
3. local variable types (for variables inside methods)
4. (optional) field types for structs

```python
struct NameBox:
    name: String[INF] # valid

name1: String[INF]    # invalid, not a local variable
name_box1: NameBox # invalid, not a local variable

@external # following also valid for internal methods
def foo(
    name2: String[INF]       # valid, parameter
    name_box2: NameBox    # valid, parameter
) -> (String[INF], NameBox): # valid, return type
  
  name3: String[INF] = name2        # valid, local variable
  name_box3: NameBox = name_box2 # valid, local variable
  
  return (name3, name_box2)
```

Unbounded sequence types are super-types of their bounded counterparts (`String[n] <: String[INF]`), for example a `String[4]` can be assigned to a variable of type `String[INF]`.
This is not true in reverse, a `String[INF]` cannot be assigned to a variable of type `String[4]`, as we cannot be sure it is of length `<= 4`.

`convert`-ing from an unbounded type to a bounded counterpart succeeds if the length fits, and reverts otherwise.
`convert`-ing from an unbounded type to another unbounded type follows the same rules as if they were bounded, for example padding is adjusted accordingly.
`convert`-ing from an unbounded type to anything else first `convert`s to the most appropriate unbounded type (if required), and then `convert`s again to the destination type. Example: `convert(s: String[INF], Bytes[5])` is equivalent to `convert(convert(s: String[INF], Bytes[INF]), Bytes[5])`.

There exists one additional way to convert some unbounded sequence types to bounded ones: `slice`, see below.

### Built-ins

Changes to built-ins, both to make them work better with the new features, as well as to standardize notation.

#### Semantically different:

* `slice`
	* `b: Bytes | bytes32 | String` to `b: Bytes[INF] | bytes32 | String[INF]`
	* return `Bytes | String` to 
		* `Bytes[length] | String[length]` if `length` is known at compile time
		* `Bytes[32]` if type of `b` is `bytes32`
		* `<type of b>` otherwise
		* Note: this is the current behavior, but is undocumented
* `raw_call`
	* `data: Bytes` to `data: Bytes[INF]`
	* (optional)
		* deprecate `max_outsize` 
		* make it return `Bytes[INF]`
		* (optional) or like `slice`: if `max_outsize` is know at compile time, returns `Bytes[max_outsize]`, else returns `Bytes[INF]`
* `msg.data`, `self.code`, and `<address>.code`
	* now of type `Bytes[INF]`
	* Should remove special handling of these types around slicing

#### Cleanup notation:

* `raw_create`
	* `initcode: Bytes[...]` to `initcode: Bytes[INF]`
* `raw_log`
	* `data: Bytes | bytes32` to `data: Bytes[INF] | bytes32`
* `raw_revert`
	* `data: Bytes` to `data: Bytes[INF]`
* `extract32`
	* `b: Bytes` to `b: Bytes[INF]`
* `as_wei_value`
	* `unit: str` to `unit: String[INF]`
		or to `unit: String[n]` where `n` is the greatest number of letters in the valid formats
* `len`
	* `b: Bytes | String | DynArray[_Type, _Integer]` to `b: Bytes[INF] | String[INF] | DynArray[_Type, INF]`

### Simplifies the compiler

Things like `Bytes.any()` can be replaced by the representation for `Bytes[INF]`, since `String[n] <: String[INF]` for any `n`.

### Back-end

TODO

## Backwards compatibility

TODO

## Alternatives considered

### Optimize calls so that the cost depends on the argument value or type, and not on the parameter type

While beneficial, it could still lead to issues:
1. The library or contract designer assumes `Bytes[1000]` is plenty, but end-user needs to pass `Bytes[1024]`.
2. Many built-ins already use types which are unbounded, this would not allow us to create true forwarders/wrappers for these methods, and makes these built-ins harder to document.

### Different syntax for the same idea

* `String`:
  Forward compat: If we ever want fixed-size lists of strings this will lead to ambiguity: `String[5]` vs `(String)[5]`.
  Does not generalize to dynamic arrays, since we can't remove their subscript.
* `String[]` (Solidity's solution):
  Issues with dynamic arrays: `DynArray[uint256, ]` or `DynArray[uint256]`.
* `String[...]`:
  A bit verbose, but does work well with dynamic arrays: `DynArray[uint256, ...]`

The syntaxes above are also less clear about sub-typing.
Since `String[4] <: String[5]`, it follows that `String[4] <: String[INF]` and not `String[INF] <: String[4]`.
That is less clear with the other syntaxes:
1. `String[4] <: String` and not `String <: String[4]`
2. `String[4] <: String[]` and not `String[] <: String[4]`
3. `String[4] <: String[...]` and not `String[...] <: String[4]`

`INF` could also be `INFTY`, `INFINITY`, etc, or an one of their lower-case versions.
All uppercase was chosen because this value is like a constant.
And `INF` in particular was chosen because it is short to type while remaining intelligible.
