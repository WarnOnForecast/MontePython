import scipy
from scipy import spatial
import numpy as np
import pandas as pd
import skimage.measure 
from skimage.measure import regionprops, regionprops_table
import math 
import collections
from datetime import datetime
import itertools


def calc_dist(xy1, xy2):
    """ xy1 = (x1,y1) and xy2 = (x2,y2)"""
    dist =  (xy1[0] - xy2[0])**2 + (xy1[-1] - xy2[-1])**2
    if np.isnan([dist]):
        return 0
    
    return dist

class ObjectTracker:
    """
    ObjectTracker performs simple object tracking by linking together data from time 
    step to time step with the most overlap.
    
    ObjectTrackers tracks storm data in time by linking together data from time 
    step to time step based on highest overlap. When multiple past data overlap
    with a single object in the future (i.e., merging), the merged object retains 
    the label of largest preceding object. Similar for splitting (i.e., multiple 
    future data overlapping a single past object), only the largest object 
    retains the label of the previous object while the other data maintain 
    their new, unique labels. 
    
    As a correction measure, the user can optionally set mend_tracks=True, 
    in which cases broken tracks are combined to produce longer tracks. 
    To perform the mend, we project the end of each track forward one time step 
    based on estimated storm motion and if the start of another track 
    at that time step is within 9 km (can make it an arg in the future), then
    that track is mended the projected track and then re-labelled to that 
    of the projected track. 


    Parameters 
    -----------
    percent_overlap : float, default = 0.0
        The amount of overlap to be consider a possible match for tracking. Default method 
        assumes that any overlap is cause for a possible match. 
            
    mend_track: True/Flat (default=False)
        if True, apply the second pass method that mends broken tracks (described above) 
    
    mend_dist : int (default = 3)
        Number of grid spaces as the maximum distance to use when mending tracks together.
        
    
     Attributes
     --------------
         trackprops : pandas.DataFrame
            Dataframe containing track duration, length, x-,y-coordinates of the track. 
        
    
    Author: Montgomery Flora (git: monte-flora) 
    Email : monte.flora@noaa.gov 
    """
    def __init__( self, percent_overlap=0.0, mend_tracks=False, mend_dist=3):
        self._percent_overlap = percent_overlap
        self._mend_tracks = mend_tracks
        self._mind_dist = mend_dist

    def track(self, data): 
        """ Given a 3D labelled dataset (the first dimension being time) 
            track the labelled data in time. 
        
        Parameters
        ----------
        data : array-like of shape (NT, NY, NX) or list of 2D arrays 
            Labelled data (integer values) from different times.
           

        Returns
        ----------
        tracks : array-like of shape (NT, NY, NX) or list of 2D arrays 
            Labelled data where interger values for different time steps
            are meaningful. I.e., the label 1 at different time indices 
            is referencing the same object at different times. 
        """
        # If neccesary, convert to np.array. 
        if not isinstance(data, np.ndarray):
            data = np.array(data)
        
        # Check that the data is 3-dimensional. 
        if np.ndim(data) != 3:
            raise ValueError('data has to be 3 dimensional!') 
        
        # Re-label the data such that each object has a unique label. 
        tracks = self.get_unique_labels(data)
        
        for t in np.arange(tracks.shape[0]-1):
            # Get these labels and the labels from the next time step 
            # and match them based on percent overlap. 
            current_data, future_data = tracks[t,:,:], tracks[t+1,:,:]
            labels_before, labels_after  = self.match(current_data, future_data)
            
            # Compute the area for the before and after objects. Used for determing 
            # the retaining label in cases of merging/splitting. 
            areas_before, areas_after = self._get_area(current_data), self._get_area(future_data)
            
            # Check for mergers.
            labels_before, labels_after = self.check_for_mergers(labels_before, labels_after, areas_before)
            
            # Check for splits. 
            labels_before, labels_after = self.check_for_splits(labels_before, labels_after, areas_after)
            
            
            # This is where the tracking is done. We re-label the objects 
            # at a future time if it is matched to a current object. 
            for label_i, label_f in zip(labels_before, labels_after):
                tracks[t+1, future_data == label_f] = label_i
  
        # Do a final re-label so that np.max(relabel_data) == number of tracked data. 
        tracks = self.relabel(tracks)
        
        # Apply a mend to broken tracks (optional).
        if self._mend_tracks:
            # Check if the track is within 9 km. 
            tracks = self.mend_broken_tracks(tracks, mend_dist=3)
        
        self.tracks=tracks 
        
        return tracks
    
    @property
    def trackprops(self,):
        """
        Similar to skimage.measure.regionprops_table, this attribute returns 
        a dataframe with track properties. 
        
        Properties:
        -label : Object integer label 
        -duration : Number of timesteps a given object exists for. 
        -length: Total distance traversed per object. 
        """
        # TODO: Add geopandas and then add the x-,y- tracks to the trackprops
        
        if not hasattr(self, 'tracks'):
            raise AttributeError('Must create the tracked data using .track_data()!') 
       
        x_cent, y_cent = self.get_track_path(self.tracks)
        labels = list(x_cent.keys())
        duration = [np.count_nonzero(~np.isnan(x_cent[label])) for label in labels]
        
        xy_pairs = [list(zip(x_cent[label],y_cent[label])) for label in labels]
        length = [ np.sum([calc_dist(xy[i], xy[i+1]) for i in range(len(xy)-1)]) for xy in xy_pairs]
        
        data = { 
                 'labels' : labels, 
                 'duration' : duration,
                 'length' : length
        }
    
        return pd.DataFrame(data) 
    

    def _get_area(self, arr):
        """
        Get the area of each object and return a dict.
        """
        return {label : np.count_nonzero(arr==label) for label in np.unique(arr)[1:]}
        

    def check_for_mergers(self, labels_before, labels_after, areas_before):
        """
        Mergers are cases where there are non-unique labels in the after step
        (i.e., two or more labels become one). For longer tracks, 
        the merged object label is inherited from the largest object in 
        the merger. 
    
        E.g., 
    
        labels_before = [1,2,3,4,4] - > [2,3,4,4] 
        labels_after  = [5,5,6,7,8] - > [5,6,7,8]
    
        Parameters
        --------------------
        labels_before : list of ints 
        labels_after : list of ints 
        areas_before : dict 
            object label, area pairs for the prior objects 
    
        Returns
        --------------------
        labels_before, labels_after 
        
        """
        # Determine if there is a merged based on non-unqique labels. 
        unique_labels_after, counts_after = np.unique(labels_after, return_counts=True)
        if any(counts_after>1):
            # Get the labels that non-unique. 
            merged_labels = unique_labels_after[counts_after>1]

            for label in merged_labels:
                # This should be 2 or more labels (which are being merged together).
                potential_label_for_merged_obj = [l for i, l in enumerate(labels_before) if labels_after[i] == label]
                # Sort the potential merged object labels by area. Keep the largest object and remove the 
                # others. 
                inds = np.argsort([areas_before[label] for label in potential_label_for_merged_obj])[::-1]
                labels_sorted = np.array(potential_label_for_merged_obj)[inds]
                for label in labels_sorted[1:]:
                    index = labels_before.index(label)
                    del labels_before[index]
                    del labels_after[index]
    
        return labels_before, labels_after

    def check_for_splits(self, labels_before, labels_after, areas_after):
        """
        Splits are cases where there are non-unique labels in the before step
        (i.e., one labels becomes two or more). For longer tracks, 
        of the split labels, the largest one inherits the before step label. 
    
    
        labels_before = [1,2,3,4,4] - > [1,2,3,4] 
        labels_after  = [5,5,6,7,8] - > [5,5,6,7]
    
    
        Parameters
        --------------------
        labels_before : list of ints 
        labels_after : list of ints 
        areas_after : dict 
            object label, area pairs for the future objects 
    
        Returns
        --------------------
        labels_before, labels_after 
        """
        unique_labels_before, counts_before = np.unique(labels_before, return_counts=True)
        if any(counts_before>1): 
            split_labels = unique_labels_before[counts_before>1]
    
            for label in split_labels: 
                # This should be 2 or more labels (which are being merged together).
                potential_label_for_split_obj = [l for i, l in enumerate(labels_after) if labels_before[i] == label]  
                # Sort the potential split object labels by area. Keep the largest object and remove the 
                # others. 
                inds = np.argsort([areas_after[label] for label in potential_label_for_split_obj])[::-1]
                labels_sorted = np.array(potential_label_for_split_obj)[inds]
        
                for label in labels_sorted[1:]:
                    index = labels_after.index(label)
                    del labels_before[index]
                    del labels_after[index]
    
        return labels_before, labels_after 
    
    
    def get_unique_labels(self, data):
        """Ensure that initially, each object for the different times have a unique label"""
        if not isinstance(data, np.ndarray):
            data = np.array(data)
        
        unique_track_set = np.zeros(data.shape, dtype=np.int32)
        
        num = 1
        for i in range(len(data)):
            current_obj = data[i,:,:]
            for label in np.unique(current_obj)[1:]:
                unique_track_set[i, current_obj==label] += num
                num+=1
                
        return unique_track_set 

    def relabel(self, data):
        """Re-label data so that np.max(data) == number of objects."""
        relabelled_data = np.copy(data)
        #Ignore the zero label
        unique_labels = np.unique(data)[1:]
        for i, label in enumerate(unique_labels):
            relabelled_data[data==label] = i+1
    
        return relabelled_data

    def match(self, data_a, data_b):
        """ Match two set of data valid at a single or multiple times.
        Parameters
        -------------
            object_set_a, 2D array or list of 2D arrays, object labels at a single or multiple times
            object_set_b, 2D array or list of 2D arrays, object labels at a single or multiple times
        Returns
        -------------
            Lists of matched labels in set a, matched labels in set b,
            and tuples of y- and x- components of centroid displacement of matched pairs
        """
        matched_object_set_a_labels  = [ ]
        matched_object_set_b_labels  = [ ]
        
        possible_matched_pairs = self.find_possible_matches(data_a, data_b) 

        # Reverse means large values first! 
        sorted_possible_matched_pairs  = sorted(possible_matched_pairs, key=possible_matched_pairs.get, reverse=True) 
        for label_a, label_b in sorted_possible_matched_pairs:
            # One to one matching is deprecated! 
            #if self.one_to_one:
            if label_a not in matched_object_set_a_labels and label_b not in matched_object_set_b_labels: 
                #otherwise pair[0] has already been matched!
                matched_object_set_a_labels.append(label_a)
                matched_object_set_b_labels.append(label_b)
            #else:
            #    if label_a not in matched_object_set_a_labels: 
            #        #otherwise pair[0] has already been matched!
            #        matched_object_set_a_labels.append(label_a)
            #        matched_object_set_b_labels.append(label_b)
       
        return matched_object_set_a_labels, matched_object_set_b_labels
    
    def percent_intersection(self, region_a, region_b):
        """
        Compute percent overlap with the region coordinates0
        """
        # Converts the input to tuples so they can be used as
        # keys (i.e., become hashable)
        region_a_coords = list(set(map(tuple, region_a.coords)))
        region_b_coords = list(set(map(tuple, region_b.coords)))
    
        denom = (len(region_a_coords)+ len(region_b_coords))
        percent_overlap_coords = float(len(list(set(region_a_coords).intersection(region_b_coords))) / denom)
    
        return percent_overlap_coords
    
    def find_possible_matches(self, data_a, data_b): 
        """ Finds matches based on amount of intersection between data at time = t and time = t+1.
        Parameters 
        -----------
            regionprops_set_a, skimage.measure.regionprops for object_set_a
            regionprops_set_b, skimage.measure.regionprops for object_set_b
            
        Returns 
        ----------
            Dictionary of tuples of possible matched object pairs associated with their total interest score 
            Dictionary of y- and x-component of centroid displacement of possible matched object pairs             
        """
        
        # Re-new object 
        object_props_a, object_props_b = [regionprops(data.astype(int)) for data in [data_a, data_b]]
        
        # Find possible matched pairs 
        possible_matched_pairs = { }
        for region_a in object_props_a:
            for region_b in object_props_b:
                percent_overlap = self.percent_intersection(region_a, region_b)
                if percent_overlap > self._percent_overlap:
                    possible_matched_pairs[(region_a.label, region_b.label)] = percent_overlap
        
        return possible_matched_pairs
        
    def get_centroid(self, df, label):
        try:
            df=df.loc[df['label'] == label]
            x_cent, y_cent = df['centroid-0'], df['centroid-1']
            x_cent=int(x_cent)
            y_cent=int(y_cent)
        except:
            return np.nan, np.nan
    
        return x_cent, y_cent 
    
    def get_track_path(self, tracks):
        """ Create track path. """
        properties = ['label', 'centroid']
        object_dfs = [pd.DataFrame(regionprops_table(tracks, properties=properties)) 
              for tracks in tracks]
        
        unique_labels = np.unique(tracks)[1:]
        centroid_x = {l : [] for l in unique_labels}
        centroid_y = {l : [] for l in unique_labels}
    
        for df in object_dfs:
            for label in unique_labels:
                x,y = self.get_centroid(df, label)
                centroid_x[label].append(x)
                centroid_y[label].append(y)

        return centroid_x, centroid_y
    
    def find_track_start_and_end(self, data):
        """
        Based on the x-centriod or y-centroid values for a track, 
        determine when the time index when the track starts and stops. 
        """
        time_indices = [i for i, v in enumerate(data) if not np.isnan([v])]
        return time_indices[0], time_indices[-1]
 
    def mend_broken_tracks(self, tracks, mend_dist=3):
        """
        Mend broken tracks by project track ends forward 
        in time based on estimated storm motion and 
        search for tracks that start in that projected area. 
        If close enough, assume that those two tracks 
        should be combined. Re-label that new tracks with 
        the projected tracks label. 
        """
        new_tracks = np.copy(tracks)
        x_cent, y_cent = self.get_track_path(tracks)
    
        # Get the start and end 
        track_start_end = {label : self.find_track_start_and_end(x_cent[label]) for label in x_cent.keys()}
    
        for label in x_cent.keys():
            # Compute the project storm position based on
            # the estimated storm motion. Since time is 
            # constant, we do not need to consider it. 
            dx = np.mean(np.diff(x_cent[label])) 
            dy = np.mean(np.diff(y_cent[label])) 

            # Get the start and end time index for this track. 
            start_ind, end_ind = track_start_end[label]
    
            x_proj = x_cent[label][end_ind] + dx
            y_proj = x_cent[label][end_ind] + dy

            # Given the end index of this track, we are looking for tracks that 
            # started when this tracked ended or during the next time step. 
            other_labels = [l for l in x_cent.keys() if l != label and track_start_end[l][0] in [end_ind, end_ind+1] ]
            for other_label in other_labels:
                x_val = x_cent[other_label][end_ind]
                x = x_val if x_val is not np.nan else x_cent[other_label][end_ind+1]
        
                y_val = y_cent[other_label][end_ind]
                y = y_val if y_val is not np.nan else y_cent[other_label][end_ind+1]
        
                # Is there an existing tracks start point that is within some
                # distance on this projected end of this track. If so,
                # link them together and re-label the existing track to this label. 
                dist = calc_dist((x_proj, y_proj), (x, y))
                if dist <= mend_dist and dist>0:
                    new_tracks[tracks==other_label] = label 
    
        return new_tracks