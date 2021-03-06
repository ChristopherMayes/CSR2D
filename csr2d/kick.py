from csr2d.deposit import split_particles, deposit_particles, histogram_cic_2d
from csr2d.central_difference import central_difference_z
from csr2d.core import psi_s, psi_x

import numpy as np

from scipy.signal import savgol_filter
from scipy.interpolate import RectBivariateSpline
from scipy.signal import convolve2d, fftconvolve, oaconvolve

import scipy.constants
mec2 = scipy.constants.value('electron mass energy equivalent in MeV')*1e6
c_light = scipy.constants.c
e_charge = scipy.constants.e
r_e = scipy.constants.value('classical electron radius')

import time


def csr2d_kick_calc(z_b, x_b, weight=None,
                    gamma=None,
                    rho=None,
                    nz=100,
                    nx=100,
                    xlim=None,
                    zlim=None,
                    reuse_psi_grids=False,
                    psi_s_grid_old=None,
                    psi_x_grid_old=None,
                    map_f=map,
                    species='electron',
                    debug=False):
    """
    
    Calculates the 2D CSR kick on a set of particles with positions `z_b`, `x_b` and charges `charges`.
    
    
    Parameters
    ----------
    z_b : np.array
        Bunch z coordinates in [m]

    x_b : np.array
        Bunch x coordinates in [m]
  
    weight : np.array
        weight array (positive only) in [C]
        This should sum to the total charge in the bunch
        
    nz : int
        number of z grid points
        
    nx : int
        number of x grid points        
    
    zlim : (min, max) or None
        z grid limits
        
    xlim : (min, max) or None  
        x grid limits
        
    map_f : map function for creating potential grids.
            Examples:
                map (default)
                executor.map
    
    species : str
        Particle species. Currently required to be 'electron'
    
    debug: bool
        If True, returns the computational grids. 
        Default: False
        
              
    Returns
    -------
    dict with:
    
        ddelta_ds : np.array
            relative z momentum kick per meter
            
        dxp_ds : np.array
            relative x momentum kick per meter
        
    
        
    """
    assert species == 'electron', 'TODO: support species {species}'
    assert np.sign(rho) == 1, 'TODO: negative rho'
    
    
    # Grid setup
    if zlim:
        zmin = zlim[0]
        zmax = zlim[1]
    else:
        zmin = z_b.min()
        zmax = z_b.max()

    if xlim:
        xmin = xlim[0]
        xmax = xlim[1]
    else:
        xmin = x_b.min()
        xmax = x_b.max()        
    
    dz = (zmax-zmin)/(nz-1) 
    dx = (xmax-xmin)/(nx-1)  
    
    # Charge deposition
    
    # Old method
    #zx_positions = np.stack((z_b, x_b)).T
    #indexes, contrib = split_particles(zx_positions, charges, mins, maxs, sizes)
    #t1 = time.time();
    #charge_grid = deposit_particles(Np, sizes, indexes, contrib)
    #t2 = time.time();
    
    # Remi's fast code 
    t1 = time.time();
    charge_grid = histogram_cic_2d( z_b, x_b, weight, nz, zmin, zmax, nx, xmin, xmax )
    
    if debug:
        t2 = time.time();
        print('Depositing particles takes:', t2 - t1, 's')    
        
    # Normalize the grid so its integral is unity
    norm = np.sum(charge_grid)*dz*dx
    lambda_grid = charge_grid/norm
    
    # Apply savgol filter
    lambda_grid_filtered = np.array([savgol_filter( lambda_grid[:,i], 13, 2 ) for i in np.arange(nx)]).T
    
    # Differentiation in z
    lambda_grid_filtered_prime = central_difference_z(lambda_grid_filtered, nz, nx, dz, order=1)
    
    # Grid axis vectors 
    zvec = np.linspace(zmin, zmax, nz)
    xvec = np.linspace(xmin, xmax, nx)
    
    beta = np.sqrt(1-1/gamma**2)
    
    t3 = time.time()
    
    if (reuse_psi_grids == True):
        psi_s_grid = psi_s_grid_old
        psi_x_grid = psi_x_grid_old
        
    else:
        # Creating the potential grids 
        zvec2 = np.linspace(2*zmin,2*zmax,2*nz)
        xvec2 = np.linspace(2*xmin,2*xmax,2*nx)
        zm2, xm2 = np.meshgrid(zvec2, xvec2, indexing='ij')

        beta_grid = beta*np.ones(zm2.shape)
        
        # Map (possibly parallel)
        temp = map_f(psi_s, zm2/2/rho, xm2, beta_grid)
        psi_s_grid = np.array(list(temp))
        temp2 = map_f(psi_x, zm2/2/rho, xm2, beta_grid)
        psi_x_grid = np.array(list(temp2))
    
    if debug:
        t4 = time.time();
        print('Computing potential grids take:', t4 - t3, 's')
        
    # Compute the wake via 2d convolution
    conv_s = oaconvolve(lambda_grid_filtered_prime, psi_s_grid, mode='same')
    conv_x = oaconvolve(lambda_grid_filtered_prime, psi_x_grid, mode='same')
    
    if debug:
        t5 = time.time()
        print('Convolution takes:', t5 - t4, 's')    
    
    Ws_grid = (beta**2/rho)*(conv_s)*(dz*dx)
    Wx_grid = (beta**2/rho)*(conv_x)*(dz*dx)
    
    # Interpolate Ws and Wx everywhere within the grid
    Ws_interp = RectBivariateSpline(zvec, xvec, Ws_grid)
    Wx_interp = RectBivariateSpline(zvec, xvec, Wx_grid)

    # Overall factor
    Nb =  np.sum(weight)/e_charge
    kick_factor = r_e*Nb/gamma # m
    
    # Calculate the kicks at the particle locations
    delta_kick = kick_factor * Ws_interp.ev(z_b, x_b)
    xp_kick    = kick_factor * Wx_interp.ev(z_b, x_b)
    
    result = {'ddelta_ds':delta_kick, 'dxp_ds':xp_kick}
    
    if debug:
        result.update({'zvec':zvec, 'xvec':xvec, 'Ws_grid':Ws_grid, 'Wx_grid':Wx_grid, 'psi_s_grid':psi_s_grid, 'psi_x_grid':psi_x_grid, 'charge_grid':charge_grid})
    
    return result