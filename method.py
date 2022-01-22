import sys
import random
import pandas as pd
import numpy as np
from time import time
import os
import subprocess

from sklearn.mixture import GaussianMixture
from scipy.interpolate import interp1d
import jenkspy

import matplotlib.pyplot as plt
import statsmodels.api as sm



def calc_SNR(ar1, ar2):
    return (np.mean(ar1) - np.mean(ar2)) / (np.std(ar1) + np.std(ar2))

######### Binarization #########

def rand_norm_splits(N, min_n_samples, snr_pval = 0.01,seed = 42,verbose = True):
    # empirical distribuition of SNR depending on the bicluster size 
    # generates normal samples of matching size and split them into bicluster and background
    min_n_perm = int(5*1.0/snr_pval)
    n_perm = max(min_n_perm,int(100000/N))
    sizes = np.arange(min_n_samples,int(N/2)+min_n_samples+1)#.shape
    if verbose:
        print("\tGenerate empirical distribuition of SNR depending on the bicluster size ...")
        print("\t\ttotal samples: %s, min_n_samples: %s - %s, n_permutations: %s"%(N,sizes[0],sizes[-1],n_perm))
    snr_thresholds = np.zeros(sizes.shape)
    np.random.seed(seed=seed)
    for s in sizes:
        snrs = np.zeros(n_perm)
        for i in range(0,n_perm):
            x = np.random.normal(size = N)
            x.sort()
            snrs[i] = calc_SNR(x[s:], x[:s]) #(x[s:].mean()-x[:s].mean())/(x[s:].std()+x[:s].std())
        snr_thresholds[s-min_n_samples]=np.quantile(snrs,q=1-0.05)
    return sizes, snr_thresholds

def get_trend(sizes, thresholds, plot= True):
    # smoothens the trend and retunrs a function min_SNR(size; p-val. cutoff)
    lowess = sm.nonparametric.lowess
    lowess_curve = lowess(sizes, thresholds,frac=0.25,return_sorted=True,is_sorted=False)
    get_min_snr = interp1d(lowess_curve[:,1],lowess_curve[:,0],kind="nearest",fill_value="extrapolate")
    if plot:
        plt.plot(sizes, thresholds,"b--",lw=2)
        plt.plot(sizes,get_min_snr(sizes),"r-",lw=2)
        plt.xlabel("n_samples")
        plt.ylabel("SNR threshold")
        plt.show()
    return get_min_snr

def jenks_binarization(exprs, get_min_snr,min_n_samples,verbose = True,
                      plot=True, plot_SNR_thr= 3.0, show_fits = []):
    t0= time()
    if verbose:
        print("\tJenks method is chosen ...")
    binarized_expressions = {"UP" : {}, "DOWN" : {}}
    N = exprs.shape[1]
    n_bins = max(20,int(N/10))
    n_ambiguous = 0
    snrs = []
    sizes = []
    genes = []
    for i, (gene, row) in enumerate(exprs.iterrows()):
        values = row.values
        hist_range = values.min(), values.max()
        up_color, down_color = "grey", "grey"
        
        ### special treatment of zero expressions, try zero vs non-zero before Jenks breaks
        ### TBD
        neg_mask = values == hist_range[0]
        # if many min-values
        if neg_mask.astype(int).sum() >= min_n_samples:
            pos_mask = values > hist_range[0]
        
        else:
            breaks = jenkspy.jenks_breaks(values, nb_class=2)
            threshold = breaks[1]
            neg_mask = values<threshold
            pos_mask = values>=threshold
        
        down_group = values[neg_mask]
        up_group = values[pos_mask]
        
        if min(len(down_group),len(up_group)) >= min_n_samples:

            # calculate SNR 
            SNR = calc_SNR(up_group,down_group)
            size = min(len(down_group),len(up_group))
            # define bicluster and background if SNR is signif. higer than random
            if SNR >= get_min_snr(size):
                snrs.append(SNR)
                sizes.append(size)
                genes.append(gene)

                # in case of insignificant difference 
                # the bigger half is treated as signal too
                if abs(len(up_group)-len(down_group)) <= min_n_samples:
                    n_ambiguous +=1 

                if len(down_group)-len(up_group) >= -min_n_samples:
                    # up-regulated group is smaller than down-regulated
                    binarized_expressions["UP"][gene] = pos_mask.astype(int)
                    up_color='red'

                if len(up_group)-len(down_group) >= -min_n_samples:
                    binarized_expressions["DOWN"][gene] = neg_mask.astype(int)
                    down_color='blue'
                
        # logging
        if verbose:
            if i % 1000 == 0:
                print("\t\tgenes processed:",i)
                
        if (gene in show_fits or SNR > plot_SNR_thr) and plot:
            print("Gene %s: SNR=%s, pos=%s, neg=%s"%(gene, round(SNR,2), len(up_group), len(down_group)))
            plt.hist(down_group, bins=n_bins, alpha=0.5, color=down_color,range=hist_range)
            plt.hist(up_group, bins=n_bins, alpha=0.5, color=up_color,range=hist_range)
            plt.show()
    
    binarized_expressions["UP"] = pd.DataFrame.from_dict(binarized_expressions["UP"])
    binarized_expressions["DOWN"] = pd.DataFrame.from_dict(binarized_expressions["DOWN"])
    
    # logging
    if verbose:
        print("\tJenks binarization for {} features completed in {:.2f} s".format(len(exprs),time()-t0))
        print("\t\tup-regulated features:", binarized_expressions["UP"].shape[1])
        print("\t\tdown-regulated features:", binarized_expressions["DOWN"].shape[1])
        print("\t\tambiguous features:", n_ambiguous )
    stats = pd.DataFrame.from_records({"SNR":snrs,"size":sizes}, index = genes)
    return binarized_expressions, stats

def binarize(exprs, method='Jenks',
             load =False, save = False, prefix = "",
             min_n_samples = 10, snr_pval = 0.01,
             plot_all = True, plot_SNR_thr= 3.0,show_fits = [],
             verbose= True,seed=42):
    
    if load:
        # load from file binarized genes
        binarized_expressions = {}

        for d in ["UP","DOWN"]:
            suffix  = ".pv="+str(snr_pval)+",method="+method+",direction="+d
            fname =prefix+ suffix +".bin_exprs.tsv"
            print("Load binarized gene expressions from",fname,file = sys.stdout)
            df = pd.read_csv(fname, sep ="\t",index_col=0)
            #df.index = range(0,df.shape[0])
            binarized_expressions[d] = df
    else:
        start_time = time()
        if verbose:
            print("\nBinarization started ....\n")

        t0 = time()
        sizes,thresholds = rand_norm_splits(exprs.shape[1],min_n_samples, snr_pval = snr_pval,seed=seed)
        get_min_snr = get_trend(sizes,thresholds, plot = plot_all)
        if verbose:
            print("\tSNR thresholds for individual features computed in {:.2f} seconds".format(time()-t0))

        if method=="Jenks":
            binarized_expressions, stats = jenks_binarization(exprs, get_min_snr,min_n_samples,verbose = verbose,
                                                  plot=plot_all, plot_SNR_thr=plot_SNR_thr, show_fits = show_fits)
        elif method=="GMM":
            from method2 import GM_binarization
            binarized_expressions = GM_binarization(exprs,get_min_snr,min_n_samples,verbose = verbose,
                                                    plot=plot_all, plot_SNR_thr= plot_SNR_thr, show_fits = show_fits,
                                                    seed = seed)
        else:
            print("Method must be either 'GMM' or 'Jenks'.",file=sys.stderr)
            return
        
        if save:
            # save to file binarized data
            sample_names = exprs.columns
            for d in ["UP","DOWN"]:
                df = binarized_expressions[d]
                df.index = sample_names
                suffix  = ".pv="+str(snr_pval)+",method="+method+",direction="+d
                fname = prefix+ suffix +".bin_exprs.tsv"
                print("Binarized gene expressions are saved to",fname,file = sys.stdout)
                df.to_csv(fname, sep ="\t")
    return binarized_expressions

######## Clustering #########

