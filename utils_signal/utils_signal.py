# -*- coding: utf-8 -*-
"""
utilities for signal processing, which numpy, scipy, etc. lack
"""
from copy import deepcopy
from collections import namedtuple
from itertools import repeat
from numbers import Number, Real
from typing import Union, List, NamedTuple, Optional, Tuple, Sequence, Any, NoReturn

import numpy as np
np.set_printoptions(precision=5, suppress=True)
import pywt
import scipy
from math import atan2, factorial
from scipy import interpolate
from scipy.signal import butter, lfilter, filtfilt, peak_prominences
try:
    from numba import jit
except:
    from utils.utils_misc import trivial_jit as jit

from ..common import ArrayLike, ArrayLike_Int


__all__ = [
    "detect_peaks",
    "phasor_transform",
    "uni_polyn_der",
    "eval_uni_polyn",
    "noise_std_estimator",
    "lstsq_with_smoothness_prior",
    "compute_snr",
    "compute_snr_improvement",
    "is_ecg_signal",
    "WaveletDenoiseResult",
    "wavelet_denoise",
    "wavelet_rec_iswt",
    "resample_irregular_timeseries",
    "resample_discontinuous_irregular_timeseries",
    "butter_bandpass",
    "butter_bandpass_filter",
    "hampel",
    "detect_flat_lines",
    "MovingAverage", "smooth",
    "gen_gaussian_noise", "gen_sinusoidal_noise", "gen_baseline_wander",
    "remove_spikes_naive",
    "ensure_lead_fmt", "ensure_siglen",
    "get_ampl",
]


WaveletDenoiseResult = namedtuple(
    typename="WaveletDenoiseResult",
    field_names=["is_ecg", "amplified_ratio", "amplified_signal", "raw_r_peaks", "side_len", "wavelet_name", "wavelet_coeffs"]
)


def detect_peaks(x:ArrayLike,
                 mph:Optional[Real]=None, mpd:int=1,
                 threshold:Real=0, left_threshold:Real=0, right_threshold:Real=0,
                 prominence:Optional[Real]=None, prominence_wlen:Optional[int]=None,
                 edge:Union[str,type(None)]="rising", kpsh:bool=False, valley:bool=False,
                 show:bool=False, ax=None,
                 verbose:int=0) -> np.ndarray:
    """
    Detect peaks in data based on their amplitude and other features.

    Parameters
    ----------
    x: 1D array_like,
        data
    mph: positive number, optional,
        abbr. for maximum (minimum) peak height,
        detect peaks that are greater than minimum peak height (if parameter `valley` is False),
        or peaks that are smaller than maximum peak height (if parameter `valley` is True)
    mpd: positive integer, default 1,
        abbr. for minimum peak distance,
        detect peaks that are at least separated by minimum peak distance (in number of samples)
    threshold: positive number, default 0,
        detect peaks (valleys) that are greater (smaller) than `threshold`,
        in relation to their neighbors within the range of `mpd`
    left_threshold: positive number, default 0,
        `threshold` that is restricted to the left
    right_threshold: positive number, default 0,
        `threshold` that is restricted to the left
    prominence: positive number, optional,
        threshold of prominence of the detected peaks (valleys)
    prominence_wlen: positive int, optional,
        the `wlen` parameter of the function `scipy.signal.peak_prominences`
    edge: str or None, default "rising",
        can also be "falling", "both",
        for a flat peak, keep only the rising edge ("rising"), only the falling edge ("falling"),
        both edges ("both"), or don't detect a flat peak (None)
    kpsh: bool, default False,
        keep peaks with same height even if they are closer than `mpd`
    valley: bool, default False,
        if True (1), detect valleys (local minima) instead of peaks
    show: bool, default False,
        if True (1), plot data in matplotlib figure
    ax: a matplotlib.axes.Axes instance, optional,

    Returns
    -------
    ind : 1D array_like
        indeces of the peaks in `x`.

    Notes
    -----
    The detection of valleys instead of peaks is performed internally by simply
    negating the data: `ind_valleys = detect_peaks(-x)`
    
    The function can handle NaN's 

    See this IPython Notebook [1]_.

    References
    ----------
    [1] http://nbviewer.ipython.org/github/demotu/BMC/blob/master/notebooks/DetectPeaks.ipynb

    Examples
    --------
    >>> from detect_peaks import detect_peaks
    >>> x = np.random.randn(100)
    >>> x[60:81] = np.nan
    >>> # detect all peaks and plot data
    >>> ind = detect_peaks(x, show=True)
    >>> print(ind)

    >>> x = np.sin(2*np.pi*5*np.linspace(0, 1, 200)) + np.random.randn(200)/5
    >>> # set minimum peak height = 0 and minimum peak distance = 20
    >>> detect_peaks(x, mph=0, mpd=20, show=True)

    >>> x = [0, 1, 0, 2, 0, 3, 0, 2, 0, 1, 0]
    >>> # set minimum peak distance = 2
    >>> detect_peaks(x, mpd=2, show=True)

    >>> x = np.sin(2*np.pi*5*np.linspace(0, 1, 200)) + np.random.randn(200)/5
    >>> # detection of valleys instead of peaks
    >>> detect_peaks(x, mph=-1.2, mpd=20, valley=True, show=True)

    >>> x = [0, 1, 1, 0, 1, 1, 0]
    >>> # detect both edges
    >>> detect_peaks(x, edge="both", show=True)

    >>> x = [-2, 1, -2, 2, 1, 1, 3, 0]
    >>> # set threshold = 2
    >>> detect_peaks(x, threshold = 2, show=True)

    Version history
    ---------------
    "1.0.5":
        The sign of `mph` is inverted if parameter `valley` is True
    """
    data = deepcopy(x)
    data = np.atleast_1d(data).astype("float64")
    if data.size < 3:
        return np.array([], dtype=int)
    
    if valley:
        data = -data
        if mph is not None:
            mph = -mph

    # find indices of all peaks
    dx = data[1:] - data[:-1]  # equiv to np.diff()

    # handle NaN's
    indnan = np.where(np.isnan(data))[0]
    if indnan.size:
        data[indnan] = np.inf
        dx[np.where(np.isnan(dx))[0]] = np.inf
    
    ine, ire, ife = np.array([[], [], []], dtype=int)
    if not edge:
        ine = np.where((np.hstack((dx, 0)) < 0) & (np.hstack((0, dx)) > 0))[0]
    else:
        if edge.lower() in ["rising", "both"]:
            ire = np.where((np.hstack((dx, 0)) <= 0) & (np.hstack((0, dx)) > 0))[0]
        if edge.lower() in ["falling", "both"]:
            ife = np.where((np.hstack((dx, 0)) < 0) & (np.hstack((0, dx)) >= 0))[0]
    ind = np.unique(np.hstack((ine, ire, ife)))

    if verbose >= 1:
        print(f"before filtering by mpd = {mpd}, and threshold = {threshold}, ind = {ind.tolist()}")
        print(f"additionally, left_threshold = {left_threshold}, right_threshold = {right_threshold}, length of data = {len(data)}")
    
    # handle NaN's
    if ind.size and indnan.size:
        # NaN's and values close to NaN's cannot be peaks
        ind = ind[np.in1d(ind, np.unique(np.hstack((indnan, indnan-1, indnan+1))), invert=True)]

    if verbose >= 1:
        print(f"after handling nan values, ind = {ind.tolist()}")
    
    # peaks are only valid within [mpb, len(data)-mpb[
    ind = np.array([pos for pos in ind if mpd<=pos<len(data)-mpd])
    
    if verbose >= 1:
        print(f"after fitering out elements too close to border by mpd = {mpd}, ind = {ind.tolist()}")

    # first and last values of data cannot be peaks
    # if ind.size and ind[0] == 0:
    #     ind = ind[1:]
    # if ind.size and ind[-1] == data.size-1:
    #     ind = ind[:-1]
    # remove peaks < minimum peak height
    if ind.size and mph is not None:
        ind = ind[data[ind] >= mph]
    
    if verbose >= 1:
        print(f"after filtering by mph = {mph}, ind = {ind.tolist()}")
    
    # remove peaks - neighbors < threshold
    _left_threshold = left_threshold if left_threshold > 0 else threshold
    _right_threshold = right_threshold if right_threshold > 0 else threshold
    if ind.size and (_left_threshold > 0 and _right_threshold > 0):
        # dx = np.min(np.vstack([data[ind]-data[ind-1], data[ind]-data[ind+1]]), axis=0)
        dx = np.max(np.vstack([data[ind]-data[ind+idx] for idx in range(-mpd, 0)]), axis=0)
        ind = np.delete(ind, np.where(dx < _left_threshold)[0])
        if verbose >= 2:
            print(f"from left, dx = {dx.tolist()}")
            print(f"after deleting those dx < _left_threshold = {_left_threshold}, ind = {ind.tolist()}")
        dx = np.max(np.vstack([data[ind]-data[ind+idx] for idx in range(1, mpd+1)]), axis=0)
        ind = np.delete(ind, np.where(dx < _right_threshold)[0])
        if verbose >= 2:
            print(f"from right, dx = {dx.tolist()}")
            print(f"after deleting those dx < _right_threshold = {_right_threshold}, ind = {ind.tolist()}")
    if verbose >= 1:
        print(f"after filtering by threshold, ind = {ind.tolist()}")
    # detect small peaks closer than minimum peak distance
    if ind.size and mpd > 1:
        ind = ind[np.argsort(data[ind])][::-1]  # sort ind by peak height
        idel = np.zeros(ind.size, dtype=bool)
        for i in range(ind.size):
            if not idel[i]:
                # keep peaks with the same height if kpsh is True
                idel = idel | (ind >= ind[i] - mpd) & (ind <= ind[i] + mpd) \
                    & (data[ind[i]] > data[ind] if kpsh else True)
                idel[i] = 0  # Keep current peak
        # remove the small peaks and sort back the indices by their occurrence
        ind = np.sort(ind[~idel])
    
    ind = np.array([item for item in ind if data[item]==np.max(data[item-mpd:item+mpd+1])])

    if verbose >= 1:
        print(f"after filtering by mpd, ind = {ind.tolist()}")

    if prominence:
        _p = peak_prominences(data, ind, prominence_wlen)[0]
        ind = ind[np.where(_p >= prominence)[0]]
        if verbose >= 1:
            print(f"after filtering by prominence, ind = {ind.tolist()}")
            if verbose >= 2:
                print(f"with detailed prominence = {_p.tolist()}")

    if show:
        if indnan.size:
            data[indnan] = np.nan
        if valley:
            data = -data
            if mph is not None:
                mph = -mph
        _plot(data, mph, mpd, threshold, edge, valley, ax, ind)

    return ind


