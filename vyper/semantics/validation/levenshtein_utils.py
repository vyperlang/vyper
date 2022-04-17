from typing import Any, Dict


def levenshtein_norm(source: str, target: str) -> float:
    """Calculates the normalized Levenshtein distance between two string
    arguments. The result will be a float in the range [0.0, 1.0], with 1.0
    signifying the biggest possible distance between strings with these lengths

    From jazzband/docopt-ng
    https://github.com/jazzband/docopt-ng/blob/bbed40a2335686d2e14ac0e6c3188374dc4784da/docopt.py
    """

    # Compute Levenshtein distance using helper function. The max is always
    # just the length of the longer string, so this is used to normalize result
    # before returning it
    distance = levenshtein(source, target)
    return float(distance) / max(len(source), len(target))


def levenshtein(source: str, target: str) -> int:
    """Computes the Levenshtein
    (https://en.wikipedia.org/wiki/Levenshtein_distance)
    and restricted Damerau-Levenshtein
    (https://en.wikipedia.org/wiki/Damerau%E2%80%93Levenshtein_distance)
    distances between two Unicode strings with given lengths using the
    Wagner-Fischer algorithm
    (https://en.wikipedia.org/wiki/Wagner%E2%80%93Fischer_algorithm).
    These distances are defined recursively, since the distance between two
    strings is just the cost of adjusting the last one or two characters plus
    the distance between the prefixes that exclude these characters (e.g. the
    distance between "tester" and "tested" is 1 + the distance between "teste"
    and "teste"). The Wagner-Fischer algorithm retains this idea but eliminates
    redundant computations by storing the distances between various prefixes in
    a matrix that is filled in iteratively.

    From jazzband/docopt-ng
    https://github.com/jazzband/docopt-ng/blob/bbed40a2335686d2e14ac0e6c3188374dc4784da/docopt.py
    """

    # Create matrix of correct size (this is s_len + 1 * t_len + 1 so that the
    # empty prefixes "" can also be included). The leftmost column represents
    # transforming various source prefixes into an empty string, which can
    # always be done by deleting all characters in the respective prefix, and
    # the top row represents transforming the empty string into various target
    # prefixes, which can always be done by inserting every character in the
    # respective prefix. The ternary used to build the list should ensure that
    # this row and column are now filled correctly
    s_range = range(len(source) + 1)
    t_range = range(len(target) + 1)
    matrix = [[(i if j == 0 else j) for j in t_range] for i in s_range]

    # Iterate through rest of matrix, filling it in with Levenshtein
    # distances for the remaining prefix combinations
    for i in s_range[1:]:
        for j in t_range[1:]:
            # Applies the recursive logic outlined above using the values
            # stored in the matrix so far. The options for the last pair of
            # characters are deletion, insertion, and substitution, which
            # amount to dropping the source character, the target character,
            # or both and then calculating the distance for the resulting
            # prefix combo. If the characters at this point are the same, the
            # situation can be thought of as a free substitution
            del_dist = matrix[i - 1][j] + 1
            ins_dist = matrix[i][j - 1] + 1
            sub_trans_cost = 0 if source[i - 1] == target[j - 1] else 1
            sub_dist = matrix[i - 1][j - 1] + sub_trans_cost

            # Choose option that produces smallest distance
            matrix[i][j] = min(del_dist, ins_dist, sub_dist)

    # At this point, the matrix is full, and the biggest prefixes are just the
    # strings themselves, so this is the desired distance
    return matrix[len(source)][len(target)]


def get_levenshtein_error_suggestions(key: str, namespace: Dict[str, Any], threshold: float) -> str:
    """
    Generate an error message snippet for the suggested closest values in the provided namespace
    with the shortest normalized Levenshtein distance from the given key if that distance
    is below the threshold. Otherwise, return an empty string.

    As a heuristic, the threshold value is inversely correlated to the size of the namespace.
    For a small namespace (e.g. struct members), the threshold value can be the maximum of
    1.0 since the key must be one of the defined struct members. For a large namespace
    (e.g. types, builtin functions and state variables), the threshold value should be lower
    to ensure the matches are relevant.

    :param key: A string of the identifier being accessed
    :param namespace: A dictionary of the possible identifiers
    :param threshold: A floating value between 0.0 and 1.0

    :return: The error message snippet if the Levenshtein value is below the threshold,
        or an empty string.
    """

    if key is None or key == "":
        return ""

    distances = sorted([(i, levenshtein_norm(key, i)) for i in namespace], key=lambda k: k[1])
    if len(distances) > 0 and distances[0][1] <= threshold:
        if len(distances) > 1 and distances[1][1] <= threshold:
            return f"Did you mean '{distances[0][0]}', or maybe '{distances[1][0]}'?"
        return f"Did you mean '{distances[0][0]}'?"
    return ""
