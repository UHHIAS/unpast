import pandas as pd
from utils.eval import find_best_matches


def read_results(tool_name, result_file):
    if tool_name in ['isa2', 'fabia', 'qubic']:
        result = pd.read_csv(result_file, names=['samples', 'genes'], sep="\t")
        result["samples"] = result["samples"].apply(lambda x: set(x.split(" ")))
        result["genes"] = result["genes"].apply(lambda x: set(x.split(" ")))
        return result
    elif tool_name == 'debi':
        samples = []
        genes = []
        line_nr = -1
        with open(result_file, 'r') as fh:
            for line in fh.readlines():
                line_nr = (line_nr + 1) % 3
                if line_nr == 1:
                    samples.append(set(line.split(" ")))
                elif line_nr == 2:
                    genes.append(set(line.split(" ")))
        return pd.DataFrame({'samples': samples, 'genes': genes})


def run_eval(tool_name, expr_file, ground_truth_file, result_file):
    # expression file
    exprs = pd.read_csv(expr_file, sep="\t", index_col=0, header=0)
    N = len(exprs.columns)
    # read ground truth from file
    ground_truth = pd.read_csv(ground_truth_file, sep="\t", index_col=0)
    ground_truth["samples"] = ground_truth["samples"].apply(lambda x: set(x.split(" ")))
    if "genes" in ground_truth.columns.values:
        ground_truth["genes"] = ground_truth["genes"].apply(lambda x: set(x.split(" ")))

    # ground_truth

    # prepare a dict with sample groups corresponding to known bicluster
    known_groups = {}
    for group in ground_truth.index.values:
        known_groups[group] = ground_truth.loc[group, "samples"]

    result = read_results(tool_name, result_file)

    best_matches = find_best_matches(result, known_groups, N, FDR=0.05)
    return best_matches["J_weighted"].sum()