def _plot(x, mph, mpd, threshold, edge, valley, ax, ind):
    """
    Plot results of the detect_peaks function, see its help.

    Parameters ref. the function `detect_peaks`
    """
    if "plt" not in dir():
        import matplotlib.pyplot as plt
    
    if ax is None:
        _, ax = plt.subplots(1, 1, figsize=(8, 4))

    ax.plot(x, "b", lw=1)
    if ind.size:
        label = "valley" if valley else "peak"
        label = label + "s" if ind.size > 1 else label
        ax.plot(ind, x[ind], "+", mfc=None, mec="r", mew=2, ms=8,
                label="%d %s" % (ind.size, label))
        ax.legend(loc="best", framealpha=.5, numpoints=1)
    ax.set_xlim(-.02*x.size, x.size*1.02-1)
    ymin, ymax = x[np.isfinite(x)].min(), x[np.isfinite(x)].max()
    yrange = ymax - ymin if ymax > ymin else 1
    ax.set_ylim(ymin - 0.1*yrange, ymax + 0.1*yrange)
    ax.set_xlabel("Data #", fontsize=14)
    ax.set_ylabel("Amplitude", fontsize=14)
    mode = "Valley detection" if valley else "Peak detection"
    ax.set_title("%s (mph=%s, mpd=%d, threshold=%s, edge='%s')"
                    % (mode, str(mph), mpd, str(threshold), edge))
    # plt.grid()
    plt.show()


def phasor_transform(s:ArrayLike, rv:Real) -> np.ndarray:
    """ finished, checked,

    phasor transform, applied to `s`, with sensitivity controlled by `rv`

    Reference
    ---------
    [1] Maršánová L, Němcová A, Smíšek R, et al. Automatic Detection of P Wave in ECG During Ventricular Extrasystoles[C]//World Congress on Medical Physics and Biomedical Engineering 2018. Springer, Singapore, 2019: 381-385.
    """
    return np.vectorize(atan2)(s,rv)


def compute_snr(original:ArrayLike, noised:ArrayLike) -> float:
    """
    computation of signal to noise ratio of the noised signal

    Parameters
    ----------
    original: array_like,
        the original signal
    noised: array_like,
        the noise component of the original signal

    Returns
    -------
    snr, float,
        the signal-to-noise ration of the signal `original`
    """
    snr = 10*np.log10(np.sum(np.power(np.array(original),2))/np.sum(np.power(np.array(original)-np.array(noised),2)))
    return snr


def compute_snr_improvement(original:ArrayLike, noised:ArrayLike, denoised:ArrayLike) -> float:
    """
    computation of the improvement of signal to noise ratio of the denoised signal,
    compared to the noised signal

    Parameters
    ----------
    original: array_like,
        the original signal
    noised: array_like,
        the noise component of the original signal
    denoised: array_like,
        denoised signal of `original`

    Returns
    -------
    snr, float,
        the signal-to-noise ration of the signal `original`
    """
    return 10*np.log10(np.sum(np.power(np.array(original)-np.array(noised),2))/np.sum(np.power(np.array(original)-np.array(denoised),2)))


def uni_polyn_der(coeff:ArrayLike, order:int=1, coeff_asc:bool=True) -> np.ndarray:
    """ finished, checked,

    compute the order-th derivative of a univariate polynomial with real (int,float) coefficients,
    faster than np.polyder

    for testing speed:
    >>> from timeit import timeit
    >>> print(timeit(lambda : np.polyder([1,2,3,4,5,6,7],5), number=100000))
    >>> print(timeit(lambda : uni_polyn_der([1,2,3,4,5,6,7],5), number=100000))

    Parameters
    ----------
    coeff: array like,
        coefficients of the univariate polynomial,
    order: non negative integer
        order of the derivative
    coeff_asc: bool
        coefficients in ascending order (a_0,a_1,...,a_n) or not (descending order, a_n,...,a_0)
    
    Returns
    -------
    der: np.ndarray
        coefficients of the order-th derivative
    """
    dtype = float if any([isinstance(item, float) for item in coeff]) else int
    _coeff = np.array(coeff,dtype=dtype)
    polyn_deg = len(_coeff) - 1

    if order < 0 or not isinstance(order, int):
        raise ValueError("order must be a non negative integer")
    elif order == 0:
        return _coeff
    elif order > polyn_deg:
        return np.zeros(1).astype(dtype)
    
    if coeff_asc:
        tmp = np.array([factorial(n)/factorial(n-order) for n in range(order,polyn_deg+1)],dtype=int)
        der = _coeff[order:]*tmp
    else:
        der = uni_polyn_der(_coeff[::-1], order, coeff_asc=True)[::-1]
    return der


def eval_uni_polyn(x:Union[Real,list,tuple,np.ndarray],
                   coeff:ArrayLike,
                   coeff_asc:bool=True) -> Union[int,float,np.ndarray]:
    """ finished, checked,

    evaluate `x` at the univariate polynomial defined by `coeff`

    Parameters
    ----------
    x: real number or array_like,
        the value(s) for the the univariate polynomial to evaluate at
    coeff: array_like,
        the coefficents which defines the univariate polynomial
    coeff_asc: bool, default True,
        if True, the degrees of the monomials corr. to the coefficients is in ascending order,
        otherwise, in descending order

    Returns
    -------
    value_at_x: real number or sequence of real numbers,
        value(s) of the univariate polynomial defined by `coeff` at point(s) of `x`
    """
    polyn_order = len(coeff)-1
    if len(coeff) == 0:
        raise ValueError("please specify a univariate polynomial!")
    
    if coeff_asc:
        if isinstance(x, (int,float)):
            value_at_x = \
                np.sum(np.array(coeff)*np.array([np.power(x,k) for k in range(polyn_order+1)]))
        else:
            value_at_x = np.array([eval_uni_polyn(p, coeff) for p in x])
    else:
        value_at_x = eval_uni_polyn(x, coeff[::-1], coeff_asc=True)
    return value_at_x


def noise_std_estimator(data:ArrayLike) -> float:
    """ finished, checked,

    median estimator for the unknown std of the noise

    Parameters
    ----------
    data: array_like,
        the input signal

    Returns
    -------
    estimation: float,
        the estimated standard deviation of the noised data

    Reference
    ---------
    [1] Katkovnik V, Stankovic L. Instantaneous frequency estimation using the Wigner distribution with varying and data-driven window length[J]. IEEE Transactions on signal processing, 1998, 46(9): 2315-2325.
    """
    estimation = np.median(np.abs(np.diff(data))) / 0.6745
    return estimation


def der_operator(responce_len:int, input_len:int, order:int) -> np.ndarray:
    """ not finished,

    derivation operator in matrix form

    Parameters
    ----------
    responce_len: int
    input_len: int
    order:int

    Returns
    -------
    to write
    """
    if responce_len+order > input_len:
        raise ValueError("responce_len+order should be no greater than input_len")

    raise NotImplementedError


def lstsq_with_smoothness_prior(data:ArrayLike) -> np.ndarray:
    """ not finished,

    Parameters
    ----------
    data: array_like
        the signal to smooth

    Returns
    -------
    to write

    Reference
    ---------
    [1]. Sameni, Reza. "Online Filtering Using Piecewise Smoothness Priors: Application to Normal and Abnormal Electrocardiogram Denoising." Signal Processing 133.C (2017): 52-63. Web.
    """
    raise NotImplementedError


