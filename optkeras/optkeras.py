from keras.callbacks import Callback, CSVLogger, ModelCheckpoint

import os, glob
import numpy as np
from datetime import datetime

import optuna


class OptKeras(Callback):
    """ The main class of OptKeras which can act as a callback for Keras.
    """
    def __init__(self, 
                 monitor = 'val_error',
                 enable_pruning = False,
                 enable_keras_log = True,
                 keras_log_file_suffix = '_Keras.csv',
                 enable_optuna_log = True,
                 optuna_log_file_suffix = '_Optuna.csv',
                 models_to_keep = 1,
                 model_file_prefix = 'model_', 
                 model_file_suffix = '.hdf5',
                 directory_path = '',
                 verbose = 1,
                 **kwargs):
        """ Wrapper of optuna.create_study
        Args:
            monitor: The metric to optimize by Optuna. 'val_error' in default or 'val_loss'.
            enable_pruning: Enable pruning by Optuna.
                See https://optuna.readthedocs.io/en/latest/tutorial/pruning.html
            enable_keras_log: Enable logging by Keras CSVLogger callback.
                See https://www.tensorflow.org/api_docs/python/tf/keras/callbacks/CSVLogger
            keras_log_file_suffix: Suffix of the file if enable_keras_log is True.
                '_Keras.csv' in default.
            enable_optuna_log: Enable generating a log file by Optuna study.trials_dataframe().
                See https://optuna.readthedocs.io/en/latest/reference/study.html
            optuna_log_file_suffix: Suffix of the file if enable_optuna_log is True.
            models_to_keep: The number of models to keep.
                either 1 in default , 0, or -1 (save all models).
            model_file_prefix: Prefix of the model file path if models_to_keep is not 0.
                'model_' in default.
            model_file_suffix: Suffix of the model file path if models_to_keep is not 0.
                '.hdf5' in default.
            directory_path: The path of the directory for the files.
                '' (Current working directory) in default.
            verbose: How much to print messages onto the screen.
                0 (no messages), 1 in default, 2 (troubleshooting)
            **kwargs: parameters for optuna.study.Study():
                study_name, storage, sampler=None, pruner=None, direction='minimize'
                See https://optuna.readthedocs.io/en/latest/reference/study.html
        """
        self.study = optuna.create_study(**kwargs)
        self.study_name = self.study.study_name
        self.keras_log_file_path = directory_path + self.study_name + keras_log_file_suffix
        self.optuna_log_file_path = directory_path + self.study_name + optuna_log_file_suffix
        self.monitor = monitor
        self.mode_max = (monitor in ['acc', 'val_acc']) # The larger acc or val_acc, the better
        self.mode = 'max' if self.mode_max else 'min'
        self.default_value = -np.Inf if self.mode_max else np.Inf
        self.latest_logs = {}
        self.latest_value = self.default_value
        self.trial_best_logs = {}
        self.trial_best_value = self.default_value
        self.enable_pruning = enable_pruning
        self.enable_keras_log = enable_keras_log
        self.enable_optuna_log = enable_optuna_log
        self.models_to_keep = models_to_keep
        self.model_file_prefix = directory_path + self.study_name + '_' + model_file_prefix
        self.model_file_suffix = model_file_suffix
        self.verbose = verbose
        self.keras_verbose = max(self.verbose - 1 , 0) # decrement
        if self.verbose >= 1:
            print('[{}]'.format(self.get_datetime()),
            'Ready for optimization. (message printed as verbose is set to 1+)')

    def optimize(self, *args, **kwargs):
        """
        Args:
            *args: parameters for study.optimize optimize(): func
            **kwargs: parameters for study.optimize optimize():
                n_trials=None, timeout=None, n_jobs=1, catch=(<class 'Exception'>, )
                See https://optuna.readthedocs.io/en/latest/reference/study.html

        Returns: None
        """
        self.study.optimize(*args, **kwargs)
        self.post_process()

    def get_model_file_path(self, trial_id = None):
        """
        Args:
            trial_id: Trial Id of Optuna study

        Returns: model file path string
        """
        return ''.join([self.model_file_prefix, 
                        '*' if trial_id is None else '{:06d}'.format(trial_id),
                        self.model_file_suffix ])

    def clean_up_model_files(self):
        """ Delete model files not needed
        Returns: None
        """
        # currently version supports only models_to_keep <= 1
        if self.models_to_keep in [1]:
            self.best_model_file_path = \
                self.get_model_file_path(self.best_trial.trial_id)
            self.model_file_list = \
                glob.glob(self.get_model_file_path())
            for model_file in self.model_file_list:
                if model_file not in [self.best_model_file_path]:
                    os.remove(model_file)

    def get_datetime(self):
        """
        Returns: date time string in '%Y-%m-%d %H:%M:%S.%f' format
        """
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

    def callbacks(self, trial):
        """ Callbacks to be passed to Keras
        Args:
            trial: Optuna trial
        """
        self.synch_with_optuna()
        callbacks = []
        self.trial = trial
        self.model_file_path = self.get_model_file_path(trial.trial_id)     
        callbacks.append(self)
        if self.enable_keras_log:
            csv_logger = CSVLogger(self.keras_log_file_path, append = True)
            callbacks.append(csv_logger)
        if self.models_to_keep != 0:
            check_point = ModelCheckpoint(filepath = self.model_file_path, 
                monitor = self.monitor, mode = self.mode, save_best_only = True, 
                save_weights_only = False, period = 1, 
                verbose = self.keras_verbose)
            callbacks.append(check_point)
            self.clean_up_model_files()                
        if self.enable_pruning:
            pruning = \
                optuna.integration.KerasPruningCallback(trial, self.monitor)
            callbacks.append(pruning)       
        return callbacks

    def save_logs_as_optuna_attributes(self):
        """ Save the logs in Optuna's database as user attributes.
        Returns: None
        """
        for key, val in self.trial_best_logs.items():
            self.trial.set_user_attr(key, val)

    def generate_optuna_log_file(self):
        """ Generate log file from Optuna
        Returns: None
        """
        try:
            df = self.study.trials_dataframe()
            df.columns = ['_'.join(str_list(col)).rstrip('_').
                          replace('user_attrs_','').replace('params_','') \
                          for col in df.columns.values]
            self.optuna_log = df
            self.optuna_log.to_csv(self.optuna_log_file_path, index=False)
        except:
            print('[{}] '.format(self.get_datetime()), 
            'Failed to generate Optuna log file. Continue to run.')

    def synch_with_optuna(self):
        """ Exchange information with Optuna
        Returns: None
        """
        # Generate the Optuna CSV log file
        if self.enable_optuna_log: self.generate_optuna_log_file()
        # best_trial
        try:
            self.best_trial = self.study.best_trial
        except:
            self.best_trial = optuna.structs.FrozenTrial(
                None, None, None, None, None, None, None, None, None, None)
        # latest_trial
        self.latest_trial = optuna.structs.FrozenTrial(
                None, None, None, None, None, None, None, None, None, None)
        if len(self.study.trials) >= 1:
            if self.study.trials[-1].state == optuna.structs.TrialState.RUNNING:
                if len(self.study.trials) >= 2:
                    self.latest_trial = self.study.trials[-2]
            else: 
                self.latest_trial = self.study.trials[-1]         
        if self.verbose >= 1: self.print_results()

    def print_results(self):
        """ Print summary of results
        Returns: None
        """
        if self.verbose >= 1 and len(self.study.trials) > 0:
            # if any trial with a valid value is found, show the result
            print(
                '[{}] '.format(self.get_datetime()) + \
                'Latest trial id: {}'.format(self.latest_trial.trial_id) + \
                ', value: {}'.format(self.latest_trial.value) + \
                ' ({}) '.format(self.latest_trial.state) + \
                '| Best trial id: {}'.format(self.best_trial.trial_id) + \
                ', value: {}'.format(self.best_trial.value) + \
                ', parameters: {}'.format(self.best_trial.params) )

    def post_process(self):
        """ Process after optimization
        Returns: None
        """
        self.synch_with_optuna()
        self.clean_up_model_files()

    def on_epoch_begin(self, epoch, logs={}):
        """ Called at the beginning of every epoch by Keras
        Args:
            epoch:
            logs:
        """
        self.datetime_epoch_begin = self.get_datetime()
        ## Reset trial best logs
        self.trial_best_logs = {}

    def on_epoch_end(self, epoch, logs={}):
        """ called at the end of every epoch by Keras
        Args:
            epoch:
            logs:
        """
        self.datetime_epoch_end = self.get_datetime()
        # Add error and val_error to logs for use as an objective to minimize
        logs['error'] = 1 - logs.get('acc', 0)
        logs['val_error'] = 1 - logs.get('val_acc', 0)
        logs['_Datetime_epoch_begin'] = self.datetime_epoch_begin
        logs['_Datetime_epoch_end'] = self.datetime_epoch_end
        logs['_Trial_id'] = self.trial.trial_id
        logs['_Monitor'] = self.monitor
        # Update the best logs

        def update_flag(latest, best, mode_max = False):
            return (mode_max and (latest > best)) \
                or ((not mode_max) and (latest < best))

        def update_best_logs(latest_logs = {}, best_logs = {}, 
                             monitor = 'val_error', 
                             mode_max = False, default_value=np.Inf):
            latest = latest_logs.get(monitor, default_value)
            best = best_logs.get(monitor, default_value)
            if update_flag(latest, best, mode_max = mode_max):
                best_logs.update(latest_logs)
        self.latest_logs = logs.copy()
        # Update trial best
        update_best_logs(self.latest_logs, self.trial_best_logs,  
                         self.monitor, self.mode_max, self.default_value)
        self.trial_best_value = \
            self.trial_best_logs.get(self.monitor, self.default_value)        
        # Recommended: save the logs from the best epoch as attributes
        # (logs include timestamp, monitor, val_acc, val_error, val_loss)
        self.save_logs_as_optuna_attributes()


def str_list(input_list):
    """ Convert all the elements in a list to str
    Args:
        input_list: list of any elements
    Returns: list of string elements
    """
    return ['{}'.format(e) for e in input_list] # convert all elements to string
