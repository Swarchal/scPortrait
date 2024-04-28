from datetime import datetime
import os
import warnings
import shutil
import tempfile
import sys

class Logable(object):
    """
    Object which can create log entries.

    Args:
        debug (bool, default ``False``): When set to ``True`` log entries will be printed to the console.

    Attributes:
        directory (str): A directory must be set in every descendant before log can be called.
        DEFAULT_LOG_NAME (str, default ``processing.log``): Default log file name.
        DEFAULT_FORMAT (str): Date and time format used for logging. See `datetime.strftime <https://docs.python.org/3/library/datetime.html#datetime.date.strftime>`_.
    """

    DEFAULT_LOG_NAME = "processing.log"
    DEFAULT_FORMAT = "%d/%m/%Y %H:%M:%S"

    def __init__(self, debug=False):
        self.debug = debug

    def log(self, message):
        """log a message

        Args:
            message (str, list(str), dict(str)): Strings are s
        """

        if not hasattr(self, "directory"):
            raise ValueError(
                "Please define a valid self.directory in every descended of the Logable class"
            )

        if isinstance(message, str):
            lines = message.split("\n")

        if isinstance(message, list):
            lines = message

        if isinstance(message, dict):
            lines = []
            for key, value in message.items():
                lines.append(f"{key}: {value}")

        else:
            try:
                lines = [str(message)]
            except:
                self.log("unknown type during loging")
                return

        for line in lines:
            log_path = os.path.join(self.directory, self.DEFAULT_LOG_NAME)

            #check that log path exists if not create
            if not os.path.isdir(self.directory):
                os.makedirs(self.directory)
                
            with open(log_path, "a") as myfile:
                myfile.write(self.get_timestamp() + line + " \n")

            if self.debug:
                print(self.get_timestamp() + line)

    def get_timestamp(self):
        """
        Get the current timestamp in the DEFAULT_FORMAT.

        Returns:
            str: Formatted timestamp.
        """

        # datetime object containing current date and time
        now = datetime.now()

        dt_string = now.strftime(self.DEFAULT_FORMAT)
        return "[" + dt_string + "] "