def generate_rr_interval(nb_beats:int,
                         bpm_mean:Real,
                         bpm_std:Real,
                         lf_hf:float,
                         lf_fs:float=0.1,
                         hf_fs:float=0.25,
                         lf_std:float=0.01,
                         hf_std:float=0.01) -> np.ndarray:
    """ finished, not checked,

    Parameters
    ----------
    nb_beats: int,
    bpm_mean: real number,
    bpm_std: real number,
    lf_hf: float,
    lf_fs: float, default 0.1,
    hf_fs: float, default 0.25,
    hf_fs: float, default 0.25,
    lf_std: float, default 0.01,
    ff_std: float, default 0.01,

    Returns
    -------
    to write
    
    """
    expected_rr_mean = 60 / bpm_mean
    expected_rr_std = 60 * bpm_std / (bpm_mean*bpm_mean)
    
    lf = lf_hf*np.random.normal(loc=lf_fs, scale=lf_std, size=nb_beats)  # lf power spectum
    hf = np.random.normal(loc=hf_fs, scale=hf_std, size=nb_beats)  # hf power spectum
    rr_power_spectrum = np.sqrt(lf + hf)
    
    # random (uniformly distributed in [0,2pi]) phases
    phases = np.vectorize(lambda theta: np.exp(2*1j*np.pi*theta))(np.random.uniform(low=0.0, high=2*np.pi, size=nb_beats))
    # real part of inverse FFT of complex spectrum
    raw_rr = np.real(np.fft.ifft(rr_power_spectrum*phases)) / nb_beats
    raw_rr_std = np.std(raw_rr)
    ratio = expected_rr_std/raw_rr_std
    rr = (raw_rr * ratio) + expected_rr_mean
    
    return rr


def is_ecg_signal(s:ArrayLike, fs:int, wavelet_name:str="db6", verbose:int=0) -> bool:
    """ finished, to be improved,

    Parameters
    ----------
    s: array_like,
        the signal to be denoised
    fs: int,
        frequency of the signal `s`
    wavelet_name: str, default "db6"
        name of the wavelet to use
    verbose: int, default 0,
        for detailedness of printing

    Returns
    -------
    True if the signal `s` is valid ecg signal, else return False
    """
    nl = "\n"
    sig_len = len(s)
    spacing = 1000/fs

    # constants for computation
    valid_rr = [200, 3000]  # ms, bpm 300 - 20
    reasonable_rr = [300, 1500]  # ms, bpm 40 - 200
    rr_samp_len = 5
    step_len = int(0.1*fs)  # 100ms
    window_radius = int(0.3*fs)  # 300ms
    slice_len = 2*window_radius  # for cutting out head and tails of the reconstructed signals

    high_confidence = 1.0
    low_confidence = 0.4

    is_ecg_confidence = 0
    is_ecg_confidence_threshold = 1.0
    
    if verbose >= 2:
        import matplotlib.pyplot as plt
        from utils.common import DEFAULT_FIG_SIZE_PER_SEC
        # figsize=(int(DEFAULT_FIG_SIZE_PER_SEC*len(s)/fs), 6)

        print("(level 3 of) the wavelet in use looks like:")
        _, psi, x = pywt.Wavelet(wavelet_name).wavefun(level=3)
        _,ax = plt.subplots()
        ax.plot(x, psi)
        ax.set_title(wavelet_name+" level 3")
        plt.show()

    qrs_freqs = [10, 40]  # Hz
    qrs_levels = [int(np.ceil(np.log2(fs/qrs_freqs[-1]))), int(np.floor(np.log2(fs/qrs_freqs[0])))]
    if qrs_levels[0] > qrs_levels[-1]:
        qrs_levels = qrs_levels[::-1]

    tot_level = qrs_levels[-1]

    if pow(2,tot_level) > sig_len:
        # raise ValueError("length of signal is too short")
        print(f"length ({sig_len}) of signal is too short (should be at least {pow(2,tot_level)}) to perform wavelet denoising")
        return False
    
    base_len = pow(2,tot_level)
    mult, res = divmod(sig_len, base_len)
    if res > 0:
        s_padded = np.concatenate((np.array(s), np.zeros((mult+1)*base_len-sig_len)))
    else:
        s_padded = np.array(s)

    if verbose >= 1:
        print(f"tot_level = {tot_level}, qrs_levels = {qrs_levels}")
        print(f"sig_len = {sig_len}, padded length = {len(s_padded)-sig_len}")
        print(f"shape of s_padded is {s_padded.shape}")
    
    # perform swt
    coeffs = pywt.swt(
        data=s_padded,
        wavelet=wavelet_name,
        level=tot_level
    )

    # cAn = coeffs[0][0]
    coeffs = [ [np.zeros(s_padded.shape), e[1]] for e in coeffs ]
    # coeffs[0][0] = cAn

    zero_coeffs = [ [np.zeros(s_padded.shape), np.zeros(s_padded.shape)] for _ in range(tot_level) ]
    # zero_coeffs = [ [coeffs[i][0], np.zeros(s_padded.shape)] for i in range(tot_level) ]
    
    qrs_signals = []
    for lv in range(qrs_levels[0],qrs_levels[-1]+1):
        c_ = deepcopy(zero_coeffs)
        c_[tot_level-lv][1] = coeffs[tot_level-lv][1]
        # for cA_lv in range(1,lv):
        #     c_[tot_level-cA_lv][0] = c_[tot_level-lv][1]
        qrs_sig = pywt.iswt(coeffs=c_, wavelet=wavelet_name)[:sig_len]
        qrs_signals.append(qrs_sig)

        if verbose >= 2:
            default_fig_sz = 120
            line_len = fs * 25  # 25 seconds
            nb_lines = len(qrs_sig) // line_len
            for idx in range(nb_lines):
                c = qrs_sig[idx*line_len:(idx+1)*line_len]
                _, ax = plt.subplots(figsize=(default_fig_sz,6))
                ax.plot(c, label=f"level {lv}")
                ax.legend(loc="best")
                ax.set_title(f"level {lv}", fontsize=24)
                plt.show()
            c = qrs_sig[nb_lines*line_len:]  # tail left
            if len(c) > 0:
                fig_sz = int(default_fig_sz*(len(s)-nb_lines*line_len)/line_len)
                _, ax = plt.subplots(figsize=(fig_sz,6))
                ax.plot(c, label=f"level {lv}")
                ax.legend(loc="best")
                ax.set_title(f"level {lv}", fontsize=24)
                plt.show()

    qrs_power = np.power(np.sum(np.array(qrs_signals)[:,slice_len:-slice_len], axis=0), 2)
    qrs_amplitudes = []
    idx = window_radius
    while idx < len(qrs_power)-window_radius:
        qrs_seg = qrs_power[idx-window_radius:idx+window_radius+1]
        qrs_amplitudes.append(np.max(qrs_seg)-np.min(qrs_seg))
        idx += step_len
    qrs_amp = np.percentile(qrs_amplitudes, 50) * 0.5

    if verbose >= 1:
        print(f"qrs_amplitudes = {qrs_amplitudes}{nl}qrs_amp = {qrs_amp}")

    raw_r_peaks = detect_peaks(
        x=qrs_power,
        mpd=step_len,
        threshold=qrs_amp,
        verbose=verbose
    )

    raw_rr_intervals = np.diff(raw_r_peaks)*spacing

    if verbose >= 1:
        print(f"raw_r_peaks = {raw_r_peaks.tolist()}{nl}raw_rr_intervals = {raw_rr_intervals.tolist()}")
        s_ = s[slice_len:-slice_len]
        if verbose >= 2:
            default_fig_sz = 120
            line_len = fs * 25  # 25 seconds
            nb_lines = len(qrs_power) // line_len
            for idx in range(nb_lines):
                c = qrs_power[idx*line_len:(idx+1)*line_len]
                c_s_ = s_[idx*line_len:(idx+1)*line_len]
                _, ax = plt.subplots(figsize=(default_fig_sz,6))
                ax.plot(c, color="blue")
                c_r = [r for r in raw_r_peaks if idx*line_len<=r<(idx+1)*line_len]
                for r in c_r:
                    ax.axvline(r-idx*line_len, color="red", linestyle="dashed", linewidth=0.5)
                ax.set_title("QRS power", fontsize=24)
                ax2 = ax.twinx()
                ax2.plot(c_s_, color="green")
                plt.show()
            c = qrs_power[nb_lines*line_len:]  # tail left
            c_s_ = s_[nb_lines*line_len:]
            if len(c) > 0:
                fig_sz = int(default_fig_sz*(len(s)-nb_lines*line_len)/line_len)
                _, ax = plt.subplots(figsize=(fig_sz,6))
                ax.plot(c, color="blue")
                c_r = [r for r in raw_r_peaks if nb_lines*line_len<=r]
                for r in c_r:
                    ax.axvline(r-nb_lines*line_len, color="red", linestyle="dashed", linewidth=0.5)
                ax.set_title("QRS power", fontsize=24)
                ax2 = ax.twinx()
                ax2.plot(c_s_, color="green")
                plt.show()
            # _, ax = plt.subplots(figsize=figsize)
            # ax.plot(qrs_power, color="blue")
            # for r in raw_r_peaks:
            #     ax.axvline(r, color="red", linestyle="dashed", linewidth=0.5)
            # ax.set_title("QRS power", fontsize=20)
            # ax2 = ax.twinx()
            # ax2.plot(s[slice_len:-slice_len], color="green", linestyle="dashed")
            # plt.show()

    # TODO: compute entropy, std., etc. of raw_r_peaks
    # criteria 1: number of (r) peaks
    if spacing*len(qrs_power)/reasonable_rr[1] <= len(raw_r_peaks) <= spacing*len(qrs_power)/reasonable_rr[0]:
        is_ecg_confidence += high_confidence
    elif spacing*len(qrs_power)/valid_rr[1] <= len(raw_r_peaks) <= spacing*len(qrs_power)/valid_rr[0]:
        is_ecg_confidence += low_confidence
    # else: zero confidence

    # criteria 2: std of rr intervals
    raw_rr_std = np.std(raw_rr_intervals)
    # TODO: compute confidence level via std

    # criteria 3: sample entropy of rr intervals
    # raw_r_peaks_entropy = ent.sample_entropy(raw_rr_intervals, sample_length=rr_samp_len)[-1]
    # TODO: compute confidence level via sample entropy

    if verbose >= 1:
        print(f"overall is_ecg_confidence = {is_ecg_confidence}")
    
    return True if is_ecg_confidence >= is_ecg_confidence_threshold else False


