# Adapted from https://en.wikipedia.org/wiki/S-expression#Parsing


def parse_literal(word):
    try:
        return int(word)
    except ValueError:
        return word


def parse_s_exp(string):
    sexp = [[]]
    word = ''
    in_str = False
    in_comment = False
    for char in string:
        if in_comment:
            if char is '\n':  # comment ends at the end of a line
                in_comment = False
            continue
        if char is ';':  # start of comment
            in_comment = True
            continue
        if char is '(' and not in_str:
            sexp.append([])
        elif char is ')' and not in_str:
            if word:
                sexp[-1].append(parse_literal(word))
                word = ''
            temp = sexp.pop()
            sexp[-1].append(temp)
        elif char in (' ', '\n', '\t') and not in_str:
            if word:
                sexp[-1].append(parse_literal(word))
                word = ''
        elif char is '\"':
            in_str = not in_str
        else:
            word += char
    return sexp[0]