class ProcessingStep(Logable):
    """Processing step. Can load a configuration file and create a subdirectory under the project class for the processing step.

    Attributes:
        config (dict): Config file which is passed by the Project class when called. Is loaded from the project based on the name of the class.
        directory (str): Directory which should be used by the processing step. The directory will be newly created if it does not exist yet. When used with the :class:`vipercore.pipeline.project.Project` class, a subdirectory of the project directory is passed.
        intermediate_output (bool, default ``False``): When set to True intermediate outputs will be saved where applicable.
        debug (bool, default ``False``): When set to True debug outputs will be printed where applicable.
        overwrite (bool, default ``False``): When set to True, the processing step directory will be completely deleted and newly created when called.
    """
    def __init__(
            self, config, directory, project_location, debug=False, intermediate_output=False, overwrite=True
    ):
        super().__init__()

        self.debug = debug
        self.overwrite = overwrite
        self.intermediate_output = intermediate_output
        self.directory = directory
        self.project_location = project_location
        self.config = config
        self.create_temp_dir()

    def __call__(
            self, *args, debug=None, intermediate_output=None, overwrite=None, **kwargs
    ):
        """
        Call the processing step.

        Args:
            intermediate_output (bool, optional, default ``None``): Allows overriding the value set on initiation. When set to True intermediate outputs will be saved where applicable.
            debug (bool, optional, default ``None``): Allows overriding the value set on initiation. When set to True debug outputs will be printed where applicable.
            overwrite (bool, optional, default ``None``): Allows overriding the value set on initiation. When set to True, the processing step directory will be completely deleted and newly created when called.
        """

        # set flags if provided
        self.debug = debug if debug is not None else self.debug
        self.overwrite = overwrite if overwrite is not None else self.overwrite
        self.intermediate_output = (
            intermediate_output
            if intermediate_output is not None
            else self.intermediate_output
        )

        # remove directory for processing step if overwrite is enabled
        if self.overwrite:
            if os.path.isdir(self.directory):
                shutil.rmtree(self.directory)

        # create directory for processing step
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory)

        print(f"Temp directory {self._tmp_dir} for method {self.__class__.__name__}")
        if not os.path.isdir(self._tmp_dir.name):
            sys.exit("Temporary directory not found, exiting...")

        process = getattr(self, "process", None)
        if callable(process):
            x = self.process(*args, **kwargs)
            return x
        else:
            warnings.warn("no process method defined")

        #after call is completed empty out temporary directories
        self.clear_temp_dir()
    
    def __call_empty__(
            self, *args, debug=None, intermediate_output=None, overwrite=None, **kwargs
    ):
        """Call the empty processing step.

        Args:
            intermediate_output (bool, optional, default ``None``): Allows overriding the value set on initiation. When set to True intermediate outputs will be saved where applicable.
            debug (bool, optional, default ``None``): Allows overriding the value set on initiation. When set to True debug outputs will be printed where applicable.
            overwrite (bool, optional, default ``None``): Allows overriding the value set on initiation. When set to True, the processing step directory will be completely deleted and newly created when called.
        """
        # set flags if provided
        self.debug = debug if debug is not None else self.debug
        self.overwrite = overwrite if overwrite is not None else self.overwrite
        self.intermediate_output = (
            intermediate_output
            if intermediate_output is not None
            else self.intermediate_output
        )

        # remove directory for processing step if overwrite is enabled
        if self.overwrite:
            if os.path.isdir(self.directory):
                shutil.rmtree(self.directory)

        # create directory for processing step
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory)

        process = getattr(self, "return_empty_mask", None)
        if callable(process):
            x = self.return_empty_mask(*args, **kwargs)
            return x
        else:
            warnings.warn("no return_empty_mask method defined")

        #also clear empty temp directory here
        self.clear_temp_dir()

    def register_parameter(self, key, value):
        """
        Registers a new parameter by updating the configuration dictionary if the key didn't exist.

        Args:
            key (str): Name of the parameter.
            value: Value of the parameter.
        """

        if isinstance(key, str):
            config_handle = self.config

        elif isinstance(key, list):
            raise NotImplementedError(
                "registration of parameters is not yet supported for nested parameters"
            )

        else:
            raise TypeError("Key must be of string or a list of strings")

        if not key in config_handle:
            self.log(
                f"No configuration for {key} found, parameter will be set to {value}"
            )
            config_handle[key] = value

    def get_directory(self):
        """
        Get the directory for this processing step.

        Returns:
            str: Directory path.
        """
        return self.directory

    def create_temp_dir(self):
        """
        Create a temporary directory in the cache directory specified in the config for saving all intermediate results.
        If "cache" not specified in the config for the method no directory will be created.
        """
        global TEMP_DIR_NAME #this is the global variable name used within alphabase.io.tempmmap which is required to intialize a memory mapped temp array using this code

        if "cache" in self.config.keys():
            self._tmp_dir_path = os.path.join(self.config["cache"], f"{self.__class__.__name__}_")
            self._tmp_dir = tempfile.TemporaryDirectory(prefix = self._tmp_dir_path)
            self.log(f"Initialized temporary directory for saving all temp results at {self._tmp_dir_path}")
            print(f"Initialized temporary directory for saving all temp results at {self._tmp_dir_path} for {self.__class__.__name__}")
            TEMP_DIR_NAME = self._tmp_dir.name
        else:
            self.log("No cache directory specified in config. Skipping temporary directory creation")
    
    def clear_temp_dir(self):
        """Delete created temporary directory."""
        
        if "_tmp_dir" in self.__dict__.keys():
            shutil.rmtree(self._tmp_dir)
            self.log(f"Cleaned up temporary directory at {self._tmp_dir}")

            del self._tmp_dir, self._tmp_dir_path
        else:
            self.log(f"Temporary directory not found, skipping cleanup")