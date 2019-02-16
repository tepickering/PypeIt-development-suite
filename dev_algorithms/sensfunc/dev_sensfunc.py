


import numpy as np
import scipy
import matplotlib.pyplot as plt
import os
from pypeit.core import pydl
import astropy.units as u
from astropy.io import fits
from pypeit.core import flux
from pypeit.core import load
from pypeit.core import coadd2d
from pypeit import utils
from pypeit import msgs
PYPEIT_FLUX_SCALE = 1e-17
from astropy.io import fits



def read_telluric_grid(filename):

    hdul = fits.open(filename)
    wave_grid = hdul[1].data
    model_grid = hdul[0].data

    pg = hdul[0].header['PRES0']+hdul[0].header['DPRES']*np.arange(0,hdul[0].header['NPRES'])
    tg = hdul[0].header['TEMP0']+hdul[0].header['DTEMP']*np.arange(0,hdul[0].header['NTEMP'])
    hg = hdul[0].header['HUM0']+hdul[0].header['DHUM']*np.arange(0,hdul[0].header['NHUM'])
    if hdul[0].header['NAM'] > 1:
        ag = hdul[0].header['AM0']+hdul[0].header['DAM']*np.arange(0,hdul[0].header['NAM'])
    else:
        ag = hdul[0].header['AM0']+1*np.arange(0,1)

    return 10.0*wave_grid, model_grid, pg, tg, hg, ag




def interp_telluric_grid(theta,tell_dict):

    pg = tell_dict['pg']
    tg = tell_dict['tg']
    hg = tell_dict['hg']
    ag = tell_dict['ag']
    model_grid = tell_dict['tell_model']
    press,temp,hum,airmass = theta
    if len(pg) > 1:
        p_ind = int(np.round((press-pg[0])/(pg[1]-pg[0])))
    else:
        p_ind = 0
    if len(tg) > 1:
        t_ind = int(np.round((temp-tg[0])/(tg[1]-tg[0])))
    else:
        t_ind = 0
    if len(hg) > 1:
        h_ind = int(np.round((hum-hg[0])/(hg[1]-hg[0])))
    else:
        h_ind = 0
    if len(ag) > 1:
        a_ind = int(np.round((airmass-ag[0])/(ag[1]-ag[0])))
    else:
        a_ind = 0

    return model_grid[p_ind,t_ind,h_ind,a_ind]

def conv_telluric(wave_grid,tell_model,res):

    loglam = np.log(wave_grid)
    dloglam = np.median(loglam[1:]-loglam[:-1])
    pix = 1.0/res/dloglam/(2.0 * np.sqrt(2.0 * np.log(2))) # number of dloglam pixels per 1 sigma dispersion
    sig2pix = 1.0/pix # number of sigma per 1 pix
    #conv_model = scipy.ndimage.filters.gaussian_filter1d(tell_model, pix)
    # x = loglam/sigma on the wavelength grid from -4 to 4, symmetric, centered about zero.
    x = np.hstack([-1*np.flip(np.arange(sig2pix,4,sig2pix)),np.arange(0,4,sig2pix)])
    # g = Gaussian evaluated at x, sig2pix multiplied in to properly normalize the convolution
    g = (1.0/(np.sqrt(2*np.pi)))*np.exp(-0.5*(x)**2)*sig2pix
    conv_model = scipy.signal.convolve(tell_model,g,mode='same')
    return conv_model

def eval_telluric(theta_tell, wave, tell_dict):

    tellmodel_hires = interp_telluric_grid(theta_tell[:-1], tell_dict)
    tellmodel_conv = conv_telluric(wave, tellmodel_hires, theta_tell[-1])
    tell_pad=tell_dict['tell_pad']
    return tellmodel_conv[tell_pad:-tell_pad]

def sensfunc_old(theta, arg_dict):

    wave_star = arg_dict['wave_star']
    counts_ps = arg_dict['counts_ps']
    counts_ps_ivar = arg_dict['counts_ps_ivar']
    thismask = arg_dict['thismask']
    wave_min = arg_dict['wave_min']
    wave_max = arg_dict['wave_max']
    flux_true = arg_dict['flux_true']
    tell_dict = arg_dict['tell_dict']
    order = arg_dict['order']
    func = arg_dict['func']

    theta_sens = theta[:order+1]
    theta_tell = theta[order+1:]
    sensmodel = utils.func_val(theta_sens, wave_star, func, minx=wave_min, maxx=wave_max)
    tellmodel_conv = eval_telluric(theta_tell, wave_star, tell_dict)
    if np.sum(sensmodel) < 1e-6:
        return np.inf
    else:
        chi_vec = thismask*(sensmodel != 0.0)*(tellmodel_conv*flux_true/(sensmodel + (sensmodel == 0.0)) -
                                               counts_ps)*np.sqrt(counts_ps_ivar)
        chi2 = np.sum(np.square(chi_vec))
    return chi2