def wavelet_denoise(s:ArrayLike,
                    fs:int,
                    wavelet_name:str="db6",
                    amplify_mode:str="ecg",
                    sides_mode:str="nearest",
                    cval:int=0,
                    verbose:int=0,
                    **kwargs:Any) -> NamedTuple:
    """ finished, to be improved,

    denoise and amplify (if necessary) signal `s`, using wavelet decomposition

    Parameters
    ----------
    s: array_like,
        the signal to be denoised
    fs: int,
        frequency of the signal `s`
    wavelet_name: str, default "db6"
        name of the wavelet to use
    amplify_mode: str, default "ecg",
        amplification mode, can be one of "ecg", "qrs", "all", "none"
    sides_mode: str, default "nearest",
        the way to treat the head and tail of the reconstructed (only if amplification is performed) signal,
        implemented modes: "nearest", "mirror", "wrap", "constant", "no_slicing"
        not yet implemented mode(s): "interp"
    cval: int, default 0,
        used only when `side_mode` is set "constant"
    verbose: int, default 0,
        for detailedness of printing

    Returns
    -------
    WaveletDenoiseResult, with field_names: "is_ecg", "amplified_ratio", "amplified_signal", "raw_r_peaks"
    
    TODO
    ----

    """
    nl = "\n"
    if amplify_mode not in ["ecg", "qrs", "all", "none"]:
        raise ValueError("Invalid amplify_mode! amplify_mode must be one of "
        "'ecg', 'qrs', 'all', 'none'.")
    if sides_mode not in ["nearest", "mirror", "wrap", "constant", "no_slicing", "interp"]:
        raise ValueError("Invalid sides_mode! sides_mode must be one of "
        "'nearest', 'mirror', 'wrap', 'constant', 'no_slicing', 'interp'.")

    sig_len = len(s)
    spacing = 1000/fs

    # constants for computation
    valid_rr = [200, 3000]  # ms, bpm 300 - 20
    reasonable_rr = [300, 1500]  # ms, bpm 40 - 200
    rr_samp_len = 5
    step_len = int(0.1*fs)  # 100ms
    qrs_radius = int(0.1*fs)  # 100ms
    window_radius = int(0.3*fs)  # 300ms
    slice_len = 2*window_radius  # for cutting out head and tails of the reconstructed signals

    # standard_ecg_amplitude = 1100  # muV
    # need_amplification_threshold = 500  # muV
    # now can be set de hors
    standard_ecg_amplitude = kwargs.get("standard_ecg_amplitude", 1100)
    need_amplification_threshold = kwargs.get("need_amplification_threshold", 500)

    high_confidence = 1.0
    low_confidence = 0.4

    is_ecg_confidence = 0
    is_ecg_confidence_threshold = 1.0
    
    if verbose >= 2:
        import matplotlib.pyplot as plt
        from utils.common import DEFAULT_FIG_SIZE_PER_SEC
        # figsize=(int(DEFAULT_FIG_SIZE_PER_SEC*len(s)/fs), 6)

        print("(level 3 of) the wavelet used looks like:")
        _, psi, x = pywt.Wavelet(wavelet_name).wavefun(level=3)
        _,ax = plt.subplots()
        ax.plot(x, psi)
        ax.set_title(wavelet_name+" level 3")
        plt.show()

    qrs_freqs = [10, 40]  # Hz
    qrs_levels = [int(np.ceil(np.log2(fs/qrs_freqs[-1]))), int(np.floor(np.log2(fs/qrs_freqs[0])))]
    if qrs_levels[0] > qrs_levels[-1]:
        qrs_levels = qrs_levels[::-1]

    ecg_freqs = [0.5, 45]  # Hz
    ecg_levels = [int(np.floor(np.log2(fs/ecg_freqs[-1]))), int(np.ceil(np.log2(fs/ecg_freqs[0])))]
        
    # if qrs_only:
    #     tot_level = qrs_levels[-1]
    # else:
    #     tot_level = ecg_levels[-1]
    tot_level = ecg_levels[-1]+1

    if pow(2,tot_level) > sig_len:
        # raise ValueError("length of signal is too short")
        print(f"length ({sig_len}) of signal is too short (should be at least {pow(2,tot_level)}) to perform wavelet denoising")
        ret = WaveletDenoiseResult(is_ecg=False, amplified_ratio=1.0, amplified_signal=deepcopy(s), raw_r_peaks=np.array([]), side_len=slice_len, wavelet_name=wavelet_name, wavelet_coeffs=[])
        return ret
    
    base_len = pow(2,tot_level)
    mult, res = divmod(sig_len, base_len)
    if res > 0:
        s_padded = np.concatenate((np.array(s), np.zeros((mult+1)*base_len-sig_len)))
    else:
        s_padded = np.array(s)

    if verbose >= 1:
        print(f"tot_level = {tot_level}, qrs_levels = {qrs_levels}, ecg_levels = {ecg_levels}")
        print(f"sig_len = {sig_len}, padded length = {len(s_padded)-sig_len}")
        print(f"shape of s_padded is {s_padded.shape}")
    
    # perform swt
    raw_coeffs = pywt.swt(
        data=s_padded,
        wavelet=wavelet_name,
        level=tot_level
    )

    # cAn = raw_coeffs[0][0]
    coeffs = [ [np.zeros(s_padded.shape), e[1]] for e in raw_coeffs ]
    # coeffs[0][0] = cAn

    zero_coeffs = [ [np.zeros(s_padded.shape), np.zeros(s_padded.shape)] for _ in range(tot_level) ]
    # zero_coeffs = [ [raw_coeffs[i][0], np.zeros(s_padded.shape)] for i in range(tot_level) ]
    
    qrs_signals = []
    for lv in range(qrs_levels[0],qrs_levels[-1]+1):
        c_ = deepcopy(zero_coeffs)
        c_[tot_level-lv][1] = coeffs[tot_level-lv][1]
        # for cA_lv in range(1,lv):
        #     c_[tot_level-cA_lv][0] = c_[tot_level-lv][1]
        qrs_sig = pywt.iswt(coeffs=c_, wavelet=wavelet_name)[:sig_len]
        qrs_signals.append(qrs_sig)

        if verbose >= 2:
            default_fig_sz = 120
            line_len = fs * 25  # 25 seconds
            nb_lines = len(qrs_sig) // line_len
            for idx in range(nb_lines):
                c = qrs_sig[idx*line_len:(idx+1)*line_len]
                _, ax = plt.subplots(figsize=(default_fig_sz,6))
                ax.plot(c, label=f"level {lv}")
                ax.legend(loc="best")
                ax.set_title(f"level {lv}", fontsize=24)
                plt.show()
            c = qrs_sig[nb_lines*line_len:]  # tail left
            if len(c) > 0:
                fig_sz = int(default_fig_sz*(len(s)-nb_lines*line_len)/line_len)
                _, ax = plt.subplots(figsize=(fig_sz,6))
                ax.plot(c, label=f"level {lv}")
                ax.legend(loc="best")
                ax.set_title(f"level {lv}", fontsize=24)
                plt.show()

    qrs_power = np.power(np.sum(np.array(qrs_signals)[:,slice_len:-slice_len], axis=0), 2)
    qrs_amplitudes = []
    idx = window_radius
    while idx < len(qrs_power)-window_radius:
        qrs_seg = qrs_power[idx-window_radius:idx+window_radius+1]
        qrs_amplitudes.append(np.max(qrs_seg)-np.min(qrs_seg))
        idx += step_len
    qrs_amp = np.percentile(qrs_amplitudes, 50) * 0.5

    if verbose >= 1:
        print(f"qrs_amplitudes = {qrs_amplitudes}{nl}qrs_amp = {qrs_amp}")

    raw_r_peaks = detect_peaks(
        x=qrs_power,
        mpd=step_len,
        threshold=qrs_amp,
        verbose=verbose
    )

    raw_rr_intervals = np.diff(raw_r_peaks)*spacing

    if verbose >= 1:
        print(f"raw_r_peaks = {raw_r_peaks.tolist()}{nl}raw_rr_intervals = {raw_rr_intervals.tolist()}")
        s_ = s[slice_len:-slice_len]
        if verbose >= 2:
            default_fig_sz = 120
            line_len = fs * 25  # 25 seconds
            nb_lines = len(qrs_power) // line_len
            for idx in range(nb_lines):
                c = qrs_power[idx*line_len:(idx+1)*line_len]
                c_s_ = s_[idx*line_len:(idx+1)*line_len]
                _, ax = plt.subplots(figsize=(default_fig_sz,6))
                ax.plot(c, color="blue")
                c_r = [r for r in raw_r_peaks if idx*line_len<=r<(idx+1)*line_len]
                for r in c_r:
                    ax.axvline(r-idx*line_len, color="red", linestyle="dashed", linewidth=0.5)
                ax.set_title("QRS power", fontsize=24)
                ax2 = ax.twinx()
                ax2.plot(c_s_, color="green")
                plt.show()
            c = qrs_power[nb_lines*line_len:]  # tail left
            c_s_ = s_[nb_lines*line_len:]
            if len(c) > 0:
                fig_sz = int(default_fig_sz*(len(s)-nb_lines*line_len)/line_len)
                _, ax = plt.subplots(figsize=(fig_sz,6))
                ax.plot(c, color="blue")
                c_r = [r for r in raw_r_peaks if nb_lines*line_len<=r]
                for r in c_r:
                    ax.axvline(r-nb_lines*line_len, color="red", linestyle="dashed", linewidth=0.5)
                ax.set_title("QRS power", fontsize=24)
                ax2 = ax.twinx()
                ax2.plot(c_s_, color="green")
                plt.show()
            # _, ax = plt.subplots(figsize=figsize)
            # ax.plot(qrs_power, color="blue")
            # for r in raw_r_peaks:
            #     ax.axvline(r, color="red", linestyle="dashed", linewidth=0.5)
            # ax.set_title("QRS power", fontsize=20)
            # ax2 = ax.twinx()
            # ax2.plot(s[slice_len:-slice_len], color="green", linestyle="dashed")
            # plt.show()

    # TODO: compute entropy, std., etc. of raw_r_peaks
    # criteria 1: number of (r) peaks
    if spacing*len(qrs_power)/reasonable_rr[1] <= len(raw_r_peaks) <= spacing*len(qrs_power)/reasonable_rr[0]:
        is_ecg_confidence += high_confidence
    elif spacing*len(qrs_power)/valid_rr[1] <= len(raw_r_peaks) <= spacing*len(qrs_power)/valid_rr[0]:
        is_ecg_confidence += low_confidence
    # else: zero confidence

    # criteria 2: std of rr intervals
    raw_rr_std = np.std(raw_rr_intervals)
    # TODO: compute confidence level via std

    # criteria 3: sample entropy of rr intervals
    # raw_r_peaks_entropy = ent.sample_entropy(raw_rr_intervals, sample_length=rr_samp_len)[-1]
    # TODO: compute confidence level via sample entropy

    if verbose >= 1:
        print(f"overall is_ecg_confidence = {is_ecg_confidence}")
    
    if is_ecg_confidence >= is_ecg_confidence_threshold:
        qrs_amplitudes = []
        # note that raw_r_peaks are computed from qrs_power,
        #  which is sliced at head (and at tail) by slice_len
        raw_r_peaks = raw_r_peaks + slice_len
        for r in raw_r_peaks:
            qrs_seg = s[r-qrs_radius:r+qrs_radius+1]
            qrs_amplitudes.append(np.max(qrs_seg)-np.min(qrs_seg))
        qrs_amp = np.percentile(qrs_amplitudes, 75)
        if qrs_amp < need_amplification_threshold:
            amplify_ratio = standard_ecg_amplitude / qrs_amp
        else:
            amplify_ratio = 1.0

        if amplify_mode != "none" and amplify_ratio > 1.0:
            c_ = deepcopy(coeffs)  # or deepcopy(zero_coeffs)?
            # c_ = deepcopy(zero_coeffs)

            if amplify_mode == "ecg":
                levels_in_use = [ecg_levels[0], ecg_levels[-1]-2]
            elif amplify_mode == "qrs":
                levels_in_use = [qrs_levels[0]-1, qrs_levels[-1]+1]
            elif amplify_mode == "all":
                levels_in_use = [1, ecg_levels[-1]+1]
            # for lv in range(qrs_levels[0]-1, qrs_levels[-1]+2):
            # for lv in range(qrs_levels[0]-1, qrs_levels[-1]+1):
            # for lv in range(ecg_levels[0], ecg_levels[-1]+1):
            for lv in range(levels_in_use[0], levels_in_use[1]):
                c_[tot_level-lv][1] = amplify_ratio*coeffs[tot_level-lv][1]
            
            s_rec = pywt.iswt(coeffs=c_, wavelet=wavelet_name)[:sig_len]
            # s_rec = np.vectorize(lambda n: int(round(n)))(s_rec[slice_len:-slice_len])
            s_rec = np.vectorize(lambda n: int(round(n)))(s_rec)

            # add head and tail
            if sides_mode == "nearest":
                s_rec[:slice_len] = s_rec[slice_len]
                s_rec[-slice_len:] = s_rec[-slice_len-1]
            elif sides_mode == "mirror":
                s_rec[:slice_len] = s_rec[2*slice_len-1:slice_len-1:-1]
                s_rec[-slice_len:] = s_rec[-slice_len-1:-2*slice_len-1:-1]
            elif sides_mode == "wrap":
                s_rec[:slice_len] = s_rec[-2*slice_len:-slice_len] + (s_rec[slice_len]-s_rec[slice_len-1])
                s_rec[-slice_len:] = s_rec[slice_len:2*slice_len] + (s_rec[-slice_len]-s_rec[-slice_len-1])
            elif sides_mode == "constant":
                s_rec[:slice_len] = cval
                s_rec[-slice_len:] = cval
            elif sides_mode == "no_slicing":
                pass  # do nothing to head and tail of s_rec
            elif sides_mode == "interp":
                raise ValueError("Invalid sides_mode! sides_mode 'interp' not implemented yet!")
        else: # set no amplification, or need no amplification
            levels_in_use = [np.nan, np.nan]
            s_rec = deepcopy(s)
        
        if verbose >= 1:
            print(f"levels used for the purpose of amplification are {levels_in_use[0]} to {levels_in_use[1]-1} (inclusive)")
            print(f"amplify_ratio = {amplify_ratio}{nl}qrs_amplitudes = {qrs_amplitudes}")
            if verbose >= 2:
                default_fig_sz = 120
                line_len = fs * 25  # 25 seconds
                nb_lines = len(s_rec) // line_len
                for idx in range(nb_lines):
                    c_rec = s_rec[idx*line_len:(idx+1)*line_len]
                    c = s[idx*line_len:(idx+1)*line_len]
                    _, ax = plt.subplots(figsize=(default_fig_sz,6))
                    ax.plot(c_rec,color="red")
                    ax.plot(c,alpha=0.6)
                    ax.set_title("signal amplified", fontsize=24)
                    c_r = [r for r in raw_r_peaks if idx*line_len<=r<(idx+1)*line_len]
                    for r in c_r:
                        ax.axvline(r-idx*line_len, color="red", linestyle="dashed", linewidth=0.5)
                    plt.show()
                c_rec = s_rec[nb_lines*line_len:]  # tail left
                c = s[nb_lines*line_len:]
                if len(c) > 0:
                    fig_sz = int(default_fig_sz*(len(s)-nb_lines*line_len)/line_len)
                    _, ax = plt.subplots(figsize=(fig_sz,6))
                    ax.plot(c_rec,color="red")
                    ax.plot(c,alpha=0.6)
                    ax.set_title("signal amplified", fontsize=24)
                    c_r = [r for r in raw_r_peaks if nb_lines*line_len<=r]
                    for r in c_r:
                        ax.axvline(r-nb_lines*line_len, color="red", linestyle="dashed", linewidth=0.5)
                    plt.show()
        
        ret = WaveletDenoiseResult(is_ecg=True, amplified_ratio=amplify_ratio, amplified_signal=s_rec, raw_r_peaks=raw_r_peaks, side_len=slice_len, wavelet_name=wavelet_name, wavelet_coeffs=raw_coeffs)
    else:  # not ecg
        raw_r_peaks = raw_r_peaks + slice_len
        ret = WaveletDenoiseResult(is_ecg=False, amplified_ratio=np.nan, amplified_signal=deepcopy(s), raw_r_peaks=raw_r_peaks, side_len=slice_len, wavelet_name=wavelet_name, wavelet_coeffs=raw_coeffs)
    
    return ret


