# helper module which implements jumptable for function selection
import math
from dataclasses import dataclass

from vyper.utils import method_id_int


@dataclass
class Signature:
    method_id: int
    payable: bool


# bucket for dense function
@dataclass
class Bucket:
    bucket_id: int
    magic: int
    method_ids: list[int]

    @property
    def image(self):
        return _image_of([s for s in self.method_ids], self.magic)

    @property
    # return method ids, sorted by by their image
    def method_ids_image_order(self):
        return [x[1] for x in sorted(zip(self.image, self.method_ids))]

    @property
    def bucket_size(self):
        return len(self.method_ids)


BITS_MAGIC = 24  # a constant which produced good results, see _bench_dense()


def _image_of(xs, magic):
    bits_shift = BITS_MAGIC

    # take the upper bits from the multiplication for more entropy
    # can we do better using primes of some sort?
    return [((x * magic) >> bits_shift) % len(xs) for x in xs]


class _FindMagicFailure(Exception):
    pass


class _HasEmptyBuckets(Exception):
    pass


def find_magic_for(xs):
    for m in range(2**16):
        test = _image_of(xs, m)
        if len(test) == len(set(test)):
            return m

    raise _FindMagicFailure(f"Could not find hash for {xs}")


def _mk_buckets(method_ids, n_buckets):
    buckets = {}
    for x in method_ids:
        t = x % n_buckets
        buckets.setdefault(t, [])
        buckets[t].append(x)
    return buckets


# two layer method for generating perfect hash
# first get "reasonably good" distribution by using
# method_id % len(method_ids)
# second, get the magic for the bucket.
def _dense_jumptable_info(method_ids, n_buckets):
    buckets = _mk_buckets(method_ids, n_buckets)

    # if there are somehow empty buckets, bail out as that can mess up
    # the bucket header layout
    if len(buckets) != n_buckets:
        raise _HasEmptyBuckets()

    ret = {}
    for bucket_id, method_ids in buckets.items():
        magic = find_magic_for(method_ids)
        ret[bucket_id] = Bucket(bucket_id, magic, method_ids)

    return ret


START_BUCKET_SIZE = 5


# this is expensive! for 80 methods, costs about 350ms and probably
# linear in # of methods.
# see _bench_perfect()
# note the buckets are NOT in order!
def generate_dense_jumptable_info(signatures):
    method_ids = [method_id_int(sig) for sig in signatures]
    n = len(signatures)
    # start at bucket size of 5 and try to improve (generally
    # speaking we want as few buckets as possible)
    n_buckets = (n // START_BUCKET_SIZE) + 1
    ret = None
    tried_exhaustive = False
    while n_buckets > 0:
        try:
            # print(f"trying {n_buckets} (bucket size {n // n_buckets})")
            solution = _dense_jumptable_info(method_ids, n_buckets)
            assert len(solution) == n_buckets
            ret = n_buckets, solution

        except _HasEmptyBuckets:
            # found a solution which has empty buckets; skip it since
            # it will break the bucket layout.
            pass

        except _FindMagicFailure:
            if ret is not None:
                break

            # we have not tried exhaustive search. try really hard
            # to find a valid jumptable at the cost of performance
            if not tried_exhaustive:
                # print("failed with guess! trying exhaustive search.")
                n_buckets = n
                tried_exhaustive = True
                continue
            else:
                raise RuntimeError(f"Could not generate jumptable! {signatures}")
        n_buckets -= 1

    return ret


# note the buckets are NOT in order!
def generate_sparse_jumptable_buckets(signatures):
    method_ids = [method_id_int(sig) for sig in signatures]
    n = len(signatures)

    # search a range of buckets to try to minimize bucket size
    # (doing the range search improves worst worst bucket size from 9 to 4,
    # see _bench_sparse)
    lo = max(1, math.floor(n * 0.85))
    hi = max(1, math.ceil(n * 1.15))
    stats = {}
    for i in range(lo, hi + 1):
        buckets = _mk_buckets(method_ids, i)

        stats[i] = buckets

    min_max_bucket_size = hi + 1  # smallest max_bucket_size
    # find the smallest i which gives us the smallest max_bucket_size
    for i, buckets in stats.items():
        max_bucket_size = max(len(bucket) for bucket in buckets.values())
        if max_bucket_size < min_max_bucket_size:
            min_max_bucket_size = max_bucket_size
            ret = i, buckets

    assert ret is not None
    return ret


# benchmark for quality of buckets
def _bench_dense(N=1_000, n_methods=100):
    import random

    stats = []
    for i in range(N):
        seed = random.randint(0, 2**64 - 1)
        # "large" contracts in prod hit about ~50 methods, test with
        # double the limit
        sigs = [f"foo{i + seed}()" for i in range(n_methods)]

        xs = generate_dense_jumptable_info(sigs)
        print(f"found. n buckets {len(xs)}")
        stats.append(xs)

    def mean(xs):
        return sum(xs) / len(xs)

    avg_n_buckets = mean([len(jt) for jt in stats])
    # usually around ~14 buckets per 100 sigs
    # N=10, time=3.6s
    print(f"average N buckets: {avg_n_buckets}")


def _bench_sparse(N=10_000, n_methods=80):
    import random

    stats = []
    for _ in range(N):
        seed = random.randint(0, 2**64 - 1)
        sigs = [f"foo{i + seed}()" for i in range(n_methods)]
        _, buckets = generate_sparse_jumptable_buckets(sigs)

        bucket_sizes = [len(bucket) for bucket in buckets.values()]
        worst_bucket_size = max(bucket_sizes)
        mean_bucket_size = sum(bucket_sizes) / len(bucket_sizes)
        stats.append((worst_bucket_size, mean_bucket_size))

    # N=10_000, time=9s
    # range 0.85*n - 1.15*n
    # worst worst bucket size: 4
    # avg worst bucket size: 3.0018
    # worst mean bucket size: 2.0
    # avg mean bucket size: 1.579112583664968
    print("worst worst bucket size:", max(x[0] for x in stats))
    print("avg worst bucket size:", sum(x[0] for x in stats) / len(stats))
    print("worst mean bucket size:", max(x[1] for x in stats))
    print("avg mean bucket size:", sum(x[1] for x in stats) / len(stats))