def sens_tellfit_old(optfunc, bounds, arg_dict, tol=1e-4, popsize=30, recombination=0.7, disp=True, polish=True, seed=None):

    result = scipy.optimize.differential_evolution(optfunc, args=(arg_dict,), tol=tol,
                                                   bounds=bounds, popsize=popsize,recombination=recombination,
                                                   disp=disp, polish=polish, seed=seed)
    wave_star = arg_dict['wave_star']
    order = arg_dict['order']
    coeff_out = result.x[:order+1]
    tell_out = result.x[order+1:]
    tellfit_conv = eval_telluric(tell_out, wave_star,arg_dict['tell_dict'])
    sensfit = utils.func_val(coeff_out, wave_star, arg_dict['func'], minx=arg_dict['wave_min'], maxx=arg_dict['wave_max'])

    return result, tellfit_conv, sensfit, coeff_out, tell_out

def update_bounds(bounds, delta_coeff, coeff):

    bounds_new = [(this_coeff * delta_coeff[0], this_coeff * delta_coeff[1]) for this_coeff in coeff]
    bounds_tell = bounds[len(coeff_out):]
    bounds_new.extend(bounds_tell)
    return bounds_new



def sensfunc(theta, args):

    thismask, arg_dict = args
    wave_star = arg_dict['wave_star']
    counts_ps = arg_dict['counts_ps']
    counts_ps_ivar = arg_dict['counts_ps_ivar']
    thismask = arg_dict['thismask']
    wave_min = arg_dict['wave_min']
    wave_max = arg_dict['wave_max']
    flux_true = arg_dict['flux_true']
    tell_dict = arg_dict['tell_dict']
    order = arg_dict['order']
    func = arg_dict['func']

    theta_sens = theta[:order+1]
    theta_tell = theta[order+1:]
    sensmodel = utils.func_val(theta_sens, wave_star, func, minx=wave_min, maxx=wave_max)
    tellmodel_conv = eval_telluric(theta_tell, wave_star, tell_dict)
    if np.sum(sensmodel) < 1e-6:
        return np.inf
    else:
        chi_vec = thismask*(sensmodel != 0.0)*(tellmodel_conv*flux_true/(sensmodel + (sensmodel == 0.0)) -
                                               counts_ps)*np.sqrt(counts_ps_ivar)
        chi2 = np.sum(np.square(chi_vec))
    return chi2

def sens_tellfit(thismask, arg_dict):

    # Function that we are optimizing
    sensfunc = arg_dict['sensfunc']
    # Differential evolution parameters
    bounds, tol, popsize, recombination, disp, polish, seed = \
        arg_dict['bounds'], arg_dict['tol'], arg_dict['popsize'], \
        arg_dict['recombination'], arg_dict['disp'], arg_dict['polish'], arg_dict['seed']

    result = scipy.optimize.differential_evolution(sensfunc, args=(thismask, arg_dict,), tol=tol,bounds=bounds, popsize=popsize,
                                                   recombination=recombination,disp=disp, polish=polish, seed=seed)
    wave_star = arg_dict['wave_star']
    order = arg_dict['order']
    counts_ps = arg_dict['counts_ps']
    coeff_out = result.x[:order+1]
    tell_out = result.x[order+1:]
    tellfit_conv = eval_telluric(tell_out, wave_star,arg_dict['tell_dict'])
    sensfit = utils.func_val(coeff_out, wave_star, arg_dict['func'], minx=arg_dict['wave_min'], maxx=arg_dict['wave_max'])
    counts_model = tellfit_conv*arg_dict['flux_true']/(sensfit + (sensfit == 0.0))

    return result, counts_ps, counts_model