def wavelet_rec_iswt(coeffs:List[List[np.ndarray]],
                     levels:ArrayLike_Int,
                     wavelet_name:str,
                     verbose:int=0) -> np.ndarray:
    """ finished, checked,

    reconstruct signal, using pywt.iswt, using coefficients obtained by pywt.swt of level in `levels`

    Parameters
    ----------
    coeffs: list of list (pair) of np.ndarray,
        wavelet ceofficients (list of [cA_n,cD_n], ..., [cA_1,cD_1]), obtained by pywt.swt
    levels: list of int,
        the levels to reconstruct from
    wavelet_name: str,
        name of the wavelet
    verbose: int, default 0,
        the detailedness of printing

    Returns
    -------
    np.ndarray, the reconstructed signal
    """
    if verbose >= 2:
        import matplotlib.pyplot as plt
    
    sig_shape = coeffs[0][0].shape
    nb_levels = len(coeffs)

    if verbose >= 1:
        print(f"sig_shape = {sig_shape}, nb_levels = {nb_levels}")
    
    if (nb_levels < np.array(levels)).any():
        raise ValueError("Invalid levels")
    
    c_ = [[np.zeros(sig_shape),np.zeros(sig_shape)] for _ in range(nb_levels)]
    for lv in levels:
        c_[nb_levels-lv][1] = coeffs[nb_levels-lv][1]
    sig_rec = pywt.iswt(coeffs=c_, wavelet=wavelet_name)

    if verbose >= 2:
        _, ax = plt.subplots(figsize=(20,4))
        ax.plot(sig_rec)
        plt.show()
    
    return sig_rec


