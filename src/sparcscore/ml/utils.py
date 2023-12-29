from scipy.sparse import csr_matrix
import numpy as np
import pandas as pd
import torch
from math import floor

def combine_datasets_balanced(list_of_datasets, class_labels, train_per_class, val_per_class, test_per_class, seed = None):
    """
    Combine multiple datasets to create a single balanced dataset.

    This function produces a balanced dataset by ensuring an equal number of 
    samples from each label source.

    Args:
        list_of_datasets (list[torch.utils.data.Dataset]): List of datasets to be combined.
        class_labels (list[str|int]): List of class labels present in the datasets.
        train_per_class (int): Number of samples per class in the train set.
        val_per_class (int): Number of samples per class in the validation set.
        test_per_class (int): Number of samples per class in the test set.
        seed (None | int ): Seed for the random number generator. Defaults to None.

    Returns:
        torch.utils.data.Dataset: Combined train dataset with balanced samples per class.
        torch.utils.data.Dataset: Combined validation dataset with balanced samples per class.
        torch.utils.data.Dataset: Combined test dataset with balanced samples per class.

    Raises:
        ValueError: If a dataset's length is too small to be split according to the provided sizes.
    """

    elements = [len(el) for el in list_of_datasets]
    rows = np.arange(len(list_of_datasets))
    
    mat = csr_matrix((elements, (rows, class_labels))).toarray()
    cells_per_class = np.sum(mat, axis=0)
    normalized = mat / cells_per_class
    dataset_fraction = np.sum(normalized, axis=1)
    
    train_dataset = []
    test_dataset = []
    val_dataset = []
    
    #check to make sure we have more than one occurance of a dataset (otherwise it will throw an error)
    if np.sum(pd.Series(class_labels).value_counts() > 1) == 0:
        for dataset, label, fraction in zip(list_of_datasets, class_labels, dataset_fraction):
            print(dataset, label, 1)
            train_size = floor(train_per_class)
            test_size = floor(test_per_class)
            val_size = floor(val_per_class)
            
            residual_size = len(dataset) - train_size - test_size - val_size
            
            if(residual_size < 0):
                raise ValueError(f"Dataset with length {len(dataset)} is to small to be split into test set of size {test_size} and train set of size {train_size} and validation set of size {val_size}. Use a smaller test and trainset.")
            
            if seed is not None:
                print(f"Using seeded generator with seed {seed} to split dataset")
                gen = torch.Generator()
                gen.manual_seed(seed)
                train, test, val, _ = torch.utils.data.random_split(dataset, [train_size, test_size, val_size, residual_size], generator=gen)
            else:
                train, test, val, _ = torch.utils.data.random_split(dataset, [train_size, test_size, val_size, residual_size])
            train_dataset.append(train)
            test_dataset.append(test)
            val_dataset.append(val)
    else: 
        for dataset, label, fraction in zip(list_of_datasets, class_labels, dataset_fraction):
            # train_size = floor(train_per_class * fraction)
            # test_size = floor(test_per_class * fraction)
            # val_size = floor(val_per_class * fraction)
            train_size = int(np.round(train_per_class * fraction))
            test_size = int(np.round(test_per_class * fraction))
            val_size = int(np.round(val_per_class * fraction))
            
            residual_size = len(dataset) - train_size - test_size - val_size
            
            if residual_size < 0:
                raise ValueError(
                    f"Dataset with length {len(dataset)} is too small to be split into test set of size {test_size}, "
                    f"train set of size {train_size}, and validation set of size {val_size}. "
                    f"Use a smaller test and trainset."
                )
            if seed is not None:
                print(f"Using seeded generator with seed {seed} to split dataset")
                gen = torch.Generator()
                gen.manual_seed(seed)
                train, test, val, _ = torch.utils.data.random_split(dataset, [train_size, test_size, val_size, residual_size], generator=gen)
            else:
                train, test, val, _ = torch.utils.data.random_split(dataset, [train_size, test_size, val_size, residual_size])

            train_dataset.append(train)
            test_dataset.append(test)
            val_dataset.append(val)
    
    train_dataset = torch.utils.data.ConcatDataset(train_dataset)
    test_dataset = torch.utils.data.ConcatDataset(test_dataset)
    val_dataset = torch.utils.data.ConcatDataset(val_dataset)
    
    return train_dataset, val_dataset, test_dataset

# def to_one_hot(y, n_dims=None):
#     """ Take integer y (tensor) with n dims and convert it to 1-hot representation with n+1 dims. """
#     y_tensor = y.type(torch.LongTensor).view(-1, 1)
#     n_dims = n_dims if n_dims is not None else int(torch.max(y_tensor)) + 1
#     y_one_hot = torch.zeros(y_tensor.size()[0], n_dims).scatter_(1, y_tensor, 1)
#     y_one_hot = y_one_hot.view(*y.shape, -1)
#     return y_one_hot