## Contributing
* See Issues above, and feel free to submit your own issues or PRs if you discover a solution
* Further discussions and questions [chat on gitter](https://gitter.im/ethereum/viper)
* For more information, see [Contributing](http://viper.readthedocs.io/en/latest/contributing.html)

[![Join the chat at https://gitter.im/bethereum/viper](https://badges.gitter.im/ethereum/viper.svg)](https://gitter.im/ethereum/viper?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)
[![Build Status](https://travis-ci.org/ethereum/viper.svg?branch=master)](https://travis-ci.org/ethereum/viper)

### Principles and Goals

Viper is an experimental programming language that aims for some of the following goals:

* **Security** - it should be possible and natural to build secure smart contracts in Viper.
* **Language and compiler simplicity** - the language and the compiler implementation should strive to be simple.
* **Auditability** - Viper code should be maximally human-readable. Furthermore, **it should be maximally difficult to write misleading code**. Simplicity for the reader is more important than simplicity for the writer, and simplicity for readers with low prior experience with Viper (and low prior experience with programming in general) is particularly important.

Some examples of what Viper does NOT have and why:

* **Modifiers** - eg. in Solidity you can do `function foo() mod1 { ... }`, where `mod1` can be defined elsewhere in the code to include a check that is done before execution, a check that is done after execution, some state changes, or possibly other things. Viper does not have this, because it makes it too easy to write misleading code. `mod1` just _looks_ too innocuous for something that could add arbitrary pre-conditions, post-conditions or state changes. Also, it encourages people to write code where the execution jumps around the file, harming auditability. The usual use case for a modifier is something that performs a single check before execution of a program; our recommendation is to simply inline these checks as asserts.
* **Class inheritance** - requires people to jump between multiple files to understand what a program is doing, and requires people to understand the rules of precedence in case of conflicts (which class's function X is the one that's actually used?). Hence, it makes code too complicated to understand.
* **Inline assembly** - adding inline assembly would make it no longer possible to Ctrl+F for a variable name to find all instances where that variable is read or modified.
* **Operator overloading** - waaay too easy to write misleading code (what do you mean "+" means "send all my money to the developer"? I didn't catch the part of the code that says that!).
* **Recursive calling** - cannot set an upper bound on gas limits, opening the door for gas limit attacks.
* **Infinite-length loops** - cannot set an upper bound on gas limits, opening the door for gas limit attacks.
* **Binary fixed point** - decimal fixed point is better, because any decimal fixed point value written as a literal in code has an exact representation, whereas with binary fixed point approximations are often required (eg. 0.2 -> 0.001100110011..., which needs to be truncated), leading to unintuitive results, eg. in python `0.3 + 0.3 + 0.3 + 0.1 != 1`.

Some changes that may be considered after Metropolis when STATICCALL becomes available include:

* Forbidding state changes after non-static calls unless the address being non-statically called is explicitly marked "trusted". This would reduce risk of re-entrancy attacks.
* Forbidding "inline" non-static calls, eg. `send(some_address, contract.do_something_and_return_a_weivalue())`, enforcing clear separation between "call to get a response" and "call to do something".

Viper does NOT strive to be a 100% replacement for everything that can be done in Solidity; it will deliberately forbid things or make things harder if it deems fit to do so for the goal of increasing security.

### Compatibility-breaking change log

* **2017.07.25**: the `def foo() -> num(const): ...` syntax no longer works; you now need to do `def foo() -> num: ...` with a `@constant` decorator on the previous line.
* **2017.07.25**: functions without a `@payable` decorator now fail when called with nonzero wei.
* **2017.07.25**: a function can only call functions that are declared above it (that is, A can call B only if B appears earlier in the code than A does). This was introduced to prevent infinite looping through recursion.

### Grammar

Note that not all programs that satisfy the following are valid; for example, there are also requirements against declaring variables twice, accessing undeclared variables, type mismatches among other rules.

    body = <globals> + <defs>
    globals = <global> <global> ...
    global = <varname>: <type>
    defs = <def> <def> ...
    def = <0 or more decorators> def <funname>(<argname>: <type>, <argname>: <type>...): <body>
        OR <0 or more decorators> def <funname>(<argname>: <type>, <argname>: <type>...) -> <type>: <body>
    decorator = @constant OR @payable OR @private OR @public
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
        OR selfdestruct(<expr>)
        OR [other functions, see full list in viper/functions.py]
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
        OR <expr>.codesize
        OR <system_var>
        OR <basetype>(<expr>) (only some type conversions allowed)
        OR floor(<expr>)
        OR [other functions, see full list in viper/functions.py]
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
* `type[base_type]`: map (can only be accessed, NOT iterated)
* `{arg1:type, arg2:type...}`: struct (can be accessed via struct.argname)

Arithmetic is overflow-checked, meaning that if a number is out of range then an exception is immediately thrown. Division and modulo by zero has a similar effect. The only kind of looping allowed is a for statement, which can come in three forms:

* `for i in range(x): ...` : x must be a nonzero positive constant integer, ie. specified at compile time
* `for i in range(x, y): ...` : x and y must be nonzero positive constant integers, ie. specified at compile time
* `for i in range(start, start + x): ...` : start can be any expression, though it must be the exact same expression in both places. x must be a nonzero positive constant integer.

In all three cases, it's possible to statically determine the maximum runtime of a loop. Jumping out of a loop before it ends can be done with either `break` or `return`.

Regarding byte array literals, unicode strings like "这个傻老外不懂中文" or "Я очень умный" are illegal, though those that manage to use values that are in the 0...255 range according to UTF-8, like "¡très bien!", are fine.

Code examples can be found in the `test_parser.py` file.

### Visibility

* `public(type)`: publicly visible state variable

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
@payable
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
    assert block.timestamp >= self.deadline and self.balance < self.goal
    ind = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = None
    self.refundIndex = ind + 30
```


# Installation
Don't panic if installation fails, Viper is still under development and constant changes. Installation will be much simplified/optimized after a stable version release.

Take a deep breath and follow, please create an issue if any errors encountered.

It is **strongly recommended** to install in **a virtual Python environment (normally either `virtualenv` or `venv`)**, so that new packages installed and dependencies built are strictly contained in your viper project and will not alter/affect your other dev environment set-up.

To find out how to set-up virtual environment, check out: [virtualenv guide](https://virtualenv.pypa.io/en/stable/).


- **Ubuntu (16.04 LTS)**
1. Package update:
```
sudo apt-get update
sudo apt-get -y upgrade
```

2. For Viper to run, Python3.6 or later is required, know your python version, if the output is `Python 3.5.2`, then install python3.6, otherwise skip step 3
```
python3 -V
```

3. Install python3.6 and some necessary package (*if you haven't installed the package*)
```
sudo apt-get install build-essential libssl-dev libffi-dev

wget https://www.python.org/ftp/python/3.6.1/Python-3.6.1.tgz
tar xfz Python-3.6.1.tgz
cd Python-3.6.1/
./configure –prefix /usr/local/lib/python3.6
sudo make
sudo make install
```

4. Now, start a python virtual environment named it "viper", then activate the virtual env. (after activation, you should be able to see "(viper)" at the front of each commandline, indicating that you are now in a virtual environment)
```
virtualenv --python=/usr/local/lib/python3.6/bin/python --no-site-packages viper
source viper/bin/activate

```
   To deactivate and return to default environment, (you should see the "(viper)" at the front disappeared.)
```
deactivate
```

   *Alternatively*: It is handy to use `pyenv` [https://github.com/pyenv/pyenv] to help manage your Python 3.6.2 or higher when Python releases new version. It works like a python version manager.
```
pyenv virtualenv viper
```

5. Now, we are talking business, clone this Viper repo and install and test, and Walla!
```
git clone https://github.com/ethereum/viper.git
cd viper
python setup.py install
python setup.py test
```

- **MacOS**

1. Make sure you have homebrew installed. if not, you could checkout [How-To-Geek Guide](https://www.howtogeek.com/211541/homebrew-for-os-x-easily-installs-desktop-apps-and-terminal-utilities/) or [Homebrew Repo](https://github.com/Homebrew/brew/blob/master/docs/Installation.md)

2. Make sure your python is 3.6 or higher. If not, you could checkout [python3 for MacOS guide](http://python-guide.readthedocs.io/en/latest/starting/install3/osx/)

3. Now, go ahead and clone viper repo (not within `pyethereum` folder), and you run install and test, and Walla !!
```
git clone https://github.com/ethereum/viper.git
cd viper
python setup.py install
python setup.py test
```

If it fails with some error message on `openssl`, do the following:
```
env LDFLAGS="-L$(brew --prefix openssl)/lib" CFLAGS="-I$(brew --prefix openssl)/include" pip install scrypt
```

# Compile
To compile your file, use:
```
viper yourFileName.v.py
```

**Note: Since .vy is not official a language supported by any syntax highlights or linter, it is recommended to name your viper file into `.v.py` to have a python highlights.**


## Testing

	python setup.py test