def resample_irregular_timeseries(s:ArrayLike,
                                  output_fs:Real=2,
                                  method:str="spline",
                                  return_with_time:bool=False,
                                  tnew:Optional[ArrayLike]=None,
                                  interp_kw:dict={},
                                  verbose:int=0) -> np.ndarray:
    """ finished, checked,

    resample the 2d irregular timeseries `s` into a 1d or 2d regular time series with frequency `output_fs`,
    elements of `s` are in the form [time, value], where the unit of `time` is ms

    Parameters
    ----------
    s: array_like,
        the 2d irregular timeseries
    output_fs: Real, default 2,
        the frequency of the output 1d regular timeseries
    method: str, default "spline"
        interpolation method, can be "spline" or "interp1d"
    return_with_time: bool, default False,
        return a 2d array, with the 0-th coordinate being time
    tnew: array_like, optional,
        the array of time of the output array
    interp_kw: dict, default {},
        additional options for the corresponding methods in scipy.interpolate

    Returns
    -------
    np.ndarray, a 1d or 2d regular time series with frequency `output_fs`

    NOTE
    ----
    pandas also has the function to regularly resample irregular timeseries
    """
    if method not in ["spline", "interp1d"]:
        raise ValueError(f"method {method} not implemented")

    if verbose >= 1:
        print(f"len(s) = {len(s)}")

    if len(s) == 0:
        return np.array([])
    
    time_series = np.atleast_2d(s)
    step_ts = 1000 / output_fs
    tot_len = int((time_series[-1][0]-time_series[0][0]) / step_ts) + 1
    if tnew is None:
        xnew = time_series[0][0] + np.arange(0, tot_len*step_ts, step_ts)
    else:
        xnew = np.array(tnew)

    if verbose >= 1:
        print(f"time_series start ts = {time_series[0][0]}, end ts = {time_series[-1][0]}")
        print(f"tot_len = {tot_len}")
        print(f"xnew start = {xnew[0]}, end = {xnew[-1]}")

    if method == "spline":
        m = len(time_series)
        w = interp_kw.get("w", np.ones(shape=(m,)))
        # s = interp_kw.get("s", np.random.uniform(m-np.sqrt(2*m),m+np.sqrt(2*m)))
        s = interp_kw.get("s", m-np.sqrt(2*m))
        interp_kw.update(w=w, s=s)

        tck = interpolate.splrep(time_series[:,0],time_series[:,1],**interp_kw)

        regular_timeseries = interpolate.splev(xnew, tck)
    elif method == "interp1d":
        f = interpolate.interp1d(time_series[:,0],time_series[:,1],**interp_kw)

        regular_timeseries = f(xnew)
    
    if return_with_time:
        return np.column_stack((xnew, regular_timeseries))
    else:
        return regular_timeseries


def resample_discontinuous_irregular_timeseries(s:ArrayLike,
                                                allowd_gap:Optional[Real]=None,
                                                output_fs:Real=2,
                                                method:str="spline",
                                                return_with_time:bool=True,
                                                tnew:Optional[ArrayLike]=None,
                                                interp_kw:dict={},
                                                verbose:int=0) -> List[np.ndarray]:
    """ finished, checked,

    resample the 2d discontinuous irregular timeseries `s` into a list of 1d or 2d regular time series with frequency `output_fs`,
    where discontinuity means time gap greater than `allowd_gap`,
    elements of `s` are in the form [time, value], where the unit of `time` is ms

    Parameters
    ----------
    s: array_like,
        the 2d irregular timeseries
    output_fs: Real, default 2,
        the frequency of the output 1d regular timeseries
    method: str, default "spline"
        interpolation method, can be "spline" or "interp1d"
    return_with_time: bool, default False,
        return a 2d array, with the 0-th coordinate being time
    tnew: array_like, optional,
        the array of time of the output array
    interp_kw: dict, default {},
        additional options for the corresponding methods in scipy.interpolate
    verbose: int, default 0,
        verbosity

    Returns
    -------
    list of np.ndarray, 1d or 2d regular time series with frequency `output_freq`

    NOTE
    ----
    pandas also has the function to regularly resample irregular timeseries
    """
    time_series = np.atleast_2d(s)
    allowd_gap = allowd_gap or 2*1000/output_fs
    split_indices = [0] + (np.where(np.diff(time_series[:,0]) > allowd_gap)[0]+1).tolist() + [len(time_series)]
    if tnew is not None:
        l_tnew = [[p for p in tnew if time_series[split_indices[idx],0]<=p<time_series[split_indices[idx+1],0]] for idx in range(len(split_indices)-1)]
    else:
        l_tnew = [None for _ in range(len(split_indices)-1)]
    result = []
    for idx in range(len(split_indices)-1):
        r = resample_irregular_timeseries(
            s=time_series[split_indices[idx]: split_indices[idx+1]],
            output_fs=output_fs,
            method=method,
            return_with_time=return_with_time,
            tnew=l_tnew[idx],
            interp_kw=interp_kw,
            verbose=verbose
        )
        result.append(r)
    return result


def sft(s:ArrayLike) -> np.ndarray:
    """

    slow Fourier transform, just for fun
    """
    N = len(s)
    _s = np.array(s)
    tmp = np.array(list(range(N)))
    return np.array([(_s*np.exp(-2*np.pi*1j*n*tmp/N)).sum() for n in range(N)])


def butter_bandpass(lowcut:Real,
                    highcut:Real,
                    fs:Real,
                    order:int,
                    verbose:int=0) -> Tuple[np.ndarray, np.ndarray]:
    """ finished, checked,

    Butterworth Bandpass Filter Design

    Parameters
    ----------
    lowcut: real,
        low cutoff frequency
    highcut: real,
        high cutoff frequency
    fs: real,
        frequency of `data`
    order: int,
        order of the filter
    verbose: int, default 0

    Returns
    -------
    b, a: tuple of ndarray,
        coefficients of numerator and denominator of the filter

    NOTE
    ----
    according to `lowcut` and `highcut`, the filter type might fall to lowpass or highpass filter

    References
    ----------
    [2] scipy.signal.butter
    [1] https://scipy-cookbook.readthedocs.io/items/ButterworthBandpass.html
    """
    nyq = 0.5 * fs
    low = lowcut / nyq
    if low >= 1:
        raise ValueError("frequency out of range!")
    high = highcut / nyq

    if low <= 0 and high >= 1:
        b, a = [1], [1]
        return b, a
    
    if low <= 0:
        Wn = high
        btype = "low"
    elif high >= 1:
        Wn = low
        btype = "high"
    elif lowcut==highcut:
        Wn = high
        btype = "low"
    else:
        Wn = [low, high]
        btype = "band"
    
    if verbose >= 1:
        print(f"by the setup of lowcut and highcut, the filter type falls to {btype}, with Wn = {Wn}")
    
    b, a = butter(order, Wn, btype=btype)
    return b, a


def butter_bandpass_filter(data:ArrayLike,
                           lowcut:Real,
                           highcut:Real,
                           fs:Real,
                           order:int,
                           verbose:int=0) -> np.ndarray:
    """ finished, checked,

    Butterworth Bandpass

    Parameters
    ----------
    data: array_like,
        data to be filtered
    lowcut: real,
        low cutoff frequency
    highcut: real,
        high cutoff frequency
    fs: real,
        frequency of `data`
    order: int,
        order of the filter
    verbose: int, default 0

    Returns
    -------
    y, ndarray,
        the filtered signal

    References
    ----------
    [1] https://scipy-cookbook.readthedocs.io/items/ButterworthBandpass.html
    [2] https://dsp.stackexchange.com/questions/19084/applying-filter-in-scipy-signal-use-lfilter-or-filtfilt
    """
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    y = filtfilt(b, a, data)
    return y


def hampel(input_series:ArrayLike,
           window_size:int,
           n_sigmas:int=3,
           return_outlier:bool=True,
           use_jit:bool=False) -> Union[np.ndarray, Tuple[np.ndarray, List[int]]]:
    """ finished, not checked, (potentially with bugs)

    Hampel filter

    Parameters
    ----------
    input_series: array_like,
        the signal to be filtered
    window_size: int,
        radius of the filter window
    n_sigmas: int, default 3,
        deviation threshold of outlier from the window median value devided by the window median of absolute differences with the window median value
    return_outlier: bool, default True,
        whether or not return the indices of outliers
    use_jit: bool, default False,
        whether or not use `@numba.jit(nopython=True)`

    Returns
    -------
    new_series: ndarray,
        the filtered signal
    outlier_indices: list of int,
        indices of the outliers, if `return_outlier` is True,
        otherwise empty list

    References
    ----------
    [1] https://towardsdatascience.com/outlier-detection-with-hampel-filter-85ddf523c73d
    [2] https://www.mathworks.com/help/signal/ref/hampel.html
    [3] Hampel, F. R. (1974). The influence curve and its role in robust estimation. Journal of the american statistical association, 69(346), 383-393.
    """
    if use_jit:
        _h = _hampel_jit(input_series, window_size, n_sigmas, return_outlier)
    else:
        _h = _hampel(input_series, window_size, n_sigmas, return_outlier)
    if len(_h) > 0:
        new_series, outlier_indices = _h
    else:
        new_series, outlier_indices = _h, []
    return new_series, outlier_indices

