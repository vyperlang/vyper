# helper module which implements jumptable for function selection
from dataclasses import dataclass
from typing import Optional, Tuple
from vyper.utils import keccak256, bytes_to_int
import math

@dataclass
class Signature:
    method_id: int
    payable: bool


# https://stackoverflow.com/a/568618/ with comments removed
def gen_primes():
    """ Generate an infinite sequence of prime numbers."""
    D = {}

    q = 2

    while True:
        if q not in D:
            yield q
            D[q * q] = [q]
        else:
            for p in D[q]:
                D.setdefault(p + q, []).append(p)
            del D[q]

        q += 1

def find_magic_for(xs):
    gen = gen_primes()
    for i in range(0xFFFF):
        p = next(gen)
        test = [((x * p) >> 32) % len(xs) for x in xs]
        if len(test) == len(set(test)):
            return p, test

    raise Exception(f"Could not find hash for {xs}")

# two layer method for generating perfect hash
# first get "reasonably good" distribution by using
# method_id % len(method_ids)
# second, get the magic for the bucket.
def _jumptable(method_ids):
    buckets = {}
    for x in method_ids:
        t = x % len(method_ids)
        buckets.setdefault(t, [])
        buckets[t].append(x)

    hashtable = {}
    for bucket, ids in buckets.items():
        magic, vals = find_magic_for(ids)
        hashtable[bucket] = (magic, ids, vals)

    return hashtable


def jumptable_ir(signatures):
    jumptable = _jumptable([sig.method_id for sig in signatures])