def run_WGCNA(fname,p1=10,p2=10,verbose = False):
    # run Rscript
    if verbose:
        t0 = time()
        print("Running WGCNA for", fname, "...")
    process = subprocess.Popen(['Rscript','run_WGCNA.R', '10','10',fname],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    stdout = stdout.decode('utf-8')
    module_file = stdout.rstrip()
    #print(module_file)
    modules_df = pd.read_csv(module_file,sep = "\t",index_col=0)
    if verbose:
        print("\tmodules detected in in {:.2f} s.".format(time()-t0))
    
    # read WGCNA output
    modules = []
    not_clustered = []
    module_dict = modules_df.T.to_dict()
    for i in module_dict.keys():
        genes =  module_dict[i]["genes"].strip().split()
        if i == 0:
            not_clustered = genes
        else:
            modules.append(genes)
    if verbose:
        print("\t{} modules and {} not clustered genes".format(len(modules),len(not_clustered)))
    return (modules,not_clustered)

def make_biclsuter_jenks(exprs, bin_exprs,min_SNR =0,min_n_samples=-1,
                          verbose= True, plot=True):
    
    bicluster = {"n_genes":0}
    genes = exprs.index.to_list()
    ones_per_sample = bin_exprs.sum(axis=1)
    
    breaks = jenkspy.jenks_breaks(ones_per_sample, nb_class=2)
    border = breaks[1] 
    
    if plot and len(genes)>2:
        counts, pos, obj = plt.hist(ones_per_sample,bins=min(20,max(ones_per_sample)))
        tmp = plt.vlines(breaks[1],0,max(counts)*1.1,colors="red")
        tmp = plt.text(breaks[1],max(counts),str(breaks[1]))
        tmp = plt.show()
    
    samples = ones_per_sample[ones_per_sample>border].index.to_list()
    if len(samples) < min_n_samples:
        # not enough samples -> failed bicluster 
        return bicluster, genes   
    
    bg_samples = ones_per_sample[ones_per_sample<=border].index
    bg = exprs.loc[:, bg_samples]
    bic = exprs.loc[:,samples]
    SNR = (bic.mean(axis=1) - bg.mean(axis=1))/(bg.std(axis=1) + bic.std(axis=1))
    SNR = SNR.abs()
    #print(SNR)
    
    excluded_genes  = []
    if min_SNR > 0:
        excluded_genes = SNR[SNR<min_SNR].index.to_list()
        if len(excluded_genes)>0:
            SNR = SNR[SNR>=min_SNR]
            genes = SNR.index.to_list()
    
    if len(genes)<2:
        # not enough genes -> failed bicluster 
        return bicluster, genes + excluded_genes 
    
    avgSNR = SNR.mean()
    if verbose and len(genes)>2:
        print(SNR.shape[0],"x",len(samples),"avgSNR:",round(avgSNR,2))
        print("droped:(%s)"%len(excluded_genes)," ".join(excluded_genes))
        print("genes:(%s)"%len(genes)," ".join(genes))
        print("samples:(%s)"%len(samples)," ".join(samples))
    bicluster["samples"] = samples
    bicluster["n_samples"] = len(samples)
    bicluster["genes"] = genes
    bicluster["n_genes"] = len(genes)
    bicluster["avgSNR"] = avgSNR
    return bicluster, excluded_genes



def write_bic_table(bics_dict_or_df, results_file_name,to_str=True):
    bics = bics_dict_or_df.copy()
    if len(bics) ==0:
        print("No biclusters found",file=sys.stderr)
    else:
        if not type(bics) == type(pd.DataFrame()):
            bics = pd.DataFrame.from_dict(bics)
        if to_str:
            bics["genes"] = bics["genes"].apply(lambda x:" ".join(map(str,sorted(x))))
            bics["samples"] = bics["samples"].apply(lambda x:" ".join(map(str,sorted(x))))
        bics = bics.sort_values(by=["avgSNR","n_genes","n_samples"], ascending = False)
        bics.index = range(0,bics.shape[0])
        bics.index.name = "id"
        cols =  bics.columns.values
        first_cols = ["avgSNR","n_genes","n_samples","direction","genes","samples"]
        bics = bics.loc[:,first_cols+sorted(list(set(cols).difference(first_cols)))]
    bics.to_csv(results_file_name ,sep = "\t")
    
    
def modules2biclsuters_jenks(clustering_results,exprs,binarized_expressions,
                            min_SNR = 0.0,min_n_samples=20,
                            snr_pval=0.01,
                            bin_method = "GMM", clust_method = "WGCNA",
                            result_file_name = False,
                            directions=["UP","DOWN"],
                            plot=False,verbose = False):
    biclusters = {}
    not_clustered = {}
    i = 0
    for d in directions:
        biclusters[d] = {}
        exprs_bin = binarized_expressions[d]
        modules, not_clustered[d] = clustering_results[d]

        for genes in modules:
            bicluster,excluded_genes = make_biclsuter_jenks(exprs.loc[genes,:], exprs_bin.loc[:,genes],
                                                                min_SNR = min_SNR,min_n_samples=min_n_samples,
                                                                plot=plot,verbose = verbose)
            not_clustered[d]+=excluded_genes

            # while any genes deleted, try to update samples of the bicluster
            while len(excluded_genes) >0 and bicluster["n_genes"]>1:
                genes = bicluster["genes"]
                bicluster,excluded_genes = make_biclsuter_jenks(exprs.loc[genes,:], exprs_bin.loc[:,genes],
                                                                min_SNR = min_SNR,min_n_samples=min_n_samples,
                                                                plot=plot,verbose = verbose)
                not_clustered[d]+=excluded_genes
                genes = bicluster["genes"]

            if bicluster["n_genes"] > 1:
                bicluster["direction"] = d
                biclusters[d][i] = bicluster
                i+=1
            elif bicluster["n_genes"] == 1:
                not_clustered[d]+= bicluster["genes"]

        biclusters[d] = pd.DataFrame.from_dict(biclusters[d]).T
        biclusters[d] = biclusters[d].loc[:,["avgSNR","direction","n_genes","n_samples","genes","samples"]]
        biclusters[d] = biclusters[d].sort_values(by = ["avgSNR","n_genes","n_samples"],ascending = [False,False, False])
        biclusters[d].index = range(0,biclusters[d].shape[0])

        if result_file_name:
            suffix  = ".pv="+str(snr_pval)+",method="+bin_method+",direction="+d+"."+clust_method
            write_bic_table(biclusters[d], result_file_name+suffix+".biclusters.tsv")

        print(d,": {} features clustered into {} modules, {} - not clustered.".format(biclusters[d]["n_genes"].sum(),
                                                                                      biclusters[d].shape[0],
                                                                                      len(not_clustered[d])))
    return biclusters, not_clustered