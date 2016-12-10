from matplotlib import pyplot as plt
import seaborn as sns
sns.set_style('white')

import pandas as pd
import numpy as np

import warnings

import os
import glob

import skimage
from skimage import io, morphology
from skimage.feature import peak_local_max
from skimage.filters import sobel
from skimage.filters import threshold_adaptive
from skimage.draw import circle_perimeter
from scipy import ndimage

from scipy.spatial.distance import pdist, squareform
import matplotlib.gridspec as gridspec
from scipy.spatial import cKDTree


def split_project(stack):
    """
    Split stack by channels and z-project each channel
    """
    stack = np.copy(stack)
    num = len(stack)
    # gfp channel is images with even index, rfp is odd
    gfp = stack[np.arange(0, num, 2)]
    rfp = stack[np.arange(1, num, 2)]
    gfp = z_project(gfp)
    rfp = z_project(rfp)
    return gfp, rfp

def z_project(stack):
    """
    Z-project based on maximum value.
    """
    z_im = np.maximum.reduce([z for z in stack])
    return z_im

def plot_gallery(images, n_row=3, n_col=4, fig_title=None):
    """
    Helper function to plot a gallery of portraits
    """
    fig = plt.figure(figsize=(1.8 * n_col, 2.4 * n_row))
    for i in range(n_row * n_col):
        ax = fig.add_subplot(n_row, n_col, i + 1)
        ax.imshow(images[i], cmap=plt.cm.gray)
        plt.xticks(())
        plt.yticks(())
    if fig_title: fig.suptitle(fig_title+'\n', fontsize=20)
    plt.tight_layout()
    return None

def fakeRGB2gray(im):
    """
    Check if an RGB image is grayscale and convert if necessary
    """
    try:
        # If the three channels are the same, it is grayscale, get only one
        if ((im[:,:,0] == im[:,:,1]) &  ( im[:,:,2]== im[:,:,0])).all():
            return im[:,:,0]
        else: raise ValueError('Channels are not identical')
    except IndexError: 
        warnings.warn('Image has only one channel')
        return im

def im_hist(im):
    """
    Plot image histogram
    """
    hist, bins = skimage.exposure.histogram(im)
    with sns.axes_style('darkgrid'):
        plt.fill_between(bins, hist, lw=0.25, alpha=0.4)
        plt.yscale('log')
        plt.xlabel('normalized pixel value')
        plt.ylabel('count')

def rectangleROI(im, thresh=None):
    """
    Identify coordinates of rectangular ROI in an image with mostly dark irrelevant pixels
    ROI does not contain all continuous zero columns and rows after threshold
    """
    if not thresh:
        thresh = skimage.filters.threshold_li(im)
    # threshold to get boolean mask
    im_thresh = im > thresh
    # check that something remains after thresholding
    if not np.sum(im_thresh): raise RuntimeError('No pixels pass specified threshold')
    # get all zero rows and columns
    rows = np.nonzero(np.sum(im_thresh, 1))[0]
    cols = np.nonzero(np.sum(im_thresh, 0))[0]
    # remove only continuous zero rows and columns and store coordinates in
    # slice object
    roi_coords = (slice(min(rows),max(rows)+1), slice(min(cols),max(cols)+1))
    return roi_coords

def label_sizesel(im, im_mask, max_int, min_int, min_size, max_size):
    """
    Create and label markers from image mask, 
    filter by area and compute region properties
    """
    markers = morphology.label(im_mask)
    nuclei = skimage.measure.regionprops(markers, im)
    # get only markers within area bounds, above intensity thersh and 
    # not oversaturated
    areas = [n.area for n in nuclei]
    all_labels = np.unique(markers)
    sel_labels = [n.label for n in nuclei if min_size < n.area < max_size \
                    and min_int < n.max_intensity < max_int]
    rem_labels = [l for l in all_labels if l not in sel_labels]
    # remove unselected markers
    for l in rem_labels:
        markers[np.where(np.isclose(markers,l))] = 0

    nuclei = [n for n in nuclei if n.label in sel_labels]

    return markers, nuclei

def nuclei_int(im_g, im_r, plot=False, min_distance=10, manual_selection=False):
    """
    get ratio of nuclei intensities and show which nuclei are being measured
    """

    thresh_r = skimage.filters.threshold_otsu(im_r)
    thresh_g = skimage.filters.threshold_otsu(im_g)
    # Get identical ROI in of both images
    roi = rectangleROI(im_r, thresh_r)
    im_r = im_r[roi]
    im_g = im_g[roi]

    im1 = mask_image(im_r)
    im2 = mask_image(im_g)

    # Nuclei area and intensity bounds
    max_int =  2**cam_bitdepth - 1
    min_int = min(thresh_r, thresh_g) * 2.5
    min_size, max_size = 15, 200

    markers_r, nuclei_r = label_sizesel(im_r, im1, max_int, min_int, min_size, max_size)
    markers_g, nuclei_g = label_sizesel(im_g, im2, max_int, min_int, min_size, max_size)

    if manual_selection:
        nuclei_r, markers_r, nuclei_g, markers_g = manual_sel(im_r, markers_r, 
            nuclei_r, im_g, markers_g, nuclei_g)

    # get nuclei intensities
    int_r = np.array([n.mean_intensity for n in nuclei_r])
    int_g = np.array([n.mean_intensity for n in nuclei_g])

    int_ratio = int_g / int_r

    # Draw circles around identified nuclei for plotting
    im_plot_r = circle_nuclei(nuclei_r, im_r)
    im_plot_g = circle_nuclei(nuclei_g, im_g)

    if plot: 
        plot_nuclei_int(im_plot_r, im_plot_g, int_ratio)

    return int_ratio, int_r, int_g, im_plot_r, im_plot_g