iord = 13
spec1dfile = os.path.join(os.getenv('HOME'),'Dropbox/PypeIt_Redux/XSHOOTER/Pypeit_files/PISCO_nir_REDUCED/Science_coadd/spec1d_STD,FLUX.fits')
sobjs, head = load.load_specobjs(spec1dfile)
exptime = head['EXPTIME']
airmass = head['AIRMASS']

wave_mask = sobjs[iord].optimal['WAVE_GRID'] > 0.0
wave = sobjs[iord].optimal['WAVE_GRID'][wave_mask]
counts = sobjs[iord].optimal['COUNTS'][wave_mask]
counts_ivar = sobjs[iord].optimal['COUNTS_IVAR'][wave_mask]

# Create copy of the arrays to avoid modification and convert to electrons / s
wave_star = wave.copy()
counts_ps = counts.copy()/exptime
counts_ps_ivar = counts_ivar.copy() * exptime ** 2
counts_ps_mask = sobjs[iord].optimal['MASK'][wave_mask]

dev_path = os.getenv('PYPEIT_DEV')
xshooter_file = os.path.join(dev_path,'dev_algorithms/sensfunc/xshooter_standards/fEG274.dat')
output = np.loadtxt(xshooter_file)
wave_std = output[:,0]
flux_std = output[:,1]/PYPEIT_FLUX_SCALE
# Create a fake std_dict for EG274
std_dict = {}
std_dict['std_ra'] = head['RA']
std_dict['std_dec'] = head['DEC']
std_dict['exptime'] = exptime
std_dict['airmass'] = head['AIRMASS']
std_dict['std_name'] = ['EG274']
std_dict['cal_file'] = ['EG274']
std_dict['wave'] = wave_std
std_dict['flux'] = flux_std

#std_dict = flux.get_standard_spectrum(star_type=star_type, star_mag=star_mag, ra=ra, dec=dec)

# Interpolate standard star spectrum onto the data wavelength grid
flux_true = scipy.interpolate.interp1d(std_dict['wave'], std_dict['flux'], bounds_error=False,fill_value='extrapolate')(wave_star)

# Load in the telluric grid
resln_fid = 9200.0
telgridfile = os.path.join(dev_path,'dev_algorithms/sensfunc/TelFit_Paranal_NIR_9800_25000_AM1.00_R20000.fits')
tell_wave_grid, tell_model_grid, pg, tg, hg, ag = read_telluric_grid(telgridfile)
# Add some padding
loglam = np.log(wave_star)
dloglam = np.median(loglam[1:] - loglam[:-1])
pix = 1.0/resln_fid/dloglam/(2.0*np.sqrt(2.0*np.log(2)))  # width of one dloglam in sigma space
tell_pad = int(np.ceil(10.0*pix))

ind_lower, ind_upper = coadd2d.get_wave_ind(tell_wave_grid, np.min(wave_star), np.max(wave_star))
tell_wave_grid = tell_wave_grid[ind_lower-tell_pad:ind_upper+tell_pad]
tell_model_grid = tell_model_grid[:,:,:,:,ind_lower-tell_pad:ind_upper+tell_pad]
tell_dict = dict(pg=pg,tg=tg,hg=hg,ag=ag,tell_model=tell_model_grid, tell_pad=tell_pad)

tell_guess = (750.0,0.0,50.0,airmass, 9200.0)
tell_model1 = eval_telluric(tell_guess,wave_star, tell_dict)

sensguess = tell_model1*flux_true/(counts_ps + (counts_ps < 0.0))
inmask = counts_ps_mask & (counts_ps > 0.0) &  np.isfinite(sensguess) & (counts_ps_ivar > 0.0)
order = 7
func = 'legendre'
wave_min = wave_star.min()
wave_max = wave_star.max()

mask, coeff = utils.robust_polyfit_djs(wave_star, sensguess, order, function=func, minx=wave_min, maxx=wave_max,
                                       inmask=inmask, lower=3.0, upper=3.0,use_mad=True)
sensfit_guess = utils.func_val(coeff, wave_star, func, minx=wave_min, maxx=wave_max)
plt.plot(wave_star, sensguess)
plt.plot(wave_star, sensfit_guess)
plt.ylim(-0.1*sensfit_guess.min(),1.3*sensfit_guess.max())
plt.show()

seed = np.fmin(int(np.abs(np.sum(counts_ps[np.isfinite(counts_ps)]))), 2 ** 32 - 1)
random_state = np.random.RandomState(seed=seed)


