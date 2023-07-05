# helper module which implements jumptable for function selection
from dataclasses import dataclass
from typing import Optional, Tuple
from vyper.utils import keccak256, bytes_to_int, method_id_int
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


_D = {}


# https://stackoverflow.com/a/568618/ but cache found data and
# with comments removed
# XXX: probably don't really want to use primes but keep this
# for a bit just in case
def _gen_primes():
    """Generate an infinite sequence of prime numbers."""
    q = 2

    while True:
        if q not in _D:
            yield q
            _D[q * q] = [q]
        else:
            for p in _D[q]:
                _D.setdefault(p + q, []).append(p)
            del _D[q]

        q += 1


BITS_MAGIC = 24  # a constant which produced good results, see _bench()


def _image_of(xs, magic):
    bits_shift = BITS_MAGIC

    # take the upper bits from the multiplication for more entropy
    return [((x * magic) >> (bits_shift)) % len(xs) for x in xs]


class _Failure(Exception):
    pass


def find_magic_for(xs):
    # for i, p in enumerate(_gen_primes()):
    for i in range(2**16):
        test = _image_of(xs, i)
        if len(test) == len(set(test)):
            return i

    raise _Failure(f"Could not find hash for {xs}")


# two layer method for generating perfect hash
# first get "reasonably good" distribution by using
# method_id % len(method_ids)
# second, get the magic for the bucket.
def _jumptable_info(method_ids, n_buckets):
    buckets = {}
    for x in method_ids:
        t = x % n_buckets
        buckets.setdefault(t, [])
        buckets[t].append(x)

    ret = {}
    for bucket_id, method_ids in buckets.items():
        magic = find_magic_for(method_ids)
        ret[bucket_id] = Bucket(bucket_id, magic, method_ids)

    return ret


START_BUCKET_SIZE = 4


def generate_jumptable_info(signatures):
    method_ids = [method_id_int(sig) for sig in signatures]
    n = len(signatures)
    # start at bucket size of 4 and try to improve (generally
    # speaking we want as few buckets as possible)
    n_buckets = n // START_BUCKET_SIZE
    ret = None
    while n_buckets > 0:
        try:
            print(f"trying {n_buckets} (bucket size {n // n_buckets})")
            ret = _jumptable_info(method_ids, n_buckets)
        except _Failure:
            # maybe try larger bucket size, but this seems pretty unlikely
            if ret is None:
                raise RuntimeError(f"Could not generate jumptable! {signatures}")
            return ret
        n_buckets -= 1

# benchmark for quality of buckets
def _bench():
    import random

    stats = []
    for i in range(1000):
        seed = random.randint(0, 1_000_000)
        # "large" contracts in prod hit about ~50 methods, test with
        # double the limit
        sigs = [f"foo{i + seed}()" for i in range(100)]

        xs = generate_jumptable_info(sigs)
        stats.append(xs)

    def mean(xs):
        return sum(xs) / len(xs)

    avg_n_buckets = mean([len(jt) for jt in stats])
    print(f"average N buckets: {avg_n_buckets}")