def circle_nuclei(nuclei, im):
    """
    Draw circles around identified nuclei for plotting
    """

    nuclei_c = [n.centroid for n in nuclei]
    circles = []
    for d in (10, 12, 14):
        circles += [circle_perimeter(int(r), int(c), d, shape=im.shape) for (r,c) in nuclei_c]
    im_plot = im.copy()
    for circle in circles:
        im_plot[circle] = np.max(im_plot)
    return im_plot

def plot_nuclei_int(im_plot_r, im_plot_g, int_ratio):
    gs = gridspec.GridSpec(1, 7)
    ax1 = plt.subplot(gs[0:3])
    ax2 = plt.subplot(gs[3:6])
    ax3 = plt.subplot(gs[6])
    ax1.imshow(im_plot_r, plt.cm.viridis)
    ax1.set_title('red channel nuclei', fontsize=20)
    ax2.imshow(im_plot_g, plt.cm.viridis)
    ax2.set_title('green channel nuclei', fontsize=20)
    sns.stripplot(int_ratio, orient='v', size=10, alpha=0.5, cmap='viridis', ax=ax3)
    #ax2.tick_params(axis='y', which='both', labelleft='off', labelright='on')
    ax3.set_ylabel('intensity ratio (gfp/rfp)', fontsize=20)
    #ax2.yaxis.set_label_position("right")
    plt.tight_layout()
    return None

def mask_image(im):
    """
    Create a binary mask to segment nuclei
    """
    im_thresh = threshold_adaptive(im, 15)
    im_thresh = skimage.morphology.remove_small_objects(im_thresh, min_size=min_size)
    im_thresh = ndimage.morphology.binary_fill_holes(im_thresh, morphology.disk(1.8))
    im_thresh = morphology.binary_opening(im_thresh)
    return im_thresh

def manual_sel(im_r, markers_r, nuclei_r, im_g, markers_g, nuclei_g):
    """
    Manual (click) selection of nuclei
    """
    coords_rg = []
    for i in (1,3):
        # click on nuclei
        fig, axes = plt.subplots(1,4, figsize=(25,10))
        axes[0].imshow(im_r, plt.cm.viridis)
        axes[1].imshow(markers_r, plt.cm.Paired)
        axes[2].imshow(im_g, plt.cm.viridis)
        axes[3].imshow(markers_g, plt.cm.Paired)
        axes[i].set_title('Select markers here\n(Press Alt+Click when done)', fontsize=20)
        coords = plt.ginput(100, show_clicks=True)
        coords = [(int(c1), int(c2)) for (c2, c1) in coords]
        plt.close('all')
        coords_rg.append(coords)
    coords_r, coords_g = coords_rg

    def update_sel(markers, nuclei, coords):
        all_labels = np.unique(markers)
        sel_labels = [markers[c] for c in coords]
        rem_labels = [l for l in all_labels if l not in sel_labels]

        # get selected nuclei
        nuclei = [n for n in nuclei if n.label in sel_labels]
        # remove unselected markers
        for l in rem_labels:
            markers[np.where(np.isclose(markers,l))] = 0
        return markers, nuclei

    markers_r, nuclei_r = update_sel(markers_r, nuclei_r, coords_r)
    markers_g, nuclei_g = update_sel(markers_g, nuclei_g, coords_g)


    return nuclei_r, markers_r, nuclei_g, markers_g


%matplotlib

cam_bitdepth = 16

data_dir = '../data/leica_data/' 
# get directories ignoring hidden files (glob does by default) (i.e. .DS_Store)
data_dirs = glob.glob(data_dir + '*')
strains = [s.split('/')[-1] for s in data_dir]
data_cols = ['strain','line','rep', 'int_ratio','int_r', 'int_g']
intensities = pd.DataFrame(columns = data_cols)
for d in data_dirs:
    im_dirs = glob.glob(d + '/*.tif')
    for im_dir in im_dirs:
        # process image
        im_stack = io.imread_collection(im_dir)
        im_g, im_r = split_project(im_stack)
        int_ratio, int_r, int_g, im_plot_r, im_plot_g = nuclei_int(im_g, im_r, plot=0)

        curr_data = pd.DataFrame()
        curr_data['int_r'] = int_r
        curr_data['int_g'] = int_g
        curr_data['int_ratio'] = int_ratio

        # get worm ID info
        name = im_dir.split('/')[-2:] 
        curr_data['strain'] = name[0].split('_')[0]
        curr_data['line'] = name[0].split('_', 1)[-1]
        curr_data['rep'] = name[1].split('.')[0]
        print("Processed worm {0} of line {1}".format(rep, strain+line))

        intensities = pd.concat([intensities, curr_data])
        break






int_ratios = []
im_plots_r = []
im_plots_g = []
#gfp, rfp = gfp[1:], rfp[1:]
for im_num in range(3):
    im_r = rfp[im_num].copy()
    im_g = gfp[im_num].copy()

    int_ratio, i1, i2, im_plot_r, im_plot_g = nuclei_int(im_r, im_g, plot=False)
    int_ratios.append(int_ratio)
    im_plots_r.append(im_plot_r)
    im_plots_g.append(im_plot_g)

plot_nuclei_int(im_plot_r[-1], im_plot_g[-1], int_ratio)
