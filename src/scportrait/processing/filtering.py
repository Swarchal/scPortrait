import numpy as np
import matplotlib.pyplot as plt
from sklearn.mixture import GaussianMixture
from scipy.stats import norm
import os

from skimage.morphology import disk, dilation, erosion
from collections import defaultdict

from scportrait.pipeline.base import Logable
from scportrait.processing.preprocessing import downsample_img_pxs

#for visualization purposes
from scportrait.utils.vis import _custom_cmap

class _BaseFilter(Logable):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_unique_ids(self, mask):
        return np.unique(mask)[1:]  # to remove the background

    def get_updated_mask(self, mask, ids_to_remove):
        """
        Update the given mask by setting the values corresponding to the specified IDs to 0.

        Parameters
        ----------
        mask : numpy.ndarray
            The mask to be updated.
        ids_to_remove : numpy.ndarray
            The IDs to be removed from the mask.

        Returns
        -------
        numpy.ndarray
            The updated mask with the specified IDs set to 0.
        """
        return np.where(np.isin(mask, ids_to_remove), 0, mask)

    def get_downsampled_mask(self, mask):
        return downsample_img_pxs(mask, N=self.downsampling_factor)

    def get_upscaled_mask_basic(self, mask, erosion_dilation=False):
        mask = mask.repeat(self.downsampling_factor, axis=0).repeat(
            self.downsampling_factor, axis=1
        )

        if erosion_dilation:
            mask = erosion(mask, footprint=disk(self.smoothing_kernel_size))
            mask = dilation(mask, footprint=disk(self.smoothing_kernel_size))

        return mask


class SizeFilter(_BaseFilter):
    """
    Filter class for removing objects from a mask based on their size.

    This class provides methods to remove objects from a segmentation mask based on their size.
    If specified the objects are filtered using a threshold range passed by the user. Otherwise,
    this threshold range will be automatically calculated.

    To automatically calculate the threshold range, a gaussian mixture model will be fitted to the data.
    Per default, the number of components is set to 2, as it is assumed that the objects in the mask can be divided into two
    groups: small and large objects. The small objects constitute segmentation artefacts (partial masks that are
    frequently generated by segmentation models like e.g. cellpose) while the large objects
    represent the actual cell masks of interest. Using the fitted model, the filtering thresholds are calculated
    to remove all cells that fall outside of the given confidence interval.

    Parameters
    ----------
    filter_threshold : tuple of floats, optional
        The lower and upper thresholds for object size filtering. If not provided, it will be automatically calculated.
    label : str, optional
        The label of the mask. Default is "segmask".
    log : bool, optional
        Whether to take the logarithm of the size of the objects before fitting the normal distribution. Default is True.
        By enabling this option, the filter will better be able to distinguish between small and large objects.
    plot_qc : bool, optional
        Whether to plot quality control figures. Default is True.
    directory : str, optional
        The directory to save the generated figures. If not provided, the current working directory will be used.
    confidence_interval : float, optional
        The confidence interval for calculating the filtering threshold. Default is 0.95.
    n_components : int, optional
        The number of components in the Gaussian mixture model. Default is 1.
    population_to_keep : str, optional
        For multipopulation models this parameter determines which population should be kept. Options are "largest", "smallest", "mostcommon", "leastcommon". Default is "mostcommon".
        If set to "largest" or "smallest", the model is chosen which has the largest or smallest mean. If set to "mostcommon" or "leastcommon", the model is chosen whose population is least or most common.
    filter_lower : bool, optional
        Whether to filter objects that are smaller than the lower threshold. Default is True.
    filter_upper : bool, optional
        Whether to filter objects that are larger than the upper threshold. Default is True.
    *args
        Additional positional arguments.
    **kwargs
        Additional keyword arguments.

    Examples
    --------
    >>> # Create a SizeFilter object
    >>> filter = SizeFilter(filter_threshold=(100, 200), label="my_mask")
    >>> # Apply the filter to a mask
    >>> filtered_mask = filter.filter(input_mask)
    >>> # Get the object IDs to be removed
    >>> ids_to_remove = filter.get_ids_to_remove(input_mask)
    >>> # Update the mask by removing the identified object IDs
    >>> updated_mask = filter.update_mask(input_mask, ids_to_remove)

    """

    def __init__(
        self,
        filter_threshold=None,
        label="segmask",
        log=True,
        plot_qc=True,
        directory=None,
        confidence_interval=0.95,
        n_components=1,
        population_to_keep="largest",
        filter_lower = True,
        filter_upper = True,
        downsampling_factor=None,
        erosion_dilation=True,
        smoothing_kernel_size=7,
        *args,
        **kwargs,
    ):  
        if directory is not None:
            self.directory = directory
        else:
            self.directory = os.getcwd()

        super().__init__(*args, directory = self.directory, **kwargs)

        self.log_values = log
        self.plot_qc = plot_qc
        self.label = label
        self.filter_threshold = filter_threshold
        self.confidence_interval = confidence_interval
        self.n_components = n_components
        self.population_to_keep = population_to_keep
        self.filter_lower = filter_lower
        self.filter_upper = filter_upper

        if downsampling_factor is not None:
            self.downsample = True
            self.downsampling_factor = downsampling_factor
            self.erosion_dilation = erosion_dilation
            self.smoothing_kernel_size = smoothing_kernel_size
        else:
            self.downsample = False

        #sanity check to ensure that some filtering will be performed
        if not self.filter_lower and not self.filter_upper:
            raise ValueError("At least one of filter_lower or filter_upper must be True otherwise no filtering will be performed.")

        # if no directory is provided, use the current working directory

        
        #initialize empty placeholders for results
        self.ids_to_remove = None
        self.mask = None

    def load_mask(self, mask):
        """
        Load the mask to be filtered.

        Parameters
        ----------
        mask : numpy.ndarray
            The mask to be filtered.
        """
        if self.downsample:
            if self.mask is None:
                self.mask = self.downsample_mask(mask)
        else:
            if self.mask is None:
                self.mask = mask

    def _get_gaussian_model_plot(
        self,
        counts,
        means,
        variances,
        weights,
        threshold,
        bins=30,
        figsize=(5, 5),
        alpha=0.5,
        save_figure=True,
    ):
        """
        Plot a histogram of the provided data with fitted Gaussian distributions.

        Parameters
        ----------
        counts : array_like
            The input data array.
        means : array_like
            The means of the Gaussian distributions.
        variances : array_like
            The variances of the Gaussian distributions.
        weights : array_like
            The weights of the Gaussian distributions.
        threshold : tuple
            The lower and upper threshold values.
        label : str
            The label for the histogram.
        n_components : int
            The number of Gaussian components.
        bins : int, optional
            The number of bins in the histogram. Default is 30.
        figsize : tuple, optional
            The size of the figure. Default is (5, 5).
        alpha : float, optional
            The transparency of the histogram bars. Default is 0.5.
        directory : str, optional
            The directory to save the figure. Default is None.
        save_figure : bool, optional
            Whether to save the figure. Default is True.

        Returns
        -------
        fig : matplotlib.figure.Figure
            The generated figure.
        """

        # generate valuerange over which to visualize the distributions
        x = np.linspace(min(counts), max(counts), 1000)

        # initialize the figure
        fig, axs = plt.subplots(1, 1, figsize=figsize)

        # visualize the base histogram
        axs.hist(counts, bins=bins, density=True, alpha=alpha, label=self.label)

        # visualize the fitted Gaussian distributions
        for i in range(self.n_components):
            _pdf = norm.pdf(x, means[i], np.sqrt(variances[i])) * weights[i]
            axs.plot(x, _pdf, "-r", label=f"Gaussian {i}")

        # visualize the threshold values as dotted lines
        if self.filter_lower:
            axs.axvline(
                threshold[0],
                color="blue",
                linestyle="--",
                label=f"Threshold Lower: {threshold[0]:.2f}",
            )

        if self.filter_upper:
            axs.axvline(
                threshold[1],
                color="blue",
                linestyle="--",
                label=f"Threshold Upper: {threshold[1]:.2f}",
            )

        # format the plot
        axs.legend()
        axs.set_title("Histogram and Fitted Distributions")
        fig.tight_layout()
        plt.close(fig)

        # automatically save figure to directory if parameter is specified
        if save_figure:
            fig.savefig(os.path.join(self.directory, f"{self.label}_bimodal_model.png"))

        return fig

    def _get_histogram_plot(
        self,
        values,
        label=None,
        bins=30,
        alpha=0.5,
        figsize=(5, 5),
        save_figure=True,
    ):
        """
        Plot a histogram of the given values.

        Parameters
        ----------
        values : array-like
            The values to be plotted.
        label : str, optional
            The label for the histogram plot.
        bins : int, optional
            The number of bins in the histogram. Default is 30.
        alpha : float, optional
            The transparency of the histogram bars. Default is 0.5.
        figsize : tuple, optional
            The size of the figure. Default is (5, 5).
        save_figure : bool, optional
            Whether to save the figure as an image. Default is True.

        Returns
        -------
        fig : matplotlib.figure.Figure
            The generated figure object.
        """

        fig, axs = plt.subplots(1, 1, figsize=figsize)
        axs.hist(values, bins=bins, density=True, alpha=alpha)
        axs.set_title(label)
        axs.set_xlabel("value")
        axs.set_ylabel("density")
        fig.tight_layout()
        plt.close(fig)

        if save_figure:
            fig.savefig(os.path.join(self.directory, f"{label}_histogram.png"))

        return fig

    def _get_index_population(self, means, weights):
        """
        Returns the index of the model that matches the population of cells to be kept.

        Parameters
        ----------
        means : numpy.ndarray
            An array containing the means of the models.
        weights : numpy.ndarray
            An array containing the weights of the models.

        Returns
        -------
        int
            The index of the model that matches the population criteria.

        Notes
        -----
        The function determines the index of the model based on the population of cells that should be kept.
        The population criteria can be set to "largest", "smallest", "mostcommon", or "leastcommon".
        If the population criteria is set to "largest" or "smallest", the index is determined based on the means array.
        If the population criteria is set to "mostcommon" or "leastcommon", the index is determined based on the weights array.
        """
        if self.population_to_keep == "largest":
            idx = np.argmax(means)
        elif self.population_to_keep == "smallest":
            idx = np.argmin(means)
        elif self.population_to_keep == "mostcommon":
            idx = np.argmax(weights)
        elif self.population_to_keep == "leastcommon":
            idx = np.argmin(weights)
        return idx

    def _calculate_filtering_threshold(self, counts, return_plot = False):
        """
        Calculate the filtering thresholds for the given counts.

        Parameters
        ----------
        counts : numpy.ndarray
            The counts of the data.

        Returns
        -------
        tuple
            A tuple containing the lower and upper filtering thresholds.

        Examples
        --------
        >>> import numpy as np
        >>> from sparcscore.processing.filtering import SizeFilter
        >>> np.random.seed(0)
        >>> counts1 = np.random.normal(0, 1, 1000)
        >>> counts2 = np.random.normal(3, 1, 1000)
        >>> counts = np.concatenate((counts1, counts2))
        >>> size_filter = SizeFilter(log = False)
        >>> thresholds = size_filter.calculate_filtering_threshold(counts)
        >>> thresholds
        (1.0785720179538172, 4.911918901671607)
        """

        # take the log of the counts if log_values is True
        if self.log_values:
            data = np.log(counts)
        else:
            data = counts.copy()

        # reshape the data to have the correct dimensions for fitting the model
        data_reshaped = data.reshape(-1, 1)

        # initialize and fit the model
        gmm = GaussianMixture(n_components=self.n_components, random_state=0)
        gmm.fit(data_reshaped)

        # Get the means, variances, and weights of the fitted Gaussians
        means = gmm.means_.flatten()
        variances = gmm.covariances_.flatten()
        weights = gmm.weights_

        # get index of the model which matches to the population of cells that should be kept
        idx = self._get_index_population(means, weights)

        # calculate the thresholds for the selected model using the given confidence interval
        mu = means[idx]
        sigma = np.sqrt(variances[idx])

        percent = 1 - self.confidence_interval
        lower = percent / 2
        upper = 1 - percent / 2

        lower_threshold = mu + sigma * norm.ppf(lower)
        upper_threshold = mu + sigma * norm.ppf(upper)

        threshold = (lower_threshold, upper_threshold)

        fig = self._get_gaussian_model_plot(
            counts=data,
            means=means,
            variances=variances,
            weights=weights,
            threshold=threshold,
        )

        if self.plot_qc:
            plt.show(fig)  # show the figure if plot_qc is True

        if self.log_values:
            self.filter_threshold = np.exp(threshold)
        else:
            self.filter_threshold = threshold

        self.log(
            f"Calculated threshold for {self.label} with {self.confidence_interval * 100}% confidence interval: {self.filter_threshold}"
        )

        if return_plot:
            return fig
        
    def _get_ids_to_remove(self, input_mask):
        """
        Get the IDs to remove from the input mask based on the filtering threshold.

        Parameters
        ----------
        input_mask : ndarray
            The input mask as a numpy array.

        Returns
        -------
        ndarray
            An array containing the IDs to remove from the input mask.

        Notes
        -----
        This function calculates the filtering threshold based on the pixel counts of the input mask.
        It then identifies the IDs that are outside of the chosen threshold range and returns them as an array.

        The filtering threshold can be automatically calculated if not provided.
        """

        self.load_mask(input_mask)

        # get value counts of the mask
        counts = np.unique(self.mask, return_counts=True)
        
        self.ids = counts[0][1:]
        pixel_counts = counts[1][1:]

        fig = self._get_histogram_plot(pixel_counts, self.label)
        plt.close(fig)

        if self.plot_qc:
            plt.show(fig)

        # automatically calculate filtering threshold if not provided
        if self.filter_threshold is None:
            self._calculate_filtering_threshold(pixel_counts)

        ids_remove = []

        if self.filter_lower:
            _ids = counts[0][1:][np.where(pixel_counts < self.filter_threshold[0])]
            ids_remove.extend(_ids)

            self.log(
                f"Found {len(_ids)} ids to remove from {self.label} mask which are smaller than the chosen threshold range {self.filter_threshold}."
            )
        else:
            _ids = counts[0][1:][np.where(pixel_counts < self.filter_threshold[0])]
            self.log(f"Filtering lower threshold is disabled. Not filtering {len(_ids)} that fall below the threshold range {self.filter_threshold}.")
        
        if self.filter_upper:
            _ids = counts[0][1:][np.where(pixel_counts > self.filter_threshold[1])]
            ids_remove.extend(_ids)

            self.log(
                f"Found {len(_ids)} ids to remove from {self.label} mask which are bigger than the chosen threshold range {self.filter_threshold}."
            )
        else:
            _ids = counts[0][1:][np.where(pixel_counts > self.filter_threshold[1])]
            self.log(f"Filtering upper threshold is disabled. Not filtering {len(_ids)} that fall above the threshold range {self.filter_threshold}.")

        self.ids_to_remove = ids_remove
    
    def visualize_filtering_results(self, return_fig = True, return_maps = False, plot_fig = True):

        mask = self.mask.copy()

        class_ids = set(self.ids)

        #get the ids to visualize as red for discarded 
        ids_discard = list(self.ids_to_remove)
        ids_keep = list(class_ids - set(self.ids_to_remove))

        #generate masks for the two classes
        final_mask = np.where(np.isin(mask, ids_keep), 2, mask)
        final_mask = np.where(np.isin(mask, ids_discard), 1, final_mask)

        #only plot results if requested
        if not plot_fig:
            if return_maps:
                return final_mask
        else:
            #generate the plot
            cmap, norm = _custom_cmap()

            fig, axs = plt.subplots(1, 1, figsize = (10, 10))

            #visualize masks
            if len(final_mask.shape) == 3:
                axs.imshow(np.zeroes(final_mask[0]), cmap=cmap, norm = norm)
                axs.imshow(final_mask[0], cmap=cmap, norm = norm)
            elif len(final_mask.shape) == 2:
                axs.imshow(np.zeroes(final_mask), cmap=cmap, norm = norm)
                axs.imshow(final_mask, cmap=cmap, norm = norm)
            
            axs.axis("off")
            axs.set_title("Filtered {self.label} mask")

            fig.tight_layout()
            if not return_fig:
                plt.show()

                if return_maps:
                    return final_mask
            else:
                if return_maps:
                    return fig, final_mask
                else:
                    return fig
    
    def filter(self, input_mask):
        """
        Filter the input mask based on the filtering threshold.

        Parameters
        ----------
        input_mask : ndarray
            The input mask to be filtered. Expected shape is (X, Y)

        Returns
        -------
        filtered_mask : ndarray
            The filtered mask after settings the IDs which do not fullfill the filtering criteria to 0.

        """

        if self.ids_to_remove is None:
            self._get_ids_to_remove(input_mask)

        return self.get_updated_mask(input_mask, self.ids_to_remove)


