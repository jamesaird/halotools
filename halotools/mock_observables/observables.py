#Duncan Campbell
#August 27, 2014
#Yale University

#Contributions by Shany Danieli
#December 10, 2014
#Yale University

""" 
Functions that compute statistics of a mock galaxy catalog in a periodic box (or not!). 
"""

from __future__ import division
import sys

__all__=['two_point_correlation_function','two_point_correlation_function_jackknife',
         'angular_two_point_correlation_function','Delta_Sigma','apparent_to_absolute_magnitude',
         'luminosity_to_absolute_magnitude','get_sun_mag','luminosity_function','HOD',
         'CLF','CSMF','isolatoion_criterion']

####import modules########################################################################
import numpy as np
from math import pi, gamma
from multiprocessing import Pool
####try to import the best pair counter###################################################
try: from npairs_mpi import npairs, wnpairs, specific_wnpairs, jnpairs
except ImportError:
    print "MPI pair counter not available.  MPI functionality will not be supported."
    try: from kdpairs import npairs, wnpairs, specific_wnpairs, jnpairs
    except ImportError:
        print "kdtree pair counter not available. Brute force methods will be used."
        try: from cpairs import npairs, wnpairs, specific_wnpairs, jnpairs
        except ImportError:
            print "cython pair counter not available. Python brute force methods will be used."
            from pairs import npairs, wnpairs, specific_wnpairs, jnpairs
##########################################################################################

####define wrapper functions for pair counters to facilitate parallelization##############
#straight pair counter
def _npairs_wrapper(tup):
    return npairs(*tup)
#weighted pair counter
def _wnpairs_wrapper(tup):
    return wnpairs(*tup)
#specific weighted pair counter
def _specific_wnpairs_wrapper(tup):
    return specific_wnpairs(*tup)
#jackknife pair counter
def _jnpairs_wrapper(tup):
    return jnpairs(*tup)
##########################################################################################

def two_point_correlation_function(sample1, rbins, sample2 = None, randoms=None, 
                                   period = None, max_sample_size=int(1e6), 
                                   estimator='Natural', N_threads=1):
    """ Calculate the two-point correlation function. 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x k numpy array containing k-d positions of Npts. 
    
    rbins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(rbins) = Nrbins + 1.
    
    sample2 : array_like, optional
        Npts x k numpy array containing k-d positions of Npts.
    
    randoms : array_like, optional
        Nran x k numpy array containing k-d positions of Npts.
    
    period: array_like, optional
        length k array defining axis-aligned periodic boundary conditions. If only 
        one number, Lbox, is specified, period is assumed to be np.array([Lbox]*k).
        If none, PBCs are set to infinity.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.

    Returns 
    -------
    correlation_function : array_like
        array containing correlation function :math:`\\xi` computed in each of the Nrbins 
        defined by input `rbins`.

        :math:`1 + \\xi(r) \equiv DD / RR`, 
        where `DD` is calculated by the pair counter, and RR is counted by the internally 
        defined `randoms` if no randoms are passed as an argument.

        If sample2 is passed as input, three arrays of length Nrbins are returned: two for
        each of the auto-correlation functions, and one for the cross-correlation function. 

    """
    #####notes#####
    #The pair counter returns all pairs, including self pairs and double counted pairs 
    #with separations less than r. If PBCs are set to none, then period=np.inf. This makes
    #all distance calculations equivalent to the non-periodic case, while using the same 
    #periodic distance functions within the pair counter.
    ###############
    
    if N_threads>1:
        pool = Pool(N_threads)
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if sample2 != None: sample2 = np.asarray(sample2)
    else: sample2 = sample1
    if randoms != None: randoms = np.asarray(randoms)
    rbins = np.asarray(rbins)
    #Process period entry and check for consistency.
    if period is None:
            PBCs = False
            period = np.array([np.inf]*np.shape(sample1)[-1])
    else:
        PBCs = True
        period = np.asarray(period).astype("float64")
        if np.shape(period) == ():
            period = np.array([period]*np.shape(sample1)[-1])
        elif np.shape(period)[0] != np.shape(sample1)[-1]:
            raise ValueError("period should have shape (k,)")
            return None
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    
    if np.shape(rbins) == ():
        rbins = np.array([rbins])
    
    k = np.shape(sample1)[-1] #dimensionality of data
    
    #check for input parameter consistency
    if (period != None) & (np.max(rbins)>np.min(period)/2.0):
        raise ValueError('Cannot calculate for seperations larger than Lbox/2.')
    if (sample2 != None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if (randoms == None) & (min(period)==np.inf):
        raise ValueError('If no PBCs are specified, randoms must be provided.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))
    if (PBCs==True) & (max(period)==np.inf):
        raise ValueError('If a non-infinte PBC specified, all PBCs must be non-infinte.')

    #If PBCs are defined, calculate the randoms analytically. Else, the user must specify 
    #randoms and the pair counts are calculated the old fashion way.
    def random_counts(sample1, sample2, randoms, rbins, period, PBCs, k, N_threads):
        """
        Count random pairs.
        """
        def nball_volume(R,k):
            """
            Calculate the volume of a n-shpere.
            """
            return (pi**(k/2.0)/gamma(k/2.0+1.0))*R**k
        
        #No PBCs, randoms must have been provided.
        if PBCs==False:
            if N_threads==1:
                RR = npairs(randoms, randoms, rbins, period=period)
                RR = np.diff(RR)
                D1R = npairs(sample1, randoms, rbins, period=period)
                D1R = np.diff(D1R)
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    D2R = npairs(sample2, randoms, rbins, period=period)
                    D2R = np.diff(D2R)
            else:
                args = [[chunk,randoms,rbins,period] for chunk in np.array_split(randoms,N_threads)]
                RR = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                RR = np.diff(RR)
                args = [[chunk,randoms,rbins,period] for chunk in np.array_split(sample1,N_threads)]
                D1R = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                D1R = np.diff(D1R)
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    args = [[chunk,randoms,rbins,period] for chunk in np.array_split(sample2,N_threads)]
                    D2R = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                    D2R = np.diff(D2R)
            
            return D1R, D2R, RR
        #PBCs and randoms.
        elif randoms != None:
            if N_threads==1:
                RR = npairs(randoms, randoms, rbins, period=period)
                RR = np.diff(RR)
                D1R = npairs(sample1, randoms, rbins, period=period)
                D1R = np.diff(D1R)
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    D2R = npairs(sample2, randoms, rbins, period=period)
                    D2R = np.diff(D2R)
            else:
                args = [[chunk,randoms,rbins,period] for chunk in np.array_split(randoms,N_threads)]
                RR = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                RR = np.diff(RR)
                args = [[chunk,randoms,rbins,period] for chunk in np.array_split(sample1,N_threads)]
                D1R = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                D1R = np.diff(D1R)
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    args = [[chunk,randoms,rbins,period] for chunk in np.array_split(sample2,N_threads)]
                    D2R = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                    D2R = np.diff(D2R)
            
            return D1R, D2R, RR
        #PBCs and no randoms--calculate randoms analytically.
        elif randoms == None:
            #do volume calculations
            dv = nball_volume(rbins,k) #volume of spheres
            dv = np.diff(dv) #volume of shells
            global_volume = period.prod() #sexy
            
            #calculate randoms for sample1
            N1 = np.shape(sample1)[0]
            rho1 = N1/global_volume
            D1R = (N1)*(dv*rho1) #read note about pair counter
            
            #if not calculating cross-correlation, set RR exactly equal to D1R.
            if np.all(sample1 == sample2):
                D2R = None
                RR = D1R #in the analytic case, for the auto-correlation, DR==RR.
            else: #if there is a sample2, calculate randoms for it.
                N2 = np.shape(sample2)[0]
                rho2 = N2/global_volume
                D2R = N2*(dv*rho2) #read note about pair counter
                #calculate the random-random pairs.
                NR = N1*N2
                rhor = NR/global_volume
                RR = (dv*rhor) #RR is only the RR for the cross-correlation.

            return D1R, D2R, RR
        else:
            raise ValueError('Un-supported combination of PBCs and randoms provided.')
    
    def pair_counts(sample1, sample2, rbins, period, N_thread):
        """
        Count data pairs.
        """
        if N_threads==1:
            D1D1 = npairs(sample1, sample1, rbins, period=period)
            D1D1 = np.diff(D1D1)
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                D1D2 = npairs(sample1, sample2, rbins, period=period)
                D1D2 = np.diff(D1D2)
                D2D2 = npairs(sample2, sample2, rbins, period=period)
                D2D2 = np.diff(D2D2)
        else:
            args = [[chunk,sample1,rbins,period] for chunk in np.array_split(sample1,N_threads)]
            D1D1 = np.sum(pool.map(_npairs_wrapper,args),axis=0)
            D1D1 = np.diff(D1D1)
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                args = [[chunk,sample2,rbins,period] for chunk in np.array_split(sample1,N_threads)]
                D1D2 = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                D1D2 = np.diff(D1D2)
                args = [[chunk,sample2,rbins,period] for chunk in np.array_split(sample2,N_threads)]
                D2D2 = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                D2D2 = np.diff(D2D2)

        return D1D1, D1D2, D2D2
        
    def TP_estimator(DD,DR,RR,factor,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural':
            xi = (1.0/factor**2.0)*DD/RR - 1.0
        elif estimator == 'Davis-Peebles':
            xi = (1.0/factor)*DD/DR - 1.0
        elif estimator == 'Hewett':
            xi = (1.0/factor**2.0)*DD/RR - (1.0/factor)*DR/RR #(DD-DR)/RR
        elif estimator == 'Hamilton':
            xi = (DD*RR)/(DR*DR) - 1.0
        elif estimator == 'Landy-Szalay':
            xi = (1.0/factor**2.0)*DD/RR - (1.0/factor)*2.0*DR/RR + 1.0 #(DD - 2.0*DR + RR)/RR
        else: 
            raise ValueError("unsupported estimator!")
        return xi
              
    if randoms != None:
        factor1 = (len(sample1)*1.0)/len(randoms)
        factor2 = (len(sample2)*1.0)/len(randoms)
        factor3 = (len(sample1)**0.5)*((len(sample2)**0.5))/len(randoms)
    else: 
        factor1 = 1.0
        factor2 = 1.0
        factor3 = 1.0
    
    #count pairs
    D1D1,D1D2,D2D2 = pair_counts(sample1, sample2, rbins, period, N_threads)
    D1R, D2R, RR = random_counts(sample1, sample2, randoms, rbins, period, PBCs, k, N_threads) 
    
    if np.all(sample2==sample1):
        xi_11 = TP_estimator(D1D1,D1R,RR,factor1,estimator)
        return xi_11
    elif (PBCs==True) & (randoms == None): 
        #Analytical randoms used. D1R1=R1R1, D2R2=R2R2, and R1R2=RR. See random_counts().
        xi_11 = TP_estimator(D1D1,D1R,D1R,1.0,estimator)
        xi_12 = TP_estimator(D1D2,D1R,RR,1.0,estimator)
        xi_22 = TP_estimator(D2D2,D2R,D2R,1.0,estimator)
        return xi_11, xi_12, xi_22
    else:
        xi_11 = TP_estimator(D1D1,D1R,RR,factor1,estimator)
        xi_12 = TP_estimator(D1D2,D1R,RR,factor3,estimator)
        xi_22 = TP_estimator(D2D2,D2R,RR,factor2,estimator)
        return xi_11, xi_12, xi_22


def two_point_correlation_function_jackknife(sample1, randoms, rbins, Nsub=10, 
                                             Lbox=[250.0,250.0,250.0], sample2 = None, 
                                             period = None, max_sample_size=int(1e6), 
                                             estimator='Natural', N_threads=1, comm=None):
    """
    Calculate the two-point correlation function with jackknife errors. 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x k numpy array containing k-d positions of Npts.
    
    randoms : array_like
        Nran x k numpy array containing k-d positions of Npts. 
    
    rbins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(rbins) = Nrbins + 1.
    
    Nsub : array_like, optional
        numpy array of number of divisions along each dimension defining jackknife subvolumes
        if single integer is given, assumed to be equivalent for each dimension
    
    Lbox : array_like, optional
        length of data volume along each dimension
    
    sample2 : array_like, optional
        Npts x k numpy array containing k-d positions of Npts.
    
    period: array_like, optional
        length k array defining axis-aligned periodic boundary conditions. If only 
        one number, Lbox, is specified, period is assumed to be np.array([Lbox]*k).
        If none, PBCs are set to infinity.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.
    
    comm: mpi Intracommunicator object, optional

    Returns 
    -------
    correlation_function : array_like
        array containing correlation function :math:`\\xi` computed in each of the Nrbins 
        defined by input `rbins`.

    """
    
    if N_threads>1:
        pool = Pool(N_threads)
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if sample2 != None: sample2 = np.asarray(sample2)
    else: sample2 = sample1
    randoms = np.asarray(randoms)
    rbins = np.asarray(rbins)
    if type(Nsub) is int: Nsub = np.array([Nsub]*np.shape(sample1)[-1])
    else: Nsub = np.asarray(Nsub)
    if type(Lbox) in (int,float): Lbox = np.array([Lbox]*np.shape(sample1)[-1])
    else: Lbox = np.asarray(Lbox)
    #Process period entry and check for consistency.
    if period is None:
            PBCs = False
            period = np.array([np.inf]*np.shape(sample1)[-1])
    else:
        PBCs = True
        period = np.asarray(period).astype("float64")
        if np.shape(period) == ():
            period = np.array([period]*np.shape(sample1)[-1])
        elif np.shape(period)[0] != np.shape(sample1)[-1]:
            raise ValueError("period should have shape (k,)")
            return None
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    if len(randoms)>max_sample_size:
        inds = np.arange(0,len(randoms))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = randoms[inds]
        print('down sampling randoms...')
    if np.shape(Nsub)[0]!=np.shape(sample1)[-1]:
        raise ValueError("Nsub should have shape (k,) or be a single integer")
    
    if np.shape(rbins) == ():
        rbins = np.array([rbins])
    
    k = np.shape(sample1)[-1] #dimensionality of data
    N1 = len(sample1)
    N2 = len(sample2)
    Nran = len(randoms)
    
    #check for input parameter consistency
    if (period != None) & (np.max(rbins)>np.min(period)/2.0):
        raise ValueError('Cannot calculate for seperations larger than Lbox/2.')
    if (sample2 != None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))
    if (PBCs==True) & (max(period)==np.inf):
        raise ValueError('If a non-infinte PBC specified, all PBCs must be non-infinte.')
    
    def get_subvolume_labels(sample1, sample2, randoms, Nsub, Lbox):
        """
        Split volume into subvolumes, and tag points in subvolumes with integer labels for 
        use in the jackknife calculation.
        
        note: '0' tag should be reserved. It is used in the jackknife calculation to mean
        'full sample'
        """
        
        dL = Lbox/Nsub # length of subvolumes along each dimension
        N_sub_vol = np.prod(Nsub) # total the number of subvolumes
    
        #tag each particle with an integer indicating which jackknife subvolume it is in
        #subvolume indices for the sample1 particle's positions
        index_1 = np.sum(np.floor(sample1/dL)*np.hstack((1,np.cumprod(Nsub[:-1]))),axis=1)+1
        j_index_1 = index_1.astype(int)
        #subvolume indices for the random particle's positions
        index_random = np.sum(np.floor(randoms/dL)*np.hstack((1,np.cumprod(Nsub[:-1]))),axis=1)+1
        j_index_random = index_random.astype(int)
        #subvolume indices for the sample2 particle's positions
        index_2 = np.sum(np.floor(sample2/dL)*np.hstack((1,np.cumprod(Nsub[:-1]))),axis=1)+1
        j_index_2 = index_2.astype(int)
        
        return j_index_1, j_index_2, j_index_random, N_sub_vol
    
    def jnpair_counts(sample1, sample2, j_index_1, j_index_2, N_sub_vol, rbins,\
                      period, N_thread, comm):
        """
        Count jackknife data pairs: DD
        """
        if N_threads==1:
            D1D1 = jnpairs(sample1, sample1, rbins, period=period,\
                       weights1=j_index_1, weights2=j_index_1, N_vol_elements=N_sub_vol)
            D1D1 = np.diff(D1D1,axis=1)
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                D1D2 = D1D1
                D2D2 = D1D1
                D1D2 = jnpairs(sample1, sample2, rbins, period=period,\
                           weights1=j_index_1, weights2=j_index_2, N_vol_elements=N_sub_vol)
                D1D2 = np.diff(D1D2,axis=1)
                D2D2 = jnpairs(sample2, sample2, rbins, period=period,\
                           weights1=j_index_2, weights2=j_index_2, N_vol_elements=N_sub_vol)
                D2D2 = np.diff(D2D2,axis=1)
        else:
            inds1 = np.arange(0,len(sample1)) #array which is just indices into sample1
            inds2 = np.arange(0,len(sample2)) #array which is just indices into sample2
            args = [[sample1[chunk],sample1,rbins,period,j_index_1[chunk],j_index_1,N_sub_vol]\
                    for chunk in np.array_split(inds1,N_threads)]
            D1D1 = np.sum(pool.map(_jnpairs_wrapper,args),axis=0)
            D1D1 = np.diff(D1D1,axis=1)
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                args = [[sample1[chunk],sample2,rbins,period,j_index_1[chunk],j_index_2,N_sub_vol]\
                        for chunk in np.array_split(inds1,N_threads)]
                D1D2 = np.sum(pool.map(_jnpairs_wrapper,args),axis=0)
                D1D2 = np.diff(D1D2,axis=1)
                args = [[sample2[chunk],sample2,rbins,period,j_index_2[chunk],j_index_2,N_sub_vol]\
                        for chunk in np.array_split(inds2,N_threads)]
                D2D2 = np.sum(pool.map(_jnpairs_wrapper,args),axis=0)
                D2D2 = np.diff(D2D2,axis=1)

        return D1D1, D1D2, D2D2
    
    def jrandom_counts(sample, randoms, j_index, j_index_randoms, N_sub_vol, rbins,\
                       period, N_thread, comm, calculate_rr=True):
        """
        Count jackknife random pairs: DR, RR
        """
        
        if comm!=None:
            DR = jnpairs(sample, randoms, rbins, period=period,\
                           weights1=j_index, weights2=j_index_randoms,\
                           N_vol_elements=N_sub_vol, comm=comm)
            DR = np.diff(DR,axis=1)
            if calculate_rr==True:
                RR = jnpairs(randoms, randoms, rbins, period=period,\
                             weights1=j_index_randoms, weights2=j_index_randoms,\
                             N_vol_elements=N_sub_vol, comm=comm)
                RR = np.diff(RR,axis=1)
            else: RR=None
        elif N_threads==1:
            DR = jnpairs(sample, randoms, rbins, period=period,\
                           weights1=j_index, weights2=j_index_randoms,\
                           N_vol_elements=N_sub_vol)
            DR = np.diff(DR,axis=1)
            if calculate_rr==True:
                RR = jnpairs(randoms, randoms, rbins, period=period,\
                             weights1=j_index_randoms, weights2=j_index_randoms,\
                             N_vol_elements=N_sub_vol)
                RR = np.diff(RR,axis=1)
            else: RR=None
        else:
            inds1 = np.arange(0,len(sample)) #array which is just indices into sample1
            inds2 = np.arange(0,len(randoms)) #array which is just indices into sample2
            args = [[sample[chunk],randoms,rbins,period,j_index[chunk],j_index_randoms,N_sub_vol]\
                    for chunk in np.array_split(inds1,N_threads)]
            DR = np.sum(pool.map(_jnpairs_wrapper,args),axis=0)
            DR = np.diff(DR,axis=1)
            if calculate_rr==True:
                args = [[randoms[chunk],randoms,rbins,period,j_index_randoms[chunk],j_index_randoms,N_sub_vol]\
                       for chunk in np.array_split(inds2,N_threads)]
                RR = np.sum(pool.map(_jnpairs_wrapper,args),axis=0)
                RR = np.diff(RR,axis=1)
            else: RR=None

        return DR, RR
        
    def TP_estimator(DD,DR,RR,factor,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural':
            xi = (1.0/factor**2.0)*DD/RR - 1.0
        elif estimator == 'Davis-Peebles':
            xi = (1.0/factor)*DD/DR - 1.0
        elif estimator == 'Hewett':
            xi = (1.0/factor**2.0)*DD/RR - (1.0/factor)*DR/RR #(DD-DR)/RR
        elif estimator == 'Hamilton':
            xi = (DD*RR)/(DR*DR) - 1.0
        elif estimator == 'Landy-Szalay':
            xi = (1.0/factor**2.0)*DD/RR - (1.0/factor)*2.0*DR/RR + 1.0 #(DD - 2.0*DR + RR)/RR
        else: 
            raise ValueError("unsupported estimator!")
        return xi
    
    def jackknife_errors(sub,full,N_sub_vol):
        """
        Calculate jackknife errors.
        """
        after_subtraction =  sub - full
        squared = after_subtraction**2.0
        error2 = ((N_sub_vol-1)/N_sub_vol)*squared.sum(axis=0)
        error = error2**0.5
        
        return error
    
    #ratio of the number of data points to random points
    factor1 = (len(sample1)*1.0)/len(randoms)
    factor2 = (len(sample2)*1.0)/len(randoms)
    factor3 = (len(sample1)**0.5)*((len(sample2)**0.5))/len(randoms)
    
    j_index_1, j_index_2, j_index_random, N_sub_vol = \
                               get_subvolume_labels(sample1, sample2, randoms, Nsub, Lbox)
    
    #calculate all the pair counts
    D1D1, D1D2, D2D2 = jnpair_counts(sample1, sample2, j_index_1, j_index_2, N_sub_vol,\
                                     rbins, period, N_threads, comm)
    D1D1_full = D1D1[0,:]
    D1D1_sub = D1D1[1:,:]
    D1D2_full = D1D2[0,:]
    D1D2_sub = D1D2[1:,:]
    D2D2_full = D2D2[0,:]
    D2D2_sub = D2D2[1:,:]
    D1R, RR = jrandom_counts(sample1, randoms, j_index_1, j_index_random, N_sub_vol,\
                             rbins, period, N_threads, comm)
    if np.all(sample1==sample2):
        D2R=D1R
    else:
        D2R, RR_dummy= jrandom_counts(sample2, randoms, j_index_2, j_index_random,\
                                      N_sub_vol, rbins, period, N_threads, comm,\
                                      calculate_rr=False)
    D1R_full = D1R[0,:]
    D1R_sub = D1R[1:,:]
    D2R_full = D2R[0,:]
    D2R_sub = D2R[1:,:]
    RR_full = RR[0,:]
    RR_sub = RR[1:,:]
    
    #calculate the correlation function for the full sample
    xi_11_full  = TP_estimator(D1D1_full,D1R_full,RR_full,factor1,estimator)
    xi_12_full  = TP_estimator(D1D2_full,D1R_full,RR_full,factor3,estimator)
    xi_22_full  = TP_estimator(D2D2_full,D2R_full,RR_full,factor2,estimator)
    #calculate the correlation function for the subsamples
    xi_11_sub  = TP_estimator(D1D1_sub,D1R_sub,RR_sub,factor1,estimator)
    xi_12_sub  = TP_estimator(D1D2_sub,D1R_sub,RR_sub,factor3,estimator)
    xi_22_sub  = TP_estimator(D2D2_sub,D2R_sub,RR_sub,factor2,estimator)
    
    #calculate the errors
    xi_11_err = jackknife_errors(xi_11_sub,xi_11_full,N_sub_vol)
    xi_12_err = jackknife_errors(xi_12_sub,xi_12_full,N_sub_vol)
    xi_22_err = jackknife_errors(xi_22_sub,xi_22_full,N_sub_vol)
    
    if np.all(sample1==sample2):
        return xi_11_full,xi_11_err
    else:
        return xi_11_full,xi_12_full,xi_22_full,xi_11_err,xi_12_err,xi_22_err


def angular_two_point_correlation_function(sample1, theta_bins, sample2=None, randoms=None, 
                                           max_sample_size=int(1e6),estimator='Natural',
                                           do_auto=True, do_cross=True, N_threads=1, comm=None):
    """ Calculate the angular two-point correlation function. 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x 2 numpy array containing ra,dec positions of Npts. 
    
    theta_bins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(theta_bins) = N_theta_bins + 1.
    
    sample2 : array_like, optional
        Npts x 2 numpy array containing ra,dec positions of Npts.
    
    randoms : array_like, optional
        Nran x 2 numpy array containing ra,dec positions of Npts.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.

    comm: mpi Intracommunicator object, optional
    
    do_auto: boolean, optional
        do auto-correlation?
    
    do_cross: boolean, optional
        do cross-correlation?
    
    Returns 
    -------
    angular correlation_function : array_like
        array containing correlation function :math:`\\xi` computed in each of the Nrbins 
        defined by input `rbins`.

        :math:`1 + \\xi(r) \equiv DD / RR`, 
        where `DD` is calculated by the pair counter, and RR is counted by the internally 
        defined `randoms` if no randoms are passed as an argument.

        If sample2 is passed as input, three arrays of length Nrbins are returned: two for
        each of the auto-correlation functions, and one for the cross-correlation function. 

    """
    #####notes#####
    #The pair counter returns all pairs, including self pairs and double counted pairs 
    #with separations less than r. If PBCs are set to none, then period=np.inf. This makes
    #all distance calculations equivalent to the non-periodic case, while using the same 
    #periodic distance functions within the pair counter.
    ###############
    
    #parallel processing things...
    if comm!=None:
        rank=comm.rank
    else: rank=0
    if N_threads>1:
        pool = Pool(N_threads)
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if np.all(sample2 != None): sample2 = np.asarray(sample2)
    else: sample2 = sample1
    if np.all(randoms != None): 
        randoms = np.asarray(randoms)
        PBCs = False
    else: PBCs = True #assume full sky coverage
    theta_bins = np.asarray(theta_bins)
        
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    
    if np.shape(theta_bins) == ():
        theta_bins = np.array([theta_bins])
    
    k = 2 #only 2-dimensions: ra,dec
    if np.shape(sample1)[-1] != k:
        raise ValueError('angular correlation function requires 2-dimensional data')
    
    #check for input parameter consistency
    if np.all(sample2 != None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))

    #If PBCs are defined, calculate the randoms analytically. Else, the user must specify 
    #randoms and the pair counts are calculated the old fashion way.
    def random_counts(sample1, sample2, randoms, theta_bins, PBCs, N_threads, do_RR, do_DR, comm):
        """
        Count random pairs.
        """
        def cap_area(C):
            """
            Calculate angular area of a spherical cap with chord length c
            """
            theta = 2.0*np.arcsin(C/2.0)
            return 2.0*np.pi*(1.0-np.cos(theta))
        
        #No PBCs, randoms must have been provided.
        if PBCs==False:
            if comm!=None:
                if do_RR==True:
                    if rank==0: print('Running MPI pair counter for RR with {0} processes.'.format(comm.size))
                    RR = npairs(randoms, randoms, theta_bins, comm=comm)
                    RR = np.diff(RR)
                else: RR=None
                if do_DR==True:
                    if rank==0: print('Running MPI pair counter for D1R with {0} processes.'.format(comm.size))
                    D1R = npairs(sample1, randoms, theta_bins, comm=comm)
                    D1R = np.diff(D1R)
                else: D1R=None
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    print('manually skipping D2R right now.')
                    if True==False:
                    #if do_DR==True:
                        if rank==0: print('Running MPI pair counter for D2R with {0} processes.'.format(comm.size))
                        D2R = npairs(sample2, randoms, theta_bins, comm=comm)
                        D2R = np.diff(D2R)
                    else: D2R=None
            elif N_threads==1:
                if do_RR==True:
                    RR = npairs(randoms, randoms, theta_bins)
                    RR = np.diff(RR)
                else: RR=None
                if do_DR==True:
                    D1R = npairs(sample1, randoms, theta_bins)
                    D1R = np.diff(D1R)
                else: D1R=None
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    if do_DR==True:
                        D2R = npairs(sample2, randoms, theta_bins)
                        D2R = np.diff(D2R)
                    else: D2R=None
            else:
                if do_RR==True:
                    args = [[chunk,randoms,theta_bins] for chunk in np.array_split(randoms,N_threads)]
                    RR = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                    RR = np.diff(RR)
                else: RR=None
                if do_DR==True:
                    args = [[chunk,randoms,theta_bins] for chunk in np.array_split(sample1,N_threads)]
                    D1R = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                    D1R = np.diff(D1R)
                else: D1R=None
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    if do_DR==True:
                        args = [[chunk,randoms,theta_bins] for chunk in np.array_split(sample2,N_threads)]
                        D2R = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                        D2R = np.diff(D2R)
                    else: D2R=None
            
            return D1R, D2R, RR
        #PBCs and no randoms--calculate randoms analytically.
        elif PBCs==True:
            #do volume calculations
            dv = cap_area(theta_bins) #volume of spheres
            dv = np.diff(dv) #volume of shells
            global_area = 4.0*np.pi
            
            #calculate randoms for sample1
            N1 = np.shape(sample1)[0]
            rho1 = N1/global_area
            D1R = (N1)*(dv*rho1) #read note about pair counter
            
            #if not calculating cross-correlation, set RR exactly equal to D1R.
            if np.all(sample1 == sample2):
                D2R = None
                RR = D1R #in the analytic case, for the auto-correlation, DR==RR.
            else: #if there is a sample2, calculate randoms for it.
                N2 = np.shape(sample2)[0]
                rho2 = N2/global_area
                D2R = N2*(dv*rho2) #read note about pair counter
                #calculate the random-random pairs.
                NR = N1*N2
                rhor = NR/global_area
                RR = (dv*rhor) #RR is only the RR for the cross-correlation.

            return D1R, D2R, RR
        else:
            raise ValueError('Un-supported combination of PBCs and randoms provided.')
    
    def pair_counts(sample1, sample2, theta_bins, N_threads, do_auto, do_cross, do_DD, comm):
        """
        Count data pairs: D1D1, D1D2, D2D2.
        """
        if comm!=None:
            if do_auto==True:
                if rank==0: print('Running MPI pair counter for D1D1 with {0} processes.'.format(comm.size))
                D1D1 = npairs(sample1, sample1, theta_bins, period=None, comm=comm)
                D1D1 = np.diff(D1D1)
            else: D1D1=None
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                if do_cross==True:
                    if rank==0: print('Running MPI pair counter for D1D2 with {0} processes.'.format(comm.size))
                    D1D2 = npairs(sample1, sample2, theta_bins, period=None, comm=comm)
                    D1D2 = np.diff(D1D2)
                else: D1D2=None
                if do_auto==True:
                    if rank==0: print('Running MPI pair counter for D2D2 with {0} processes.'.format(comm.size))
                    D2D2 = npairs(sample2, sample2, theta_bins, period=None, comm=comm)
                    D2D2 = np.diff(D2D2)
                else: D2D2=False
        elif N_threads==1:
            if do_auto==True:
                D1D1 = npairs(sample1, sample1, theta_bins, period=None)
                D1D1 = np.diff(D1D1)
            else: D1D1=None
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                if do_cross==True:
                    D1D2 = npairs(sample1, sample2, theta_bins, period=None)
                    D1D2 = np.diff(D1D2)
                else: D1D2=None
                if do_auto==True:
                    D2D2 = npairs(sample2, sample2, theta_bins, period=None)
                    D2D2 = np.diff(D2D2)
                else: D2D2=False
        else:
            if do_auto==True:
                args = [[chunk,sample1,theta_bins] for chunk in np.array_split(sample1,N_threads)]
                D1D1 = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                D1D1 = np.diff(D1D1)
            else: D1D1=None
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                if do_cross==True:
                    args = [[chunk,sample2,theta_bins] for chunk in np.array_split(sample1,N_threads)]
                    D1D2 = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                    D1D2 = np.diff(D1D2)
                else: D1D2=None
                if do_auto==True:
                    args = [[chunk,sample2,theta_bins] for chunk in np.array_split(sample2,N_threads)]
                    D2D2 = np.sum(pool.map(_npairs_wrapper,args),axis=0)
                    D2D2 = np.diff(D2D2)
                else: D2D2=None

        return D1D1, D1D2, D2D2
        
    def TP_estimator(DD,DR,RR,ND1,ND2,NR1,NR2,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural':
            factor = ND1*ND2/(NR1*NR2)
            xi = (1.0/factor)*DD/RR - 1.0 #DD/RR-1
        elif estimator == 'Davis-Peebles':
            factor = ND1*ND2/(ND1*NR2)
            xi = (1.0/factor)*DD/DR - 1.0 #DD/DR-1
        elif estimator == 'Hewett':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*DR/RR #(DD-DR)/RR
        elif estimator == 'Hamilton':
            xi = (DD*RR)/(DR*DR) - 1.0 #DDRR/DRDR-1
        elif estimator == 'Landy-Szalay':
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*2.0*DR/RR + 1.0 #(DD - 2.0*DR + RR)/RR
        else: 
            raise ValueError("unsupported estimator!")
        return xi
    
    def TP_estimator_requirements(estimator):
        """
        return booleans indicating which pairs need to be counted for the chosen estimator
        """
        if estimator == 'Natural':
            do_DD = True
            do_DR = False
            do_RR = True
        elif estimator == 'Davis-Peebles':
            do_DD = True
            do_DR = True
            do_RR = False
        elif estimator == 'Hewett':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Hamilton':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Landy-Szalay':
            do_DD = True
            do_DR = True
            do_RR = True
        else: 
            raise ValueError("unsupported estimator!")
        return do_DD, do_DR, do_RR
              
    if np.all(randoms != None):
        N1 = len(sample1)
        N2 = len(sample2)
        NR = len(randoms)
    else: 
        N1 = 1.0
        N2 = 1.0
        NR = 1.0
    
    do_DD, do_DR, do_RR = TP_estimator_requirements(estimator)
    
    #convert angular coordinates into cartesian coordinates
    from halotools.utils.spherical_geometry import spherical_to_cartesian, chord_to_cartesian
    xyz_1 = np.empty((len(sample1),3))
    xyz_2 = np.empty((len(sample2),3))
    xyz_1[:,0],xyz_1[:,1],xyz_1[:,2] = spherical_to_cartesian(sample1[:,0], sample1[:,1])
    xyz_2[:,0],xyz_2[:,1],xyz_2[:,2] = spherical_to_cartesian(sample2[:,0], sample2[:,1])
    if PBCs==False:
        xyz_randoms = np.empty((len(randoms),3))
        xyz_randoms[:,0],xyz_randoms[:,1],xyz_randoms[:,2] = spherical_to_cartesian(randoms[:,0], randoms[:,1])
    else: xyz_randoms=None
    
    #convert angular bins to cartesian distances
    c_bins = chord_to_cartesian(theta_bins, radians=False)
    
    #count pairs
    if rank==0: print('counting data pairs...')
    D1D1,D1D2,D2D2 = pair_counts(xyz_1, xyz_2, c_bins, N_threads, do_auto, do_cross, do_DD, comm)
    if rank==0: print('counting random pairs...')
    D1R, D2R, RR = random_counts(xyz_1, xyz_2, xyz_randoms, c_bins, PBCs, N_threads, do_RR, do_DR, comm)
    if rank==0: print('done counting pairs')
    
    if rank==0:
        print(D1D2)
        print(D1R)
    
    if np.all(sample2==sample1):
        xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
        return xi_11
    else:
        if (do_auto==True) & (do_cross==True):
            xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
            xi_12 = TP_estimator(D1D2,D1R,RR,N1,N2,NR,NR,estimator)
            xi_22 = TP_estimator(D2D2,D2R,RR,N2,N2,NR,NR,estimator)
            return xi_11, xi_12, xi_22
        elif do_cross==True:
            xi_12 = TP_estimator(D1D2,D1R,RR,N1,N2,NR,NR,estimator)
            return xi_12
        elif do_auto==True:
            xi_11 = TP_estimator(D1D1,D1R,RR,N1,N1,NR,NR,estimator)
            xi_22 = TP_estimator(D2D2,D2R,RR,N2,N2,NR,NR,estimator)
            return xi_11, xi_22


def projected_cross_two_point_correlation_function(sample1, z, sample2, r_bins, cosmo=None, 
                                                   N_theta_bins=10, randoms=None,
                                                   weights1=None, weights2=None, weights_randoms=None, 
                                                   max_sample_size=int(1e6),
                                                   estimator='Natural',
                                                   N_threads=1, comm=None):
    """ Calculate the projected cross two point correlation function between a spec-z set 
    and a photometric set 
    
    Parameters 
    ----------
    sample1 : array_like
        Npts x 2 numpy array containing ra,dec positions of Npts. 
    
    theta_bins : array_like
        numpy array of boundaries defining the bins in which pairs are counted. 
        len(theta_bins) = N_theta_bins + 1.
    
    sample2 : array_like, optional
        Npts x 2 numpy array containing ra,dec positions of Npts.
    
    randoms : array_like, optional
        Nran x 2 numpy array containing ra,dec positions of Npts.
    
    max_sample_size : int, optional
        Defines maximum size of the sample that will be passed to the pair counter. 
        
        If sample size exeeds max_sample_size, the sample will be randomly down-sampled 
        such that the subsamples are (roughly) equal to max_sample_size. 
        Subsamples will be passed to the pair counter in a simple loop, 
        and the correlation function will be estimated from the median pair counts in each bin.
    
    estimator: string, optional
        options: 'Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay'
    
    N_thread: int, optional
        number of threads to use in calculation.

    comm: mpi Intracommunicator object, optional
    
    do_auto: boolean, optional
        do auto-correlation?
    
    do_cross: boolean, optional
        do cross-correlation?
    
    Returns 
    -------
    angular correlation_function : array_like
        array containing correlation function :math:`\\xi` computed in each of the Nrbins 
        defined by input `rbins`.

        :math:`1 + \\xi(r) \equiv DD / RR`, 
        where `DD` is calculated by the pair counter, and RR is counted by the internally 
        defined `randoms` if no randoms are passed as an argument.

        If sample2 is passed as input, three arrays of length Nrbins are returned: two for
        each of the auto-correlation functions, and one for the cross-correlation function. 

    """
    #####notes#####
    #The pair counter returns all pairs, including self pairs and double counted pairs 
    #with separations less than r. If PBCs are set to none, then period=np.inf. This makes
    #all distance calculations equivalent to the non-periodic case, while using the same 
    #periodic distance functions within the pair counter.
    ###############
    
    do_auto=False
    do_cross=True
    
    if comm!=None:
        rank=comm.rank
    else: rank=0
    if N_threads>1:
        pool = Pool(N_threads)
    
    def list_estimators(): #I would like to make this accessible from the outside. Know how?
        estimators = ['Natural', 'Davis-Peebles', 'Hewett' , 'Hamilton', 'Landy-Szalay']
        return estimators
    estimators = list_estimators()
    
    #process input parameters
    sample1 = np.asarray(sample1)
    if np.all(sample2 != None): sample2 = np.asarray(sample2)
    else: sample2 = sample1
    if np.all(randoms != None): 
        randoms = np.asarray(randoms)
        PBCs = False
    else: PBCs = True #assume full sky coverage
    r_bins = np.asarray(r_bins)
        
    #down sample is sample size exceeds max_sample_size.
    if (len(sample2)>max_sample_size) & (not np.all(sample1==sample2)):
        inds = np.arange(0,len(sample2))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample2 = sample2[inds]
        print('down sampling sample2...')
    if len(sample1)>max_sample_size:
        inds = np.arange(0,len(sample1))
        np.random.shuffle(inds)
        inds = inds[0:max_sample_size]
        sample1 = sample1[inds]
        print('down sampling sample1...')
    
    if np.shape(r_bins) == ():
        theta_bins = np.array([r_bins])
    
    k = 2 #only 2-dimensions: ra,dec
    if np.shape(sample1)[-1] != k:
        raise ValueError('angular correlation function requires 2-dimensional data')
    
    #check for input parameter consistency
    if np.all(sample2 != None) & (sample1.shape[-1]!=sample2.shape[-1]):
        raise ValueError('Sample 1 and sample 2 must have same dimension.')
    if estimator not in estimators: 
        raise ValueError('Must specify a supported estimator. Supported estimators are:{0}'
        .value(estimators))

    #If PBCs are defined, calculate the randoms analytically. Else, the user must specify 
    #randoms and the pair counts are calculated the old fashion way.
    def random_counts(sample1, sample2, randoms, theta_bins, PBCs, N_threads, do_RR, do_DR, comm):
        """
        Count random pairs.
        """
        def cap_area(C):
            """
            Calculate angular area of a spherical cap with chord length c
            """
            theta = 2.0*np.arcsin(C/2.0)
            return 2.0*np.pi*(1.0-np.cos(theta))
        
        #No PBCs, randoms must have been provided.
        if PBCs==False:
            if comm!=None:
                if do_RR==True:
                    if rank==0: print('Running MPI pair counter for RR with {0} processes.'.format(comm.size))
                    RR = specific_wnpairs(randoms, randoms, theta_bins, comm=comm)
                    RR = np.diff(RR)
                else: RR=None
                if do_DR==True:
                    if rank==0: print('Running MPI pair counter for D1R with {0} processes.'.format(comm.size))
                    D1R = specific_wnpairs(sample1, randoms, theta_bins, comm=comm)
                    D1R = np.diff(D1R)
                else: D1R=None
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    print('manually skipping D2R right now.')
                    if True==False:
                    #if do_DR==True:
                        if rank==0: print('Running MPI pair counter for D2R with {0} processes.'.format(comm.size))
                        D2R = specific_wnpairs(sample2, randoms, theta_bins, comm=comm)
                        D2R = np.diff(D2R)
                    else: D2R=None
            elif N_threads==1:
                if do_RR==True:
                    RR = specific_wnpairs(randoms, randoms, theta_bins)
                    RR = np.diff(RR)
                else: RR=None
                if do_DR==True:
                    D1R = specific_wnpairs(sample1, randoms, theta_bins)
                    D1R = np.diff(D1R)
                else: D1R=None
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    if do_DR==True:
                        D2R = specific_wnpairs(sample2, randoms, theta_bins)
                        D2R = np.diff(D2R)
                    else: D2R=None
            else:
                if do_RR==True:
                    args = [[chunk,randoms,theta_bins] for chunk in np.array_split(randoms,N_threads)]
                    RR = np.sum(pool.map(_specific_wnpairs_wrapper,args),axis=0)
                    RR = np.diff(RR)
                else: RR=None
                if do_DR==True:
                    args = [[chunk,randoms,theta_bins] for chunk in np.array_split(sample1,N_threads)]
                    D1R = np.sum(pool.map(_specific_wnpairs_wrapper,args),axis=0)
                    D1R = np.diff(D1R)
                else: D1R=None
                if np.all(sample1 == sample2): #calculating the cross-correlation
                    D2R = None
                else:
                    if do_DR==True:
                        args = [[chunk,randoms,theta_bins] for chunk in np.array_split(sample2,N_threads)]
                        D2R = np.sum(pool.map(_specific_wnpairs_wrapper,args),axis=0)
                        D2R = np.diff(D2R)
                    else: D2R=None
            
            return D1R, D2R, RR
        #PBCs and no randoms--calculate randoms analytically.
        elif PBCs==True:
            #do volume calculations
            dv = cap_area(theta_bins) #volume of spheres
            dv = np.diff(dv) #volume of shells
            global_area = 4.0*np.pi
            
            #calculate randoms for sample1
            N1 = np.shape(sample1)[0]
            rho1 = N1/global_area
            D1R = (N1)*(dv*rho1) #read note about pair counter
            
            #if not calculating cross-correlation, set RR exactly equal to D1R.
            if np.all(sample1 == sample2):
                D2R = None
                RR = D1R #in the analytic case, for the auto-correlation, DR==RR.
            else: #if there is a sample2, calculate randoms for it.
                N2 = np.shape(sample2)[0]
                rho2 = N2/global_area
                D2R = N2*(dv*rho2) #read note about pair counter
                #calculate the random-random pairs.
                NR = N1*N2
                rhor = NR/global_area
                RR = (dv*rhor) #RR is only the RR for the cross-correlation.

            return D1R, D2R, RR
        else:
            raise ValueError('Un-supported combination of PBCs and randoms provided.')
    
    def pair_counts(sample1, sample2, weights1, weights2, theta_bins, N_threads, do_auto, do_cross, do_DD, comm):
        """
        Count data pairs: D1D1, D1D2, D2D2.  If a comm object is passed, the code uses a
        MPI pair counter.  Else if N_threads==1, the calculation is done serially.  Else,
        the calculation is done on N_threads threads. 
        """
        if comm!=None:
            if do_auto==True:
                if rank==0: print('Running MPI pair counter for D1D1 with {0} processes.'.format(comm.size))
                D1D1 = specific_wnpairs(sample1, sample1, theta_bins, period=None, weights1=weights1, weights2=weights2, wf=None, comm=comm)
                D1D1 = np.diff(D1D1)
            else: D1D1=None
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                if do_cross==True:
                    if rank==0: print('Running MPI pair counter for D1D2 with {0} processes.'.format(comm.size))
                    D1D2 = specific_wnpairs(sample1, sample2, theta_bins, period=None, weights1=weights1, weights2=weights2, wf=None, comm=comm)
                    D1D2 = np.diff(D1D2)
                else: D1D2=None
                if do_auto==True:
                    if rank==0: print('Running MPI pair counter for D2D2 with {0} processes.'.format(comm.size))
                    D2D2 = specific_wnpairs(sample2, sample2, theta_bins, period=None, weights1=weights2, weights2=weights2, wf=None, comm=comm)
                    D2D2 = np.diff(D2D2)
                else: D2D2=False
        elif N_threads==1:
            if do_auto==True:
                D1D1 = specific_wnpairs(sample1, sample1, theta_bins, period=None, weights1=weights1, weights2=weights1, wf=None)
                D1D1 = np.diff(D1D1)
            else: D1D1=None
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                if do_cross==True:
                    D1D2 = specific_wnpairs(sample1, sample2, theta_bins, period=None, weights1=weights1, weights2=weights2, wf=None)
                    D1D2 = np.diff(D1D2)
                else: D1D2=None
                if do_auto==True:
                    D2D2 = specific_wnpairs(sample2, sample2, theta_bins, period=None, weights1=weights2, weights2=weights2, wf=None)
                    D2D2 = np.diff(D2D2)
                else: D2D2=False
        else:
            inds1 = np.arange(0,len(sample1)) #indices into sample1
            inds2 = np.arange(0,len(sample2)) #indices into sample2
            if do_auto==True:
                #split sample1 into subsamples for list of args to pass to the pair counter
                args = [[sample1[chunk],sample1,theta_bins, None, weights1[chunk], weights1, None] for chunk in np.array_split(inds1,N_threads)]
                D1D1 = np.sum(pool.map(_specific_wnpairs_wrapper,args),axis=0)
                D1D1 = np.diff(D1D1)
            else: D1D1=None
            if np.all(sample1 == sample2):
                D1D2 = D1D1
                D2D2 = D1D1
            else:
                if do_cross==True:
                    #split sample1 into subsamples for list of args to pass to the pair counter
                    args = [[sample1[chunk],sample2,theta_bins, None, weights1[chunk], weights2, None] for chunk in np.array_split(inds1,N_threads)]
                    D1D2 = np.sum(pool.map(_specific_wnpairs_wrapper,args),axis=0)
                    D1D2 = np.diff(D1D2)
                else: D1D2=None
                if do_auto==True:
                   #split sample2 into subsamples for list of args to pass to the pair counter
                    args = [[sample2[chunk],sample2,theta_bins, None, weights2[chunk], weights2, None] for chunk in np.array_split(inds2,N_threads)]
                    D2D2 = np.sum(pool.map(_specific_wnpairs_wrapper,args),axis=0)
                    D2D2 = np.diff(D2D2)
                else: D2D2=None

        return D1D1, D1D2, D2D2
        
    def TP_estimator(DD,DR,RR,ND1,ND2,NR1,NR2,estimator):
        """
        two point correlation function estimator
        """
        if estimator == 'Natural': #DD/RR-1
            factor = ND1*ND2/(NR1*NR2)
            xi = (1.0/factor)*DD/RR - 1.0
        elif estimator == 'Davis-Peebles': #DD/DR-1
            factor = ND1*ND2/(ND1*NR2)
            xi = (1.0/factor)*DD/DR - 1.0
        elif estimator == 'Hewett': #(DD-DR)/RR
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*DR/RR 
        elif estimator == 'Hamilton': #DDRR/DRDR-1
            xi = (DD*RR)/(DR*DR) - 1.0
        elif estimator == 'Landy-Szalay': #(DD - 2.0*DR + RR)/RR
            factor1 = ND1*ND2/(NR1*NR2)
            factor2 = ND1*NR2/(NR1*NR2)
            xi = (1.0/factor1)*DD/RR - (1.0/factor2)*2.0*DR/RR + 1.0
        else: 
            raise ValueError("unsupported estimator!")
        return xi
    
    def TP_estimator_requirements(estimator):
        """
        return booleans indicating which pairs need to be counted for the chosen estimator
        """
        if estimator == 'Natural':
            do_DD = True
            do_DR = False
            do_RR = True
        elif estimator == 'Davis-Peebles':
            do_DD = True
            do_DR = True
            do_RR = False
        elif estimator == 'Hewett':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Hamilton':
            do_DD = True
            do_DR = True
            do_RR = True
        elif estimator == 'Landy-Szalay':
            do_DD = True
            do_DR = True
            do_RR = True
        else: 
            raise ValueError("unsupported estimator!")
        return do_DD, do_DR, do_RR
              
    if np.all(randoms != None):
        N1 = len(sample1)
        N2 = len(sample2)
        NR = len(randoms)
    else: 
        N1 = 1.0
        N2 = 1.0
        NR = 1.0
    
    def proj_r_to_angular_bins(r_bins, z, N_sample, cosmo):
        """
        define angular bins given r_proj bins and redshift range.
        parameters
            r_bins: np.array, projected radial bins in Mpc
            N_sample: int, oversample rate of theta bins
            cosmo: astropy cosmology object defining cosmology
        returns:
            theta_bins: np.array, angular bins in radians
        """
    
        N_r_bins = len(r_bins)
        N_theta_bins = N_sample * N_r_bins
    
        #find maximum theta
        X_min = cosmo.comoving_distance(np.min(z)).value
        max_theta = np.max(r_bins)/(X_min/(1.0+np.min(z)))
    
        #find minimum theta
        X_max = cosmo.comoving_distance(np.max(z)).value
        min_theta = np.min(r_bins)/(X_max/(1.0+np.max(z)))
    
        theta_bins = np.linspace(np.log10(min_theta), np.log10(max_theta), N_theta_bins)
        theta_bins = 10.0**theta_bins
    
        return theta_bins*180.0/np.pi
    
    do_DD, do_DR, do_RR = TP_estimator_requirements(estimator)
    
    theta_bins = proj_r_to_angular_bins(r_bins, z, N_theta_bins, cosmo)
    if rank==0:
        print("bins")
        print(r_bins)
        print(theta_bins)
    
    #convert angular coordinates into cartesian coordinates
    from halotools.utils.spherical_geometry import spherical_to_cartesian, chord_to_cartesian
    xyz_1 = np.empty((len(sample1),3))
    xyz_2 = np.empty((len(sample2),3))
    xyz_1[:,0],xyz_1[:,1],xyz_1[:,2] = spherical_to_cartesian(sample1[:,0], sample1[:,1])
    xyz_2[:,0],xyz_2[:,1],xyz_2[:,2] = spherical_to_cartesian(sample2[:,0], sample2[:,1])
    if PBCs==False:
        xyz_randoms = np.empty((len(randoms),3))
        xyz_randoms[:,0],xyz_randoms[:,1],xyz_randoms[:,2] = spherical_to_cartesian(randoms[:,0], randoms[:,1])
    else: xyz_randoms=None
    
    #convert angular bins to cartesian distances
    c_bins = chord_to_cartesian(theta_bins, radians=False)
    
    #count pairs
    if rank==0: print('counting data pairs...')
    D1D1,D1D2,D2D2 = pair_counts(xyz_1, xyz_2, weights1, weights2, c_bins, N_threads, do_auto, do_cross, do_DD, comm)
    if rank==0: print('counting random pairs...')
    D1R, D2R, RR = random_counts(xyz_1, xyz_2, xyz_randoms, c_bins, PBCs, N_threads, do_RR, do_DR, comm)
    if rank==0: print('done counting pairs.')
    
    #covert angular pair counts to projected pair counts
    #comoving distance to sample 1
    X = cosmo.comoving_distance(z).value
    
    proj_D1D2 = np.zeros(len(r_bins)) #pair count storage array
    proj_D1R = np.zeros(len(r_bins)) #pair count storage array
    N1 = len(sample1)
    for j in range(0,N1):
        r_proj = X[j]/(1.0+z[j])*np.radians(theta_bins)
        k_ind = np.searchsorted(r_bins,r_proj)-1
        for k in range(0,len(theta_bins)-1):
            #if k_ind[k]<len(r_bins):
            proj_D1D2[k_ind[k]] += D1D2[j,k]
            proj_D1R[k_ind[k]] += D1R[j,k]
    
    proj_D1D2 = proj_D1D2[:-1]
    proj_D1R = proj_D1R[:-1]
    
    if rank==0:
        print(proj_D1D2)
        print(proj_D1R)
    
    
    xi_12 = TP_estimator(proj_D1D2,proj_D1R,None,N1,N2,NR,NR,estimator)
    return xi_12

def Delta_Sigma(centers, particles, rbins, bounds=[-0.1,0.1], normal=[0.0,0.0,1.0],
                randoms=None, period=None, N_threads=1):
    """
    Calculate the galaxy-galaxy lensing signal, $\Delata\Sigma$.
    
    Parameters
    ----------
    centers: array_like
    
    particles: array_like
    
    rbins: array_like
    
    bounds: array_like, optional
    
    normal: array_like, optional
    
    randoms: array_like, optional
    
    period: array_like, optional
    
    N_threads: int, optional
    
    
    Returns
    -------
    
    Delata_Sigma: np.array
    """
    from halotools.mock_observables.spatial.geometry import inside_volume
    from halotools.mock_observables.spatial.geometry import cylinder
    from halotools.mock_observables.spatial.kdtrees.ckdtree import cKDTree
    
    if period is None:
            PBCs = False
            period = np.array([np.inf]*np.shape(sample1)[-1])
    else:
        PBCs = True
        period = np.asarray(period).astype("float64")
        if np.shape(period) == ():
            period = np.array([period]*np.shape(centers)[-1])
        elif np.shape(period)[0] != np.shape(centers)[-1]:
            raise ValueError("period should have shape (k,)")
    
    normal = np.asarray(normal)
    bounds = np.asarray(bounds)
    centers = np.asarray(centers)
    
    N_targets = len(centers)
    length = bounds[1]-bounds[0]
    
    #create cylinders
    cyls = np.ndarray((N_targets,len(rbins)),dtype=object)
    for i in range(0,N_targets):
        for j in range(0,len(rbins)):
            cyls[i,j] = geometry.cylinder(center=centers[i], radius = rbins[j], length=length, normal=normal)
    
    #calculate the number of particles inside each cylinder 
    tree = cKDTree(particles)
    N = np.ndarray((len(centers),len(rbins)))
    print 'here'
    for j in range(0,len(rbins)):
        dum1, dum2, dum3, N[:,j] = inside_volume(cyls[:,j].tolist(), tree, period=period)
    print 'here here'
    #numbers in annular bins, N
    N = np.diff(N,axis=1)
    
    #area of a annular ring, A
    A = np.pi*rbins**2.0
    A = np.diff(A)
    print A
    
    #calculate the surface density in annular bins, Sigma
    Sigma = N/A
    
    delta_Sigma = np.zeros((N_targets,len(rbins)-1))
    
    for target in range(0,N_targets):
        #loop over each each radial bin
        for i in range(1,len(rbins)-1):
            outer = 1.0/(np.pi*rbins[i]**2.0)
            inner_sum=0.0
            #loop over annular bins internal to the ith one.
            for n in range(0,i):
                inner_sum += Sigma[target,n]*A[n]-Sigma[target,i]
            delta_Sigma[target,i] = inner_sum*outer
    
    return np.mean(delta_Sigma, axis=0)


def apparent_to_absolute_magnitude(m, d_L):
    """
    calculate the absolute magnitude
    
    Parameters
    ----------
    m: array_like
        apparent magnitude
    
    d_L: array_like
        luminosity distance to object
    
    Returns
    -------
    Mag: np.array of absolute magnitudes
    """
    
    M = m - 5.0*(np.log10(d_L)+5.0)
    
    return M


def luminosity_to_absolute_magnitude(L, band, system='SDSS_Blanton_2003_z0.1'):
    """
    calculate the absolute magnitude
    
    Parameters
    ----------
    L: array_like
        apparent magnitude
    
    band: string
       filter band
    
    system: string, optional
        filter systems: default is 'SDSS_Blanton_2003_z0.1'
          1. Binney_and_Merrifield_1998
          2. SDSS_Blanton_2003_z0.1
    
    Returns
    -------
    Mag: np.array of absolute magnitudes
    """
    
    Msun = get_sun_mag(band,system)
    Lsun = 1.0
    M = -2.5*np.log10(L/Lsun) + Msun
            
    return M


def get_sun_mag(filter,system):
    """
    get the solar value for a filter in a system.
    
    Parameters
    ----------
    filter: string
    
    system: string
    
    Returns
    -------
    Msun: float
    """
    if system=='Binney_and_Merrifield_1998':
    #see Binney and Merrifield 1998
        if filter=='U':
            return 5.61
        elif filter=='B':
            return 5.48
        elif filter=='V':
            return 4.83
        elif filter=='R':
            return 4.42
        elif filter=='I':
            return 4.08
        elif filter=='J':
            return 3.64
        elif filter=='H':
            return 3.32
        elif filter=='K':
            return 3.28
        else:
            raise ValueError('Filter does not exist in this system.')
    if system=='SDSS_Blanton_2003_z0.1':
    #see Blanton et al. 2003 equation 14
        if filter=='u':
            return 6.80
        elif filter=='g':
            return 5.45
        elif filter=='r':
            return 4.76
        elif filter=='i':
            return 4.58
        elif filter=='z':
            return 4.51
        else:
            raise ValueError('Filter does not exist in this system.')
    else:
        raise ValueError('Filter system not included in this package.')


def luminosity_function(m, z, band, cosmo, system='SDSS_Blanton_2003_z0.1', L_bins=None):
    """
    Calculate the galaxy luminosity function.
    
    Parameters
    ----------
    m: array_like
        apparent magnitude of galaxies
    
    z: array_like
        redshifts of galaxies
    
    band: string
        filter band
    
    cosmo: astropy.cosmology object 
        specifies the cosmology to use, default is FlatLambdaCDM(H0=70, Om0=0.3)
    
    system: string, optional
        filter systems: default is 'SDSS_Blanton_2003_z0.1'
          1. Binney_and_Merrifield_1998
          2. SDSS_Blanton_2003_z0.1
    
    L_bins: array_like, optional
        bin edges to use for for the luminosity function. If None is given, "Scott's rule"
        is used where delta_L = 3.5sigma/N**(1/3)
    
    Returns
    -------
    counts, L_bins: np.array, np.array
    """
    
    from astropy import cosmology
    d_L = cosmo.luminosity_distance(z)
    
    M = apparant_to_absolute_magnitude(m,d_L)
    Msun = get_sun_mag(filter,system)
    L = 10.0**((Msun-M)/2.5)
    
    #determine Luminosity bins
    if L_bins==None:
        delta_L = 3.5*np.std(L)/float(L.shape[0]) #scott's rule
        Nbins = np.ceil((np.max(L)-np.min(L))/delta_L)
        L_bins = np.linspace(np.min(L),np.max(L),Nbins)
    
    counts = np.histogram(L,L_bins)[0]
    
    return counts, L_bins


def HOD(mock,galaxy_mask=None, mass_bins=None):
    """
    Calculate the galaxy HOD.
    
    Parameters
    ----------
    mock: mock object
    
    galaxy_mask: array_like, optional
        boolean array specifying subset of galaxies for which to calculate the HOD.
    
    mass_bins: array_like, optional
        array indicating bin edges to use for HOD calculation
    
    Returns
    -------
    N_avg, mass_bins: np.array, np.array
        mean number of galaxies per halo within the bin defined by bins, bin edges
    """
    
    from halotools.utils import match
    
    if not hasattr(mock, 'halos'):
        raise ValueError('mock must contain halos.')
    if not hasattr(mock, 'galaxies'):
        raise ValueError('mock must contain galaxies. execute mock.populate().')
    
    if galaxy_mask != None:
        if len(galaxy_mask) != len(mock.galaxies):
            raise ValueError('galaxy mask be the same length as mock.galaxies')
        elif x.dtype != bool:
            raise TypeError('galaxy mask must be of type bool')
        else:
            galaxies = mock.galaxies[galaxy_mask]
    else:
        galaxies = np.array(mock.galaxies)
    
    galaxy_to_halo = match(galaxies['haloID'],halo['ID'])
    
    galaxy_halos = halos[galaxy_to_halo]
    unq_IDs, unq_inds = np.unique(galaxy_halos['ID'], return_index=True)
    Ngals_in_halo = np.bincount(galaxy_halos['ID'])
    Ngals_in_halo = Ngals_in_halo[galaxy_halos['ID']]
    
    Mhalo = galaxy_haloes[unq_inds]
    Ngals = Ngals_in_halo[unq_inds]
    
    inds_in_bins = np.digitize(Mhalo,mass_bins)
    
    N_avg = np.zeros((len(mass_bins)-1,))
    for i in range(0,len(N_avg)):
        inds = np.where(inds_in_bins==i+1)[0]
        Nhalos_in_bin = float(len(inds))
        Ngals_in_bin = float(sum(Ngal[inds]))
        if Nhalos_in_bin==0: N_avg[i]=0.0
        else: N_avg[i] = Ngals_in_bin/Nhalos_in_bin
    
    return N_avg, mass_bins
    
    pass


def CLF(mock):
    """
    Calculate the galaxy CLF.
    """
    pass


def CSMF(mock):
    """
    Calculate the galaxy CSMF.
    """
    pass


from halotools.mock_observables.spatial import geometry
class isolatoion_criterion(object):
    """
    A object that defines a galaxy isolation criterion.
    
    Parameters 
    ----------
    volume: geometry volume object
        e.g. sphere, cylinder
    
    vol_args: list or function
        arguments to initialize the volume objects defining the test region of isolated 
        candidates, or function taking a galaxy object which returns the vol arguments.
    
    test_prop: string
        mock property to test isolation against.  e.g. 'M_r', 'Mstar', etc.
        
    test_func: function
        python function defining the property isolation test.
    """
    
    def __init__(self, volume=geometry.sphere, vol_args=None,
                 test_prop='primary_galprop', test_func=None):
        #check to make sure the volume object passed is in fact a volume object 
        if not issubclass(volume,geometry.volume):
            raise ValueError('volume object must be a subclass of geometry.volume')
        else: self.volume = volume
        #check volume object arguments. Is it None, a function, or a list?
        if vol_args==None:
            #default only passes center argument to volume object
            def default_func(galaxy):
                center = galaxy['coords']
                return center
            self.vol_agrs = default_func
        elif hasattr(vol_args, '__call__'):
            self.vol_args= vol_args
            #check for compatibility with the mock in the method
        else:
            #else, return the list of values passes in every time.
            def default_func(galaxy):
                return vol_agrs
            self.vol_agrs = default_func
        #store these two and check if they are compatible with a mock later in the method.
        self.test_prop = test_prop
        self.test_func = test_func
    
    def make_volumes(self, galaxies, isolated_candidates):
        volumes = np.empty((len(isolated_candidates),))
        for i in range(0,len(isolated_candidates)):
            volumes[i] = self.volume(self.vol_args(galaxies[isolated_candidates[i]]))
        return volumes

    def apply_criterion(self, mock, isolated_candidates):
        """
        Return galaxies which pass isolation criterion. 
    
        Parameters 
        ----------
        mock: galaxy mock object
    
        isolated_candidates: array_like
            indices of mock galaxy candidates to test for isolation.
        
        Returns 
        -------
        inds: numpy.array
            indicies of galaxies in mock that pass the isolation criterion.

        """
        
        #check input
        if not hasattr(mock, 'galaxies'):
            raise ValueError('mock must contain galaxies. execute mock.populate()')
        if self.test_prop not in mock.galaxies.dtype.names:
            raise ValueError('test_prop not present in mock.galaxies table.')
        try: self.volume(self.vol_args(mock.galaxies[0]))
        except TypeError: print('vol_args are not compatable with the volume object.')
        
        volumes = make_volumes(self,mock.galaxies,isolated_candidates)
        
        points_inside_shapes = geometry.inside_volume(
                               volumes, mock.coords[neighbor_candidates], period=mock.Lbox
                               )[2]
        
        ioslated = np.array([True]*len(isolated_candidates))
        for i in range(0,len(isolated_candidates)):
            inside = points_inside_shapes[i] 
            isolated[i] = np.all(self.test_func(mock.galaxies[isolated_candidates[i]][self.test_prop],mock.galaxies[inside][self.test_prop]))
        
        return isolated



