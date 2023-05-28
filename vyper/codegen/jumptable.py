# helper module which implements jumptable for function selection
from dataclasses import dataclass
from typing import Optional, Tuple
from vyper.utils import keccak256, bytes_to_int
import math

@dataclass
class Signature:
    method_id: int
    payable: bool

@dataclass
class Bucket:
    bucket_id: int
    magic: int
    signatures: list[int]

    @property
    def image(self):
        return _image_of([s for s in self.signatures], self.magic)


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

def _image_of(xs, p):
    return [((x * p) >> 32) % len(xs) for x in xs]

def find_magic_for(xs):
    gen = gen_primes()

    for i in range(0xFFFF):
        test = _image_of(xs, i)
        if len(test) == len(set(test)):
            return i

    raise Exception(f"Could not find hash for {xs}")

# two layer method for generating perfect hash
# first get "reasonably good" distribution by using
# method_id % len(method_ids)
# second, get the magic for the bucket.
def _jumptable(method_ids, i):

    buckets = {}
    for x in method_ids:
        t = x % i  # len(method_ids)
        buckets.setdefault(t, [])
        buckets[t].append(x)

    ret = {}
    for bucket_id, method_ids in buckets.items():
        magic = find_magic_for(method_ids)
        ret[bucket_id] = Bucket(bucket_id, magic, method_ids)

    return ret


def jumptable_ir(signatures):
    jumptable = _jumptable([sig.method_id for sig in signatures])