class MatchNucleusCytosolIds(_BaseFilter):
    """
    Filter class for matching nucleusIDs to their matching cytosol IDs and removing all classes from the given
    segmentation masks that do not fullfill the filtering criteria.

    Masks only pass filtering if both a nucleus and a cytosol mask are present and have an overlapping area
    larger than the specified threshold. If the threshold is not specified, the default value is set to 0.5.

    Parameters
    ----------
    filtering_threshold : float, optional
        The threshold for filtering cytosol IDs based on the proportion of overlapping area with the nucleus. Default is 0.5.
    downsampling_factor : int, optional
        The downsampling factor for the masks. Default is None.
    erosion_dilation : bool, optional
        Flag indicating whether to perform erosion and dilation on the masks during upscaling. Default is True.
    smoothing_kernel_size : int, optional
        The size of the smoothing kernel for upscaling. Default is 7.
    *args
        Additional positional arguments.
    **kwargs
        Additional keyword arguments.

    Attributes
    ----------
    filtering_threshold : float
        The threshold for filtering cytosol IDs based on the proportion of overlapping area with the nucleus.
    downsample : bool
        Flag indicating whether downsampling is enabled.
    downsampling_factor : int
        The downsampling factor for the masks.
    erosion_dilation : bool
        Flag indicating whether to perform erosion and dilation on the masks during upscaling.
    smoothing_kernel_size : int
        The size of the smoothing kernel for upscaling.
    nucleus_mask : numpy.ndarray
        The nucleus mask.
    cytosol_mask : numpy.ndarray
        The cytosol mask.
    nuclei_discard_list : list
        A list of nucleus IDs to be discarded.
    cytosol_discard_list : list
        A list of cytosol IDs to be discarded.
    nucleus_lookup_dict : dict
        A dictionary mapping nucleus IDs to matched cytosol IDs after filtering.

    Methods
    -------
    load_masks(nucleus_mask, cytosol_mask)
        Load the nucleus and cytosol masks.
    update_cytosol_mask(cytosol_mask)
        Update the cytosol mask based on the matched nucleus-cytosol pairs.
    update_masks()
        Update the nucleus and cytosol masks after filtering.
    match_nucleus_id(nucleus_id)
        Match the given nucleus ID to a cytosol ID based on the overlapping area.
    initialize_lookup_table()
        Initialize the lookup table by matching all nucleus IDs to cytosol IDs.
    count_cytosol_occurances()
        Count the occurrences of each cytosol ID in the lookup table.
    check_for_unassigned_cytosols()
        Check for unassigned cytosol IDs in the cytosol mask.
    identify_multinucleated_cells()
        Identify and discard multinucleated cells from the lookup table.
    cleanup_filtering_lists()
        Cleanup the discard lists by removing duplicate entries.
    cleanup_lookup_dictionary()
        Cleanup the lookup dictionary by removing discarded nucleus-cytosol pairs.
    generate_lookup_table(nucleus_mask, cytosol_mask)
        Generate the lookup table by performing all necessary steps.
    filter(nucleus_mask, cytosol_mask)
        Filter the nucleus and cytosol masks based on the matching results.

    """

    def __init__(
        self,
        filtering_threshold=0.5,
        downsampling_factor=None,
        erosion_dilation=True,
        smoothing_kernel_size=7,
        directory = None,
        *args,
        **kwargs,
    ):
        if directory is not None:
            self.directory = directory
        else:
            self.directory = os.getcwd()
            
        super().__init__(*args, directory = self.directory, **kwargs)

        # set relevant parameters
        self.filtering_threshold = filtering_threshold

        # set downsampling parameters
        if downsampling_factor is not None:
            self.downsample = True
            self.downsampling_factor = downsampling_factor
            self.erosion_dilation = erosion_dilation
            self.smoothing_kernel_size = smoothing_kernel_size
        else:
            self.downsample = False

        # initialize placeholders for masks
        self.nucleus_mask = None
        self.cytosol_mask = None

        # initialize datastructures for saving results
        self._nucleus_lookup_dict = {}
        self.nuclei_discard_list = []
        self.cytosol_discard_list = []
        self.nucleus_lookup_dict = None

    def _load_masks(self, nucleus_mask, cytosol_mask):
        """
        Load the nucleus and cytosol masks into their placeholders.
        This function only loads the masks (and downsamples them if necessary) if this has not already been performed.

        Parameters
        ----------
        nucleus_mask : numpy.ndarray
            The nucleus mask.
        cytosol_mask : numpy.ndarray
            The cytosol mask.
        """
        if self.downsample:
            if self.nucleus_mask is None:
                self.nucleus_mask = self.downsample_mask(nucleus_mask)
            if self.cytosol_mask is None:
                self.cytosol_mask = self.downsample_mask(cytosol_mask)
        else:
            if self.nucleus_mask is None:
                self.nucleus_mask = nucleus_mask
            if self.cytosol_mask is None:
                self.cytosol_mask = cytosol_mask

    def _get_updated_cytosol_mask(self, cytosol_mask):
        """
        Update the cytosol mask based on the matched nucleus-cytosol pairs.

        Parameters
        ----------
        cytosol_mask : numpy.ndarray
            The cytosol mask.

        Returns
        -------
        numpy.ndarray
            The updated cytosol mask.
        """
        updated = np.zeros_like(cytosol_mask, dtype=bool)

        #remove cytosols that need to be deleted
        cytosol_mask = self.get_updated_mask(cytosol_mask, self.cytosol_discard_list)

        for nucleus_id, cytosol_id in self.nucleus_lookup_dict.items():
            condition = np.logical_and(cytosol_mask == cytosol_id, ~updated)
            cytosol_mask[condition] = nucleus_id
            updated = np.logical_or(updated, condition)
        return cytosol_mask

    def _get_updated_masks(self):
        """
        Update the nucleus and cytosol masks after filtering.

        Returns
        -------
        tuple
            A tuple containing the updated nucleus mask and cytosol mask.
        """
        nucleus_mask = self.get_updated_mask(
            self.nucleus_mask, self.nuclei_discard_list
        )
        cytosol_mask = self._get_updated_cytosol_mask(self.cytosol_mask)

        if self.downsample:
            nucleus_mask = self.get_upscaled_mask_basic(
                nucleus_mask, self.erosion_dilation
            )
            cytosol_mask = self.get_upscaled_mask_basic(
                self.cytosol_mask, self.erosion_dilation
            )

        return nucleus_mask, cytosol_mask

    def _match_nucleus_id(self, nucleus_id):
        """
        Match the given nucleus ID to a cytosol ID based on the overlapping area.

        Parameters
        ----------
        nucleus_id : int
            The nucleus ID to be matched.

        Returns
        -------
        int or None
            The matched cytosol ID, or None if no match is found.
        """
        nucleus_pixels = np.where(self.nucleus_mask == nucleus_id)
        potential_cytosol = self.cytosol_mask[nucleus_pixels]

        if np.all(potential_cytosol != 0):
            unique_cytosol, counts = np.unique(potential_cytosol, return_counts=True)
            all_counts = np.sum(counts)
            cytosol_proportions = counts / all_counts

            if np.any(cytosol_proportions >= self.filtering_threshold):
                cytosol_id = unique_cytosol[
                    np.argmax(cytosol_proportions >= self.filtering_threshold)
                ]
                if cytosol_id != 0:
                    self._nucleus_lookup_dict[nucleus_id] = cytosol_id
                    return cytosol_id
                else:
                    self.nuclei_discard_list.append(nucleus_id)
                    return None
            else:
                self.nuclei_discard_list.append(nucleus_id)
                return None
        else:
            self.nuclei_discard_list.append(nucleus_id)
            return None

    def _initialize_lookup_table(self):
        """
        Initialize the lookup table by matching all nucleus IDs to cytosol IDs.
        """
        all_nucleus_ids = self.get_unique_ids(self.nucleus_mask)

        for nucleus_id in all_nucleus_ids:
            self._match_nucleus_id(nucleus_id)

    def _count_cytosol_occurances(self):
        """
        Count the occurrences of each cytosol ID in the lookup table.
        """
        cytosol_count = defaultdict(int)

        for cytosol in self._nucleus_lookup_dict.values():
            cytosol_count[cytosol] += 1

        self.cytosol_count = cytosol_count

    def _check_for_unassigned_cytosols(self):
        """
        Check for unassigned cytosol IDs in the cytosol mask.
        """
        all_cytosol_ids = self.get_unique_ids(self.cytosol_mask)

        for cytosol_id in all_cytosol_ids:
            if cytosol_id not in self._nucleus_lookup_dict.values():
                self.cytosol_discard_list.append(cytosol_id)

    def _identify_multinucleated_cells(self):
        """
        Identify and discard multinucleated cells from the lookup table.
        """
        for nucleus, cytosol in self._nucleus_lookup_dict.items():
            if self.cytosol_count[cytosol] > 1:
                self.nuclei_discard_list.append(nucleus)
                self.cytosol_discard_list.append(cytosol)

    def _cleanup_filtering_lists(self):
        """
        Cleanup the discard lists by removing duplicate entries.
        """
        self.nuclei_discard_list = list(set(self.nuclei_discard_list))
        self.cytosol_discard_list = list(set(self.cytosol_discard_list))

    def _cleanup_lookup_dictionary(self):
        """
        Cleanup the lookup dictionary by removing discarded nucleus-cytosol pairs.
        """
        _cleanup = []
        for nucleus_id, cytosol_id in self._nucleus_lookup_dict.items():
            if nucleus_id in self.nuclei_discard_list:
                _cleanup.append(nucleus_id)
            if cytosol_id in self.cytosol_discard_list:
                _cleanup.append(nucleus_id)

        # ensure we have no duplicate entries
        _cleanup = list(set(_cleanup))
        for nucleus in _cleanup:
            del self._nucleus_lookup_dict[nucleus]

    def get_lookup_table(self, nucleus_mask, cytosol_mask):
        """
        Generate the lookup table by performing all necessary steps.

        Parameters
        ----------
        nucleus_mask : numpy.ndarray
            The nucleus mask.
        cytosol_mask : numpy.ndarray
            The cytosol mask.

        Returns
        -------
        dict
            The lookup table mapping nucleus IDs to matched cytosol IDs.
        """
        self._load_masks(nucleus_mask, cytosol_mask)
        self._initialize_lookup_table()
        self._count_cytosol_occurances()
        self._check_for_unassigned_cytosols()
        self._identify_multinucleated_cells()
        self._cleanup_filtering_lists()
        self._cleanup_lookup_dictionary()

        self.nucleus_lookup_dict = self._nucleus_lookup_dict

        return self.nucleus_lookup_dict

    def visualize_filtering_results(self, return_fig = True, return_maps = False, plot_fig = True):

        nuc_mask = self.nucleus_mask.copy()
        cyto_mask = self.cytosol_mask.copy()

        class_ids_nuc = set(np.unique(nuc_mask)) - set([0])
        class_ids_cyto = set(np.unique(cyto_mask)) - set([0])

        #get the ids to visualize as red for discarded 
        ids_discard_nuc = self.nuclei_discard_list
        ids_keep_nuc = list(set(class_ids_nuc) - set(ids_discard_nuc))

        ids_discard_cyto = self.cytosol_discard_list
        ids_keep_cyto = list(set(class_ids_cyto) - set(ids_discard_cyto))

        #generate masks for the two classes
        final_mask_nuc = np.where(np.isin(nuc_mask, ids_keep_nuc), 2, nuc_mask)
        final_mask_nuc = np.where(np.isin(nuc_mask, ids_discard_nuc), 1, final_mask_nuc)

        final_mask_cyto = np.where(np.isin(cyto_mask, ids_keep_cyto), 2, cyto_mask)
        final_mask_cyto = np.where(np.isin(cyto_mask, ids_discard_cyto), 1, final_mask_cyto)

        #only plot results if requested
        if not plot_fig:
            if return_maps:
                return final_mask_nuc, final_mask_cyto
        else:
            #generate the plot
            cmap, norm = _custom_cmap()

            fig, axs = plt.subplots(1, 1, figsize = (10, 10))

            #visualize masks
            if len(final_mask_nuc.shape) == 3:
                axs[0].imshow(final_mask_nuc[0], cmap=cmap, norm = norm)
                axs[0].imshow(final_mask_cyto[0], cmap=cmap, norm = norm)
            elif len(final_mask_nuc.shape) == 2:
                axs[0].imshow(final_mask_nuc, cmap=cmap, norm = norm)
                axs[0].imshow(final_mask_cyto, cmap=cmap, norm = norm)
            
            axs[0].axis("off")
            axs[0].set_title("Filtered Nucleus and Cytosol Masks")

            fig.tight_layout()
            if not return_fig:
                plt.show()

                if return_maps:
                    return final_mask_nuc, final_mask_cyto
            else:
                if return_maps:
                    return fig, final_mask_nuc, final_mask_cyto
                else:
                    return fig

    def filter(self, nucleus_mask, cytosol_mask):
        """
        Filter the nucleus and cytosol masks based on the matching results and return the updated masks.

        Parameters
        ----------
        nucleus_mask : numpy.ndarray
            The nucleus mask.
        cytosol_mask : numpy.ndarray
            The cytosol mask.

        Returns
        -------
        tuple
            A tuple containing the updated nucleus mask and cytosol mask after filtering.
        """
        self._load_masks(nucleus_mask, cytosol_mask)

        if self.nucleus_lookup_dict is None:
            self.get_lookup_table(nucleus_mask, cytosol_mask)

        return self._get_updated_masks()
