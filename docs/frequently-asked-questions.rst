###########################
Frequently Asked Questions
###########################

***************
Basic Questions
***************

==============
What is Vyper?
============== 
Vyper is a smart contract development language. Vyper aims to be auditable, secure, and human-readable. Being simple to read is more important than being simple to write. 

==================
Vyper or Solidity?
================== 
For the majority of use-cases, this is personal preference. To support the aims of being secure, auditable, and human-readable, a number of programming constructs included in Solidity are not included in Vyper.  If your use-case requires these, use Solidity not Vyper. 

==============================
What is not included in Vyper?
============================== 
The following constructs are not included because their use can lead to misleading or difficult to understand code: 

* Modifiers
* Class inheritance
* Inline assembly
* Function overloading
* Operator overloading
* Binary fixed point. 

Recursive calling and infinite-length loops are not included because they cannot set an upper bound on gas limits. An upper bound is required to prevent gas limit attacks and ensure the security of smart contracts built in Vyper. 

======================
How do for loops work?
======================
Like Python for loops but with one significant difference. Vyper does not allow looping over variable lengths. Looping over variables introduces the possibility of infinite-length loops which make gas limit attacks possible. 

====================
How do structs work?
==================== 
Structs group variables and are accessed using ``struct.argname``. They are similar to Python dictionaries:: 

 # define the struct
 struct: { 
  arg1: int128, arg2: decimal
 } 
 
 #access arg1 in struct
 struct.arg1 = 1 



******************
Advanced Questions
******************