delta_coeff_coarse = (0.1, 10.0)
delta_coeff_fine = (0.7, 1.3)

bounds = [(this_coeff*delta_coeff_coarse[0], this_coeff*delta_coeff_coarse[1]) for this_coeff in coeff]
bounds_tell = [(tell_dict['pg'].min(), tell_dict['pg'].max()),
               (tell_dict['tg'].min(), tell_dict['tg'].max()),
               (tell_dict['hg'].min(), tell_dict['hg'].max()),
               (tell_dict['ag'].min(), tell_dict['ag'].max())]
bounds.extend(bounds_tell)
bounds.extend([(6000,13000)])

# Params for the iterative rejection, will become optional params
maxiter= 5
maxdev=None
maxrej=None
groupdim=None
groupsize=None
groupbadpix=False
grow=0
sticky=True
use_mad=True
lower = 3.0
upper = 3.0

if use_mad:
    invvar = None
else:
    invvar = counts_ps_ivar

arg_dict = dict(wave_star=wave_star, bounds=bounds, counts_ps=counts_ps, counts_ps_ivar=counts_ps_ivar,
                wave_min=wave_min, wave_max=wave_max, flux_true=flux_true, tell_dict=tell_dict, order=order,
                func=func, sensfunc=sensfunc)

result, ymodel, outmask = utils.robust_optimize(sens_tellfit, inmask, arg_dict, maxiter=maxiter,
                                                lower=lower, upper=upper, sticky=sticky, use_mad=use_mad)

sys.exit(-1)

iter = 0
qdone = False
thismask = np.copy(inmask)
arg_dict = dict(wave_star=wave_star, counts_ps=counts_ps, counts_ps_ivar=counts_ps_ivar, thismask=thismask,
                wave_min=wave_min, wave_max=wave_max, flux_true=flux_true, tell_dict=tell_dict, order=order, func=func,
                tol=tol, )

while (not qdone) and (iter < maxiter):
    arg_dict['thismask'] = thismask
    result, tellfit, sensfit, coeff_out, tell_out = sens_tellfit(sensfunc, bounds, arg_dict, seed=random_state)
    counts_model = tellfit*flux_true/(sensfit + (sensfit == 0.0))
    thismask, qdone = pydl.djs_reject(counts_ps, counts_model, outmask=thismask, inmask=inmask, invvar=invvar,
                                      lower=lower, upper=upper, maxdev=maxdev, maxrej=maxrej,
                                      groupdim=groupdim, groupsize=groupsize, groupbadpix=groupbadpix, grow=grow,
                                      use_mad=use_mad, sticky=sticky)
    #msgs.info()
    nrej = np.sum(arg_dict['thismask'] & np.invert(thismask))
    nrej_tot = np.sum(inmask & np.invert(thismask))
    msgs.info('Iteration #{:d}: nrej={:d} new rejections, nrej_tot={:d} total rejections'.format(iter,nrej,nrej_tot))
    # recenter the bounds for the legendge fit about the last iteration result
    bounds = update_bounds(bounds, delta_coeff_fine, coeff_out)
    iter += 1

if (iter == maxiter) & (maxiter != 0):
    msgs.warn('Maximum number of iterations maxiter={:}'.format(maxiter) + ' reached in sens_tell_fit')
outmask = np.copy(thismask)
if np.sum(outmask) == 0:
    msgs.warn('All points were rejected!!! The fits will be zero everywhere.')

arg_dict['thismask'] = outmask
result, tellfit, sensfit, coeff_out, tell_out = sens_tellfit(sensfunc, bounds, arg_dict, seed=random_state)


plt.plot(wave_star,counts_ps*sensfit)
plt.plot(wave_star,counts_ps*sensfit/(tellfit + (tellfit == 0.0)))
plt.plot(wave_star,flux_true)
plt.ylim(-0.1*flux_true.max(),1.5*flux_true.max())
plt.show()

plt.plot(wave_star,counts_ps, drawstyle='steps-mid',color='k',label='star spectrum',alpha=0.7)
plt.plot(wave_star,tellfit*flux_true/(sensfit + (sensfit == 0.0)),color='red',linewidth=1.0,label='model',zorder=3,alpha=0.7)
plt.ylim(-0.1*counts_ps.max(),1.5*counts_ps.max())
plt.legend()
plt.show()
