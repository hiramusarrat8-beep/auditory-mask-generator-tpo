# amg_app/utils.py
import numpy as np

def linear_ramp_window(length, ramp_samples):
    """Linear ramp up and down"""
    if ramp_samples <= 0 or ramp_samples * 2 > length:
        return np.ones(length)
    
    window = np.ones(length)
    window[:ramp_samples] = np.linspace(0, 1, ramp_samples)
    window[-ramp_samples:] = np.linspace(1, 0, ramp_samples)
    return window

def tukey_ramp_window(length, ramp_samples):
    """Improved Tukey (tapered cosine) window with flat top"""
    if ramp_samples <= 0 or ramp_samples * 2 > length:
        return np.ones(length)
    
    if ramp_samples * 2 >= length:
        return np.hanning(length)
    
    t = np.linspace(0, 1, length)
    alpha = 2 * ramp_samples / length
    window = np.ones(length)
    
    idx_rise = t < alpha / 2
    window[idx_rise] = 0.5 * (1 - np.cos(2 * np.pi * t[idx_rise] / alpha))
    
    idx_fall = t > 1 - alpha / 2
    window[idx_fall] = 0.5 * (1 - np.cos(2 * np.pi * (1 - t[idx_fall]) / alpha))
    
    return window

def exponential_ramp_window(length, ramp_samples):
    """Exponential ramp up and down"""
    if ramp_samples <= 0 or ramp_samples * 2 > length:
        return np.ones(length)
    
    window = np.ones(length)
    t_rise = np.linspace(0, 1, ramp_samples)
    k = 5
    window[:ramp_samples] = 1 - np.exp(-k * t_rise)
    t_fall = np.linspace(0, 1, ramp_samples)
    window[-ramp_samples:] = np.exp(-k * t_fall)
    return window

def logarithmic_ramp_window(length, ramp_samples):
    """Logarithmic ramp up and down"""
    if ramp_samples <= 0 or ramp_samples * 2 > length:
        return np.ones(length)
    
    window = np.ones(length)
    t_rise = np.linspace(0, 1, ramp_samples)
    k = 9
    window[:ramp_samples] = np.log(1 + k * t_rise) / np.log(1 + k)
    t_fall = np.linspace(0, 1, ramp_samples)
    window[-ramp_samples:] = np.log(1 + k * (1 - t_fall)) / np.log(1 + k)
    return window