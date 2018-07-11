###########################
Frequently Asked Questions
###########################

***************
Basic Questions
***************

** What is Vyper? 
Vyper is a smart contract development language. Vyper aims to be human-readable. Being simple to read is more important than being simple to write. 

** Vyper or Solidity? 
For the majority of use-cases, this is perosnal preference. To support the aims of being secure, auditable, and human-readable, a number of programming constructs included in Solidity are not includeed in Vyper.  If your use-case requires these, use Solidity not Vyper. 

** What is not included in Vyper? 
The following constructs are not included because their use can lead to misleading or difficult to understand code: 
* Modifiers
* Class inheritance
* Inline assembly
* Function overloading
* Operator overloading
* Binary fixed point. 

Recursive calling and infinite-length loops are not included because they cannot set an upper bound on gas limits. An upper bound is required to prevent gas limit attacks and ensure the security of smart contracts build in Vyper. 

***************
Getting Started
***************

** Where do I get Vyper? 
GitHub - https://github.com/ethereum/vyper

** How do I get started with Vyper? 
See Installing Vyper. 
See Vyper by Example. 
Additional samples on GitHub - https://github.com/ethereum/vyper/tree/master/examples

** How do for loops work?
Like Python for loops but with one significant difference - Vyper does not allow looping over variable lengths. Looping over variables introduces the possibility of infinite-length loops which allow gas limit attacks. 


******************
Advanced Questions
******************
