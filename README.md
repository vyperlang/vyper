Viper is an experimental programming language that aims to provide the following features:

* Bounds and overflow checking, both on array accesses and on arithmetic
* Support for signed integers and decimal fixed point numbers
* Decidability - it's possible to compute a precise upper bound on the gas consumption of any function call
* Strong typing, including support for units (eg. timestamp, timedelta, seconds, wei, wei per second, meters per second squared)
* Maximally small and understandable compiler code size
* Limited support for pure functions - anything marked constant is NOT allowed to change the state

### Grammar

Note that not all programs that satisfy the following are valid; for example, there are also requirements against declaring variables twice, accessing undeclared variables, type mismatches among other rules.

    body = <globals> + <defs>
    globals = <global> <global> ...
    global = <varname> = <type>
    defs = <def> <def> ...
    def = def <funname>(<argname>: <type>, <argname>: <type>...): <body>
        OR def <funname>(<argname>: <type>, <argname>: <type>...) -> <type>: <body>
        OR def <funname>(<argname>: <type>, <argname>: <type>...) -> <type>(const): <body>
    argname = <str>
    body = <stmt> <stmt> ...
    stmt = <varname> = <type>
        OR <var> = <expr>
        OR <var> <augassignop> <expr>
        OR if <cond>: <body>
        OR if <cond>: <body> else: <body>
        OR for <varname> in range(<int>): <body>
        OR for <varname> in range(<expr>, <expr> + <int>): <body> (two exprs must match)
        OR pass
        OR return
        OR break
        OR return <expr>
        OR send(<expr>, <expr>)
        OR selfdestruct(<expr>) # suicide(<expr>) is a synonym
    var = <varname>
        OR <var>.<membername>
        OR <var>[<expr>]
    varname = <str>
    expr = <literal>
        OR <expr> <binop> <expr>
        OR <expr> <boolop> <expr>
        OR <expr> <compareop> <expr>
        OR not <expr>
        OR <var>
        OR <expr>.balance
        OR <system_var>
        OR <basetype>(<expr>) (only some type conversions allowed)
        OR floor(<expr>)
    literal = <integer>
        OR <fixed point number>
        OR <address, in the form 0x12cd2f...3fe, CHECKSUMS ARE MANDATORY>
        OR <bytes32, in the form 0x414db52e5....2a7d>
        OR <bytes, in the form "cow">
    system_var = (block.timestamp, block.coinbase, block.number, block.difficulty, tx.origin, tx.gasprice, msg.gas, self)
    basetype = (num, decimal, bool, address, bytes32)
    unit = <baseunit>
        OR <baseunit> * <positive integer>
        OR <unit> * <unit>
        OR <unit> / <unit>
    type = <basetype>
        OR bytes <= <maxlen>
        OR {<membername>: <type>, <membername>: <type>, ...}
        OR <type>[<basetype>]
        OR <type>[<int>] # Integer must be nonzero positive
        OR <num or decimal>(unit)
    binop = (+, -, *, /, %)
    augassignop = (+=, -=, *=, /=, %=)
    boolop = (or, and)
    compareop = (<, <=, >, >=, ==, !=)
    membername = varname = argname = <str>

### Types

* `num`: a signed integer strictly between -2\*\*128 and 2\*\*128
* `decimal`: a decimal fixed point value with the integer component being a signed integer strictly between -2\*\*128 and 2\*\*128 and the fractional component being ten decimal places
* `timestamp`: a timestamp value
* `timedelta`: a number of seconds (note: two timedeltas can be added together, as can a timedelta and a timestamp, but not two timestamps)
* `wei_value`: an amount of wei
* `currency_value`: an amount of currency
* `address`: an address
* `bytes32`: 32 bytes
* `bool`: true or false
* `type[length]`: finite list
* `bytes <= maxlen`: a byte array with the given maximum length
* `{base_type: type}`: map (can only be accessed, NOT iterated)
* `[arg1(type), arg2(type)...]`: struct (can be accessed via struct.argname)

Arithmetic is overflow-checked, meaning that if a number is out of range then an exception is immediately thrown. Division and modulo by zero has a similar effect. The only kind of looping allowed is a for statement, which can come in three forms:

* `for i in range(x): ...` : x must be a nonzero positive constant integer, ie. specified at compile time
* `for i in range(x, y): ...` : x and y must be nonzero positive constant integers, ie. specified at compile time
* `for i in range(start, start + x): ...` : start can be any expression, though it must be the exact same expression in both places. x must be a nonzero positive constant integer.

In all three cases, it's possible to statically determine the maximum runtime of a loop. Jumping out of a loop before it ends can be done with either `break` or `return`.

Regarding byte array literals, unicode strings like "这个傻老外不懂中文" or "Я очень умный" are illegal, though those that manage to use values that are in the 0...255 range according to UTF-8, like "¡très bien!", are fine.

Code examples can be found in the `test_parser.py` file.

### Planned future features

* Declaring external contract ABIs, and calling to external contracts
* A mini-language for handling num256 and signed256 values and directly / unsafely using opcodes; will be useful for high-performance code segments
* Smart optimizations, including compile-time computation of arithmetic and clamps, intelligently computing realistic variable ranges, etc

### Code example

```python
funders: {sender: address, value: wei_value}[num]
nextFunderIndex: num
beneficiary: address
deadline: timestamp
goal: wei_value
refundIndex: num
timelimit: timedelta
    
# Setup global variables
def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal
    
# Participate in this crowdfunding campaign
def participate():
    assert block.timestamp < self.deadline
    nfi = self.nextFunderIndex
    self.funders[nfi] = {sender: msg.sender, value: msg.value}
    self.nextFunderIndex = nfi + 1
    
# Enough money was raised! Send funds to the beneficiary
def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)
    
# Not enough money was raised! Refund everyone (max 30 people at a time
# to avoid gas limit issues)
def refund():
    ind = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = None
    self.refundIndex = ind + 30
```

## Installation

Requires python3

	python setup.py install

## Testing

	python setup.py test
