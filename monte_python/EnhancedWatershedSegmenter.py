#
# The Enhanced Watershed code is based on the algorithm from Lakshmanan et al. (2009) and was adapted
# from Java code found at https://github.com/lakshmanok/asgbook/blob/master/src/edu/ou/asgbook/segmentation/EnhancedWatershedSegmenter.java.
#
# References
# Valliappa Lakshmanan, Kurt Hondl, and Robert Rabin, 2009: An Efficient, General-Purpose 
#  Technique for Identifying Storm Cells in Geospatial Images. J. Atmos. Oceanic Technol., 26, 523-537.
# https://journals.ametsoc.org/doi/full/10.1175/2008JTECHA1153.1
"""
@author: David John Gagne (djgagne@ou.edu) and Montgomery Flora (monte.flora@noaa.gov)
"""

import numpy as np
from scipy.ndimage import find_objects
from collections import OrderedDict
#import numba
#from numba.core.errors import NumbaDeprecationWarning, NumbaPendingDeprecationWarning
#import warnings

#warnings.simplefilter('ignore', category=NumbaDeprecationWarning)
#warnings.simplefilter('ignore', category=NumbaPendingDeprecationWarning)


class EnhancedWatershed(object):
    """
    The enhanced watershed performs image segmentation using a modified version of the traditional watershed technique.
    It includes a size criteria and creates foothills around each object to keep them distinct. The object is used to
    store the quantization and size parameters. It can be used to watershed multiple grids.

    Attributes:
        min_thresh (int): minimum pixel value for pixel to be part of a region
        data_increment (int): quantization interval. Use 1 if you don't want to quantize
        max_thresh (int): values greater than maxThresh are treated as the maximum threshold
        area_threshold (int): clusters smaller than this threshold are ignored.
    """
    

    def __init__(self, min_thresh, max_thresh, area_threshold, dist_btw_objects, data_increment=1):
        self.min_thresh = min_thresh
        self.data_increment = data_increment
        self.max_thresh = max_thresh
        self.max_size = area_threshold
        self.min_size = 6
        self.dist_btw_objects = dist_btw_objects
        self.max_bin = int((self.max_thresh - self.min_thresh) / self.data_increment)
        self.UNMARKED = -1
        self.GLOBBED = -3
        self.TOOSMALL = -4

    def label(self, input_grid, only_objects=True):
        """
        Labels input grid using enhanced watershed algorithm.

        Args:
            input_grid (numpy.ndarray): Grid to be labeled.
            only_objects (bool): Only return object pixel values on final grid

        Returns:
            Array of labeled pixels
        """
        pixels, q_data = self.quantize(input_grid)
        centers = self.find_local_maxima(pixels, q_data)
        marked = self.grow_centers(centers, q_data)
        if only_objects:
            marked = np.where(marked > 0, marked, 0)
        return marked

    @staticmethod
    def size_filter(labeled_grid, min_size):
        """
        Removes labeled objects that are smaller than min_size, and relabels the remaining objects.

        Args:
            labeled_grid: Grid that has been labeled
            min_size: Minimium object size.
        Returns:
            Labeled array with re-numbered objects to account for those that have been removed
        """
        out_grid = np.zeros(labeled_grid.shape, dtype=int)
        slices = find_objects(labeled_grid)
        j = 1
        for i, s in enumerate(slices):
            box = labeled_grid[s]
            size = np.count_nonzero(box == i + 1)
            if size >= min_size and box.shape[0] > 1 and box.shape[1] > 1:
                out_grid[np.where(labeled_grid == i + 1)] = j
                j += 1
        return out_grid

    #@numba.jit(fastmath=True, forceobj=True) 
    def find_local_maxima(self, pixels, q_data):
        """
        Finds the local maxima in the inputGrid and perform region growing to identify objects.

        Args:
            pixels: dictionary of quantized pixel values
            q_data: 2D array representation of quantized input data
        Returns:
            array with labeled objects.
        """
        centers = OrderedDict()
        for p in pixels.keys():
            centers[p] = []
        marked = np.ones(q_data.shape, dtype=np.int32) * self.UNMARKED
        MIN_INFL = int(np.round(1 + 0.5 * np.sqrt(self.dist_btw_objects)))
        MAX_INFL = 2 * MIN_INFL
        marked_so_far = []
        # Find the maxima. These are high-values with enough clearance
        # around them.
        # Work from high to low bins. The pixels in the highest bin mark their
        # neighborhoods first. If you did it from low to high the lowest maxima
        # would mark their neighborhoods first and interfere with the identification of higher maxima.
        for b in sorted(pixels.keys(), reverse=True):
            # Square starts large with high intensity bins and gets smaller with low intensity bins.
            infl_dist = MIN_INFL + int(np.round(float(b) / self.max_bin * (MAX_INFL - MIN_INFL)))
            for p in pixels[b]:
                if marked[p] == self.UNMARKED:
                    ok = False
                    del marked_so_far[:]
                    # Temporarily mark unmarked points in square around point (keep track of them in list
                    # marked_so_far).
                    # If none of the points in square were marked already from a higher intensity center, 
                    # this counts as a new center and ok=True and points will remain marked.
                    # Otherwise ok=False and marked points that were previously unmarked will be unmarked.
                    for (i, j), v in np.ndenumerate(marked[p[0] - infl_dist:p[0] + infl_dist + 1,
                                                    p[1] - infl_dist:p[1] + infl_dist + 1]):
                        if v == self.UNMARKED:
                            ok = True
                            marked[i - infl_dist + p[0], j - infl_dist + p[1]] = b

                            marked_so_far.append((i - infl_dist + p[0], j - infl_dist + p[1]))
                        else:
                            # neighborhood already taken
                            ok = False
                            break
                    # ok if point and surrounding square were not marked already.
                    if ok:
                        # highest point in its neighborhood
                        centers[b].append(p)
                    else:
                        for m in marked_so_far:
                            marked[m] = self.UNMARKED
        return centers

    #@numba.jit(fastmath=True, forceobj=True)
    def grow_centers(self, centers, q_data):
        """
        Once

        Args:
            centers:
            q_data:

        Returns:

        """
        marked = np.ones(q_data.shape, dtype=np.int32) * self.UNMARKED
        deferred_from_last = []
        deferred_to_next = []
        center_keys = np.array(list(centers.keys()))[::-1]
        capture_index = 1
        foothills = []
        # Work from high to low bins.
        for b in center_keys:
            bin_lower = b - 1
            deferred_from_last[:] = deferred_to_next[:]
            del deferred_to_next[:]
            new_centers = len(centers[b])
            old_centers = len(deferred_from_last)
            tot_centers = new_centers + old_centers
            for i in range(tot_centers):
                # done this way to minimize memory overhead of maintaining two lists
                if i < old_centers:
                    center = deferred_from_last[i]
                else:
                    center = centers[b][i - old_centers]
                if bin_lower < 0:
                    bin_lower = 0
                if marked[center] == self.UNMARKED:
                    captured = self.set_maximum(q_data, marked, center, bin_lower, foothills, capture_index)
                    if not captured:
                        # decrement to lower value to see if it'll get big enough
                        deferred_to_next.append(center)
                    else:
                        capture_index += 1
                # this is the last one for this bin
            self.remove_foothills(q_data, marked, b, bin_lower, centers, foothills)
        del deferred_from_last[:]
        del deferred_to_next[:]
        return marked
    
    #@numba.jit(fastmath=True, forceobj=True)
    def set_maximum(self, q_data, marked, center, bin_lower, foothills, capture_index):
        """
        Grow a region at a certain bin level and check if the region has reached the maximum size.

        Args:
            q_data: Quantized data array
            marked: Array marking points that are objects
            center: Coordinates of the center pixel of the region being grown
            bin_lower: Intensity level of lower bin being evaluated
            foothills: List of points that are associated with a center but fall outside the the size or
                intensity criteria
            capture_index:
        Returns:
            True if the object is finished growing and False if the object should be grown again at the next
            threshold level.
        """
        as_bin = []  # pixels to be included in peak
        as_glob = []  # pixels to be globbed up as part of foothills
        marked_so_far = []  # pixels that have already been marked
        will_be_considered_again = False
        as_bin.append(center)
        center_data = q_data[center]
        while len(as_bin) > 0:
            p = as_bin.pop(-1)  # remove and return last pixel in as_bin
            if marked[p] != self.UNMARKED:  # already processed
                continue
            marked[p] = capture_index
            marked_so_far.append(p)

            # check neighbors
            for index, val in np.ndenumerate(marked[p[0] - 1:p[0] + 2, p[1] - 1:p[1] + 2]):
                # is neighbor part of peak or part of mountain?
                if val == self.UNMARKED:
                    pixel = (index[0] - 1 + p[0], index[1] - 1 + p[1])
                    p_data = q_data[pixel]
                    if (not will_be_considered_again) and (p_data >= 0) and (p_data < center_data):
                        will_be_considered_again = True
                    if p_data >= bin_lower:
                        as_bin.append(pixel)
                    # Do not check that this is the closest: this way, a narrow channel of globbed pixels form
                    elif p_data >= 0:
                        as_glob.append(pixel)
        if bin_lower == 0:
            will_be_considered_again = False
        big_enough = len(marked_so_far) >= self.max_size
        if big_enough:
            # remove lower values within region of influence
            foothills.append((center, as_glob))
        
        elif len(marked_so_far) <= self.min_size:
            for m in marked_so_far:
                marked[m] = self.UNMARKED  
        
        elif will_be_considered_again:  # remove the check if you want to ignore regions smaller than max_size
            for m in marked_so_far:
                marked[m] = self.UNMARKED
            del as_bin[:]
            del as_glob[:]
            del marked_so_far[:]
        return big_enough or (not will_be_considered_again)

    #@numba.jit(fastmath=True, forceobj=True)
    def remove_foothills(self, q_data, marked, bin_num, bin_lower, centers, foothills):
        """
        Mark points determined to be foothills as globbed, so that they are not included in
        future searches. Also searches neighboring points to foothill points to determine
        if they should also be considered foothills.

        Args:
            q_data: Quantized data
            marked: Marked
            bin_num: Current bin being searched
            bin_lower: Next bin being searched
            centers: dictionary of local maxima considered to be object centers
            foothills: List of foothill points being removed.
        """
        hills = []
        for foot in foothills:
            center = foot[0]
            hills[:] = foot[1][:]
            # remove all foothills
            while len(hills) > 0:
                # mark this point
                pt = hills.pop(-1)
                marked[pt] = self.GLOBBED
                for s_index, val in np.ndenumerate(marked[pt[0] - 1:pt[0] + 2, pt[1] - 1:pt[1] + 2]):
                    index = (s_index[0] - 1 + pt[0], s_index[1] - 1 + pt[1])
                    # is neighbor part of peak or part of mountain?
                    if val == self.UNMARKED:
                        # will let in even minor peaks
                        if (q_data[index] >= 0) and \
                                (q_data[index] < bin_lower) and \
                                ((q_data[index] <= q_data[pt]) or self.is_closest(index, center, centers, bin_num)):
                            hills.append(index)
        del foothills[:]

    @staticmethod
    def is_closest(point, center, centers, bin_num):
        bin_thresh = int(bin_num / 2)
        p_arr = np.array(point)
        c_arr = np.array(center)
        my_dist = np.sum(np.power(p_arr - c_arr, 2))
        for o_bin in range(bin_thresh, len(centers.keys())):
            for c in centers[o_bin]:
                oc_arr = np.array(c)
                if np.sum(np.power(p_arr - oc_arr, 2)) < my_dist:
                    return False
        return True

    def quantize(self, input_grid):
        """
        Quantize a grid into discrete steps based on input parameters.

        Args:
            input_grid: 2-d array of values

        Returns:
            Dictionary of value pointing to pixel locations, and quantized 2-d array of data
        """
        pixels = dict()
        for i in range(self.max_bin + 1):
            pixels[i] = []

        data = (np.array(input_grid, dtype=np.int32) - self.min_thresh) // self.data_increment
        if self.min_thresh == 0:
            data[data <= 0] = -1
        else:
            data[data < 0] = -1 
        data[data > self.max_bin] = self.max_bin
        good_points = np.where(data >= 0)
        for g in np.arange(good_points[0].shape[0]):
            pixels[data[(good_points[0][g], good_points[1][g])]].append((good_points[0][g], good_points[1][g]))
        return pixels, data

    @staticmethod
    def is_valid(point, shape):
        return np.all((np.array(point) >= 0) & (np.array(shape) - np.array(point) > 0))


def rescale_data(data, data_min, data_max, out_min=0.0, out_max=100.0):
    """
    Rescale your input data so that is ranges over integer values, which will perform better in the watershed.

    Args:
        data: 2D or 3D ndarray being rescaled
        data_min: minimum value of input data for scaling purposes
        data_max: maximum value of input data for scaling purposes
        out_min: minimum value of scaled data
        out_max: maximum value of scaled data

    Returns:
        Linearly scaled ndarray
    """
    return (out_max - out_min) / (data_max - data_min) * (data - data_min) + out_min