@jit(nopython=True)
def _hampel_jit(input_series:ArrayLike,
                window_size:int,
                n_sigmas:int=3,
                return_outlier:bool=True) -> Union[np.ndarray, Tuple[np.ndarray, List[int]]]:
    """
    ref. hampel
    """
    n = len(input_series)
    new_series = np.array(input_series).copy()
    k = 1.4826 # scale factor for Gaussian distribution
    outlier_indices = []
    
    for i in range((window_size),(n - window_size)):
        x0 = np.nanmedian(input_series[(i - window_size):(i + window_size)])
        S0 = k * np.nanmedian(np.abs(input_series[(i - window_size):(i + window_size)] - x0))
        if (np.abs(input_series[i] - x0) > n_sigmas * S0):
            new_series[i] = x0
            outlier_indices.append(i)
    if return_outlier:
        return new_series, outlier_indices
    else:
        return new_series

def _hampel(input_series:ArrayLike,
            window_size:int,
            n_sigmas:int=3,
            return_outlier:bool=True) -> Union[np.ndarray, Tuple[np.ndarray, List[int]]]:
    """
    ref. hampel
    """
    n = len(input_series)
    new_series = np.array(input_series).copy()
    k = 1.4826 # scale factor for Gaussian distribution
    outlier_indices = []
    
    for i in range((window_size),(n - window_size)):
        x0 = np.nanmedian(input_series[(i - window_size):(i + window_size)])
        S0 = k * np.nanmedian(np.abs(input_series[(i - window_size):(i + window_size)] - x0))
        if (np.abs(input_series[i] - x0) > n_sigmas * S0):
            new_series[i] = x0
            outlier_indices.append(i)
    if return_outlier:
        return new_series, outlier_indices
    else:
        return new_series


def detect_flat_lines(s:np.ndarray,
                      window:int,
                      tolerance:Real=0,
                      verbose:int=0,
                      **kwargs:Any) -> Tuple[np.ndarray, float]:
    """ finished, checked,

    detect flat (with tolerance) lines of length >= `window`

    Parameters
    ----------
    s: ndarray,
        the signal
    window: int,
        size (length) of the detection window
    tolerance: real, default 0,
        difference within `tolerance` will be considered "flat"
    verbose: int, default 0,

    Returns
    -------
    flat_locs: ndarray,
        indices of samples in `s` of the flat lines
    flat_prop: float,
        proportion of flat parts in `s`
    
    References
    ----------
    https://github.com/gslapnicar/bp-estimation-mimic3/blob/master/cleaning_scripts/flat_lines.m
    """
    n = len(s)
    flat_locs = np.ones(n-window+1,dtype=int)
    for i in range(1, window):
        tmp = (np.abs(s[:n-window+1] - s[i:n-window+i+1]) <= abs(tolerance)).astype(int)
        flat_locs = np.bitwise_and(flat_locs, tmp)
    flat_locs = np.append(flat_locs, np.zeros(window-1,dtype=int))
    tmp = flat_locs.copy()
    for i in range(1, window):
        flat_locs[i:] = np.bitwise_or(flat_locs[i:], tmp[:-i])
    if verbose >= 2:
        if "plt" not in dir():
            import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(n/125*4,6))
        x = np.arange(n)
        ax.plot(x, s)
        ax.scatter(x[flat_locs==1], s[flat_locs==1], color="red")
    flat_prop = np.sum(flat_locs)/n
    return flat_locs, flat_prop


class MovingAverage(object):
    """ finished, checked, to be improved,

    moving average

    References
    ----------
    [1] https://en.wikipedia.org/wiki/Moving_average
    """
    def __init__(self, data:ArrayLike, **kwargs:Any) -> NoReturn:
        """
        Parameters
        ----------
        data: array_like,
            the series data to compute its moving average
        kwargs: auxilliary key word arguments
        """
        self.data = np.array(data)
        self.verbose = kwargs.get("verbose", 0)

    def cal(self, method:str, **kwargs:Any) -> np.ndarray:
        """
        Parameters
        ----------
        method: str,
            method for computing moving average, can be one of
            - "sma", "simple", "simple moving average"
            - "ema", "ewma", "exponential", "exponential weighted", "exponential moving average", "exponential weighted moving average"
            - "cma", "cumulative", "cumulative moving average"
            - "wma", "weighted", "weighted moving average"
        """
        m = method.lower().replace("_", " ")
        if m in ["sma", "simple", "simple moving average"]:
            func = self._sma
        elif m in ["ema", "ewma", "exponential", "exponential weighted", "exponential moving average", "exponential weighted moving average"]:
            func = self._ema
        elif m in ["cma", "cumulative", "cumulative moving average"]:
            func = self._cma
        elif m in ["wma", "weighted", "weighted moving average"]:
            func = self._wma
        else:
            raise NotImplementedError
        return func(**kwargs)

    def _sma(self, window:int=5, center:bool=False, **kwargs:Any) -> np.ndarray:
        """
        simple moving average

        Parameters
        ----------
        window: int, default 5,
            window length of the moving average
        center: bool, default False,
            if True, when computing the output value at each point, the window will be centered at that point;
            otherwise the previous `window` points of the current point will be used
        """
        smoothed = []
        if center:
            hw = window//2
            window = hw*2+1
        for n in range(window):
            smoothed.append(np.mean(self.data[:n+1]))
        prev = smoothed[-1]
        for n, d in enumerate(self.data[window:]):
            s = prev + (d - self.data[n]) / window
            prev = s
            smoothed.append(s)
        smoothed = np.array(smoothed)
        if center:
            smoothed[hw:-hw] = smoothed[window-1:]
            for n in range(hw):
                smoothed[n] = np.mean(self.data[:n+hw+1])
                smoothed[-n-1] = np.mean(self.data[-n-hw-1:])
        return smoothed

    def _ema(self, weight:float=0.6, **kwargs:Any) -> np.ndarray:
        """
        exponential moving average,
        which is also the function used in Tensorboard Scalar panel,
        whose parameter `smoothing` is the `weight` here

        Parameters
        ----------
        weight: float, default 0.6,
            weight of the previous data point
        """
        smoothed = []
        prev = self.data[0]
        for d in self.data:
            s = prev * weight + (1 - weight) * d
            prev = s
            smoothed.append(s)
        smoothed = np.array(smoothed)
        return smoothed

    def _cma(self, **kwargs) -> np.ndarray:
        """
        cumulative moving average
        """
        smoothed = []
        prev = 0
        for n, d in enumerate(self.data):
            s = prev + (d - prev) / (n+1)
            prev = s
            smoothed.append(s)
        smoothed = np.array(smoothed)
        return smoothed

    def _wma(self, window:int=5, **kwargs:Any) -> np.ndarray:
        """
        weighted moving average

        Parameters
        ----------
        window: int, default 5,
            window length of the moving average
        """
        # smoothed = []
        # total = []
        # numerator = []
        conv = np.arange(1, window+1)[::-1]
        deno = np.sum(conv)
        smoothed = np.convolve(conv, self.data, mode="same") / deno
        return smoothed


