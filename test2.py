# define the function
def my_func(N):
    # define variables
    a, b, c = 0, 0, 0
    # define statements
    a = 0
    while a < N:
        b = a + 1
        c = c + b
        a = b * 2
    return c


# perform SSA-form analysis using dictionary
ssa_defs = {}
b_count = {}

for const_obj in my_func.co_consts:
    if isinstance(const_obj, type(my_func)):
        for i, ss in enumerate(const_obj.co_names):
            if ss == "LOAD_GLOBAL" and i + 1 < len(const_obj.co_code):
                var_name = const_obj.co_names[const_obj.co_code[i + 1]]
                if var_name not in b_count:
                    b_count[var_name] = 1
                    ssa_defs[var_name] = f"{var_name}_{b_count[var_name]}"
                else:
                    b_count[var_name] += 1
                    ssa_defs[var_name] = f"{var_name}_{b_count[var_name]}"
                const_obj.co_names[i + 1] = ssa_defs[var_name]


def ssa_rewrite(var):
    if var not in ssa_defs:
        b_count[var] = 1
        ssa_defs[var] = f"{var}_{b_count[var]}"
    else:
        b_count[var] += 1
        ssa_defs[var] = f"{var}_{b_count[var]}"


# perform liveness analysis
liveness = {}


def calc_liveness(statement, in_set, out_set):
    for var in statement.used_variables():
        out_set.add(var)
    for var in statement.defined_variables():
        if var in out_set:
            out_set.remove(var)
        in_set.add(var)
        liveness[var] = out_set.copy()


# compute SSA-form and liveness information
ssa_defs.clear()
b_count.clear()
liveness.clear()
count = 0
for stmt in my_func.__code__.co_consts[1].co_consts:
    ss = stmt.__class__.__name__
    if ss == "ASSIGNMENT":
        ssa_rewrite(stmt.target)
        stmt.target = ssa_defs[stmt.target]
        ssa_defs[stmt.target] = stmt.source
    elif ss == "RETURN":
        ssa_rewrite(f"RET{count}")
        stmt.value = ssa_defs[stmt.value]
        ssa_defs[f"RET{count}"] = stmt.value
        count += 1
ssa_defs["N"] = "N"
for stmt in my_func.__code__.co_consts[1].co_consts:
    in_set, out_set = set(), set()
    calc_liveness(stmt, in_set, out_set)

# print the results
print("SSA form:")
for var, defn in ssa_defs.items():
    print(f"{var} : {defn}")
print("Liveness analysis:")
for var, live_set in liveness.items():
    print(f"{var} : {live_set}")