def smooth(x:np.ndarray,
           window_len:int=11,
           window:str="hanning",
           mode:str="valid",
           keep_dtype:bool=True) -> np.ndarray:
    """ finished, checked,
    
    smooth the 1d data using a window with requested size.
    
    This method is based on the convolution of a scaled window with the signal.
    The signal is prepared by introducing reflected copies of the signal 
    (with the window size) in both ends so that transient parts are minimized
    in the begining and end part of the output signal.
    
    Parameters
    ----------
    x: ndarray,
        the input signal 
    window_len: int, default 11,
        the length of the smoothing window,
        (previously should be an odd integer, currently can be any (positive) integer)
    window: str, default "hanning",
        the type of window from "flat", "hanning", "hamming", "bartlett", "blackman",
        flat window will produce a moving average smoothing
    mode: str, default "valid",
        ref. `np.convolve`
    keep_dtype: bool, default True,
        dtype of the returned value keeps the same with that of `x` or not

    Returns
    -------
    y: ndarray,
        the smoothed signal
        
    Example
    -------
    >>> t = linspace(-2, 2, 0.1)
    >>> x = sin(t) + randn(len(t)) * 0.1
    >>> y = smooth(x)
    
    See also
    --------
    np.hanning, np.hamming, np.bartlett, np.blackman, np.convolve
    scipy.signal.lfilter
    scipy.signal.filtfilt
 
    TODO: the window parameter could be the window itself if an array instead of a string

    NOTE: length(output) != length(input), to correct this: return y[(window_len/2-1):-(window_len/2)] instead of just y.

    References
    ----------
    [1] https://scipy-cookbook.readthedocs.io/items/SignalSmooth.html
    """
    radius = min(len(x), window_len)
    radius = radius if radius%2 == 1 else radius-1

    if x.ndim != 1:
        raise ValueError("smooth only accepts 1 dimension arrays.")

    # if x.size < radius:
    #     raise ValueError("Input vector needs to be bigger than window size.")

    if radius < 3:
        return x
    
    if not window in ["flat", "hanning", "hamming", "bartlett", "blackman"]:
        raise ValueError("Window is on of 'flat', 'hanning', 'hamming', 'bartlett', 'blackman'")

    s = np.r_[x[radius-1:0:-1], x, x[-2:-radius-1:-1]]
    #print(len(s))
    if window == "flat": #moving average
        w = np.ones(radius,"d")
    else:
        w = eval(f"np.{window}({radius})")

    y = np.convolve(w/w.sum(), s, mode=mode)
    y = y[(radius//2-1):-(radius//2)-1]
    assert len(x) == len(y)

    if keep_dtype:
        y = y.astype(x.dtype)
    
    return y


def ensure_lead_fmt(values:Sequence[Real],
                    n_leads:int=12,
                    fmt:str="lead_first") -> np.ndarray:
    """ finished, checked,

    ensure the `n_leads`-lead (ECG) signal to be of the format of `fmt`

    Parameters
    ----------
    values: sequence,
        values of the `n_leads`-lead (ECG) signal
    fmt: str, default "lead_first", case insensitive,
        format of the output values, can be one of
        "lead_first" (alias "channel_first"), "lead_last" (alias "channel_last")

    Returns
    -------
    out_values: ndarray,
        ECG signal in the format of `fmt`
    """
    out_values = np.array(values)
    lead_dim = np.where(np.array(out_values.shape) == n_leads)[0]
    if not any([[0] == lead_dim or [1] == lead_dim]):
        raise ValueError(f"not valid {n_leads}-lead 1d signal")
    lead_dim = lead_dim[0]

    if (lead_dim == 1 and fmt.lower() in ["lead_first", "channel_first"]) \
        or (lead_dim == 0 and fmt.lower() in ["lead_last", "channel_last"]):
        out_values = out_values.T
        return out_values

    return out_values


def ensure_siglen(values:Sequence[Real], siglen:int, fmt:str="lead_first") -> np.ndarray:
    """ finished, checked,

    ensure the (ECG) signal to be of length `siglen`,
    strategy:
        if `values` has length greater than `siglen`,
        the central `siglen` samples will be adopted;
        otherwise, zero padding will be added to both sides

    Parameters
    ----------
    values: sequence,
        values of the `n_leads`-lead (ECG) signal
    siglen: int,
        length of the signal supposed to have
    fmt: str, default "lead_first", case insensitive,
        format of the input and output values, can be one of
        "lead_first" (alias "channel_first"), "lead_last" (alias "channel_last")

    Returns
    -------
    out_values: ndarray,
        ECG signal in the format of `fmt` and of fixed length `siglen`
    """
    if fmt.lower() in ["channel_last", "lead_last"]:
        _values = np.array(values).T
    else:
        _values = np.array(values).copy()
    original_siglen = _values.shape[1]
    n_leads = _values.shape[0]

    if original_siglen >= siglen:
        start = (original_siglen - siglen) // 2
        end = start + siglen
        out_values = _values[..., start:end]
    else:
        pad_len = siglen - original_siglen
        pad_left = pad_len // 2
        pad_right = pad_len - pad_left
        out_values = np.concatenate([np.zeros((n_leads, pad_left)), _values, np.zeros((n_leads, pad_right))], axis=1)

    if fmt.lower() in ["channel_last", "lead_last"]:
        out_values = out_values.T
    
    return out_values


def gen_gaussian_noise(siglen:int, mean:Real=0, std:Real=0) -> np.ndarray:
    """ finished, checked,

    generate 1d Gaussian noise of given length, mean, and standard deviation

    Parameters
    ----------
    siglen: int,
        length of the noise signal
    mean: real number, default 0,
        mean of the noise
    std: real number, default 0,
        standard deviation of the noise

    Returns
    -------
    gn: ndarray,
        the gaussian noise of given length, mean, and standard deviation
    """
    gn = np.random.normal(mean, std, siglen)
    return gn


def gen_sinusoidal_noise(siglen:int,
                         start_phase:Real,
                         end_phase:Real,
                         amplitude:Real,
                         amplitude_mean:Real=0,
                         amplitude_std:Real=0) -> np.ndarray:
    """ finished, checked,

    generate 1d sinusoidal noise of given length, amplitude, start phase, and end phase

    Parameters
    ----------
    siglen: int,
        length of the (noise) signal
    start_phase: real number,
        start phase, with units in degrees
    end_phase: real number,
        end phase, with units in degrees
    amplitude: real number,
        amplitude of the sinusoidal curve
    amplitude_mean: real number,
        mean amplitude of an extra Gaussian noise
    amplitude_std: real number, default 0,
        standard deviation of an extra Gaussian noise

    Returns
    -------
    sn: ndarray,
        the sinusoidal noise of given length, amplitude, start phase, and end phase
    """
    sn = np.linspace(start_phase, end_phase, siglen)
    sn = amplitude * np.sin(np.pi * sn / 180)
    sn += gen_gaussian_noise(siglen, amplitude_mean, amplitude_std)
    return sn


def gen_baseline_wander(siglen:int,
                        fs:Real,
                        bw_fs:Union[Real,Sequence[Real]],
                        amplitude:Union[Real,Sequence[Real]],
                        amplitude_mean:Real=0,
                        amplitude_std:Real=0) -> np.ndarray:
    """ finished, checked,

    generate 1d baseline wander of given length, amplitude, and frequency

    Parameters
    ----------
    siglen: int,
        length of the (noise) signal
    fs: real number,
        sampling frequency of the original signal
    bw_fs: real number, or list of real numbers,
        frequency (frequencies) of the baseline wander
    amplitude: real number, or list of real numbers,
        amplitude of the baseline wander (corr. to each frequency band)
    amplitude_mean: real number, default 0,
        mean amplitude of an extra Gaussian noise
    amplitude_std: real number, default 0,
        standard deviation of an extra Gaussian noise

    Returns
    -------
    bw: ndarray,
        the baseline wander of given length, amplitude, frequency

    Example
    -------
    >>> gen_baseline_wander(4000, 400, [0.4,0.1,0.05], [0.1,0.2,0.4])
    """
    bw = gen_gaussian_noise(siglen, amplitude_mean, amplitude_std)
    if isinstance(bw_fs, Real):
        _bw_fs = [bw_fs]
    else:
        _bw_fs = bw_fs
    if isinstance(amplitude, Real):
        _amplitude = list(repeat(amplitude, len(_bw_fs)))
    else:
        _amplitude = amplitude
    assert len(_bw_fs) == len(_amplitude)
    duration = (siglen / fs)
    for bf, a in zip(_bw_fs, _amplitude):
        start_phase = np.random.randint(0,360)
        end_phase = duration * bf * 360 + start_phase
        bw += gen_sinusoidal_noise(siglen, start_phase, end_phase, a, 0, 0)
    return bw


def remove_spikes_naive(sig:np.ndarray) -> np.ndarray:
    """ finished, checked,

    remove `spikes` from `sig` using a naive method proposed in entry 0416 of CPSC2019

    `spikes` here refers to abrupt large bumps with (abs) value larger than 20 mV,
    do NOT confuse with `spikes` in paced rhythm

    Parameters
    ----------
    sig: ndarray,
        single-lead ECG signal with potential spikes
    
    Returns
    -------
    filtered_sig: ndarray,
        ECG signal with `spikes` removed
    """
    b = list(filter(lambda k: k > 0, np.argwhere(np.abs(sig)>20).squeeze(-1)))
    filtered_sig = sig.copy()
    for k in b:
        filtered_sig[k] = filtered_sig[k-1]
    return filtered_sig


def get_ampl(sig:np.ndarray,
             fs:Real,
             fmt:str="lead_first",
             window:Real=0.2,
             critical_points:Optional[Sequence]=None) -> Union[float, np.ndarray]:
    """ finished, checked,

    get amplitude of a signal (near critical points if given)

    Parameters
    ----------
    sig: ndarray,
        (ecg) signal
    fs: real number,
        sampling frequency of the signal
    fmt: str, default "lead_first",
        format of the signal,
        "channel_last" (alias "lead_last"), or
        "channel_first" (alias "lead_first"),
        ignored if sig is 1d array (single-lead)
    window: int, default 0.2s,
        window length of a window for computing amplitude, with units in seconds
    critical_points: ndarray, optional,
        positions of critical points near which to compute amplitude,
        e.g. can be rpeaks, t peaks, etc.

    Returns
    -------
    ampl: float, or ndarray,
        amplitude of the signal
    """
    if fmt.lower() in ["channel_last", "lead_last"]:
        _sig = sig.T
    else:
        _sig = sig.copy()
    _window = int(round(window * fs))
    half_window = _window // 2
    _window = half_window * 2
    if _sig.ndim == 1:
        ampl = 0
    else:
        ampl = np.zeros((_sig.shape[0],))
    if critical_points is not None:
        s = np.stack(
            [
                ensure_siglen(
                    _sig[...,max(0,p-half_window):min(_sig.shape[-1],p+half_window)],
                    siglen=_window,
                    fmt="lead_first") \
                for p in critical_points
            ],
            axis=-1
        )
        # the following is much slower
        # for p in critical_points:
        #     s = _sig[...,max(0,p-half_window):min(_sig.shape[-1],p+half_window)]
        #     ampl = np.max(np.array([ampl, np.max(s,axis=-1) - np.min(s,axis=-1)]), axis=0)
    else:
        s = np.stack(
            [_sig[..., idx*half_window: idx*half_window+_window] for idx in range(_sig.shape[-1]//half_window-1)],
            axis=-1
        )
        # the following is much slower
        # for idx in range(_sig.shape[-1]//half_window-1):
        #     s = _sig[..., idx*half_window: idx*half_window+_window]
        #     ampl = np.max(np.array([ampl, np.max(s,axis=-1) - np.min(s,axis=-1)]), axis=0)
    ampl = np.max(np.max(s,axis=-2) - np.min(s,axis=-2), axis=-1)
    return ampl
