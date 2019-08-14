import shutil
import os
from multiprocessing import *
from tornasole.core.utils import get_logger
import yaml
import time
import asyncio
import aioboto3
from tornasole.core.access_layer.s3handler import ReadObjectRequest, S3Handler, ListRequest
import logging.handlers
import time

logger = get_logger()

# store path to config file and test mode for testing rule scrip with training script
class TestRules():
    def __init__(self, mode, path_to_config):
        """
        :param mode: mode could be either 'tensorflow' or 'mxnet'
        :param path_to_config: the path of config file which contains path to training and test scripts and corresponding arg strings
        """
        self.mode = mode
        self.path_to_config = path_to_config

    # mode is either 'serial' or 'parallel'
    def configure_log(self, path_train_script, path_test_script, trial_dir, mode):
        location = 's3' if trial_dir.startswith('s3') else 'local'
        training_script_name = path_train_script.split('/')[-1].strip('.py')
        test_script_name = path_test_script.split('/')[-1].strip('.py')
        # add independent logger for serial job
        fh = logging.FileHandler(os.path.join(os.getcwd(),
                                 format(f"{training_script_name}_{test_script_name}_{location}_{mode}")))
        logger = logging.getLogger('tornasole')
        logging.basicConfig(level=logging.INFO)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)  # enable to write log into log file
        return logger

    # delete the s3 folders using aioboto3
    async def del_folder(self, bucket, keys):
        loop = asyncio.get_event_loop()
        client = aioboto3.client('s3', loop=loop)
        await asyncio.gather(*[client.delete_object(Bucket=bucket, Key=key) for key in keys])
        await client.close()

    # delete outputs generated by all training processes
    # local_trials: trial dirs on local, e.g., './output/trial'
    def delete_local_trials(self, local_trials):
        for trial in local_trials:
            trial_root = trial.split('/')[1]
            if os.path.exists(trial):
                shutil.rmtree(trial_root)

    # delete the s3 folders using aioboto3
    # s3_trials: trial dirs on s3, e.g., 's3://bucket_name/trial'
    def delete_s3_trials(self, s3_trials):
        s3_handler = S3Handler()
        list_req = []
        bucket_name = ''
        for trial in s3_trials:
            bucket_name = trial.split('/')[2]
            trial_name = trial.split('/')[3]
            list_req.append(ListRequest(Bucket=bucket_name, Prefix=trial_name))
        keys = s3_handler.list_prefixes(list_req)
        # flat nested list
        keys = [item for sublist in keys for item in sublist]
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.del_folder(bucket_name, keys))
        loop.run_until_complete(task)

    # run a 'job' in serial. a 'job' is a training/test scripts combination
    def run_job_in_serial(self, path_train_script, train_script_args, path_test_script, test_script_args, trial_dir):
        self.run_train(path_train_script, train_script_args, path_test_script, trial_dir)
        logger.info(f'Finished Serial training job: {path_train_script}')
        self.run_test(path_test_script, test_script_args, path_train_script, trial_dir)
        logger.info(f'Finished Serial testing job: {path_test_script}')

    # run a training script only
    def run_train(self, path_train_script, train_script_args, path_test_script, trial_dir):
        logger.info("running training script {}".format(path_train_script))
        if path_train_script.split('/')[-1] == 'mnist_gluon_vg_demo.py' \
                or path_train_script.split('/')[-1] == 'mnist_gluon_basic_hook_demo.py':
            commands = format(f"python {path_train_script} --output-uri {trial_dir} {train_script_args}")
        else:
            commands = format(f"TORNASOLE_LOG_LEVEL=info python {path_train_script} --tornasole_path {trial_dir} {train_script_args}")
        os.system(commands) # os.system(commands) enables the usage of cmd executable prompts
        logger.info(f'Finished Parallel training job: {path_train_script}')

    # run a test script only
    def run_test(self, path_test_script, test_script_args, path_train_script, trial_dir):
        logger.info("running test script {}".format(path_test_script))
        commands = format(f"TORNASOLE_LOG_LEVEL=debug python {path_test_script} --tornasole_path {trial_dir} {test_script_args}")
        os.system(commands) # os.system(commands) enables the usage of cmd executable prompts
        logger.info(f'Finished Parallel testing job: {path_test_script}')

    # run 'job's provided by user. a 'job' is a training/test scripts combination
    # mode: testing mode, either 'auto' or 'manual'
    # jobs: a list of lists, the sublist is called a ‘job’
    # each job is run in serial and parallel on both local and s3
    def run_jobs(self):
        # load config file
        f = open(self.path_to_config)
        jobs = yaml.load(f)
        process_list = []
        local_trials = set()
        s3_trials = set()
        # execute all the 'job's
        for job in jobs:
            # format of a 'job' is:
            # - tensorflow/mxnet
            # - *Enable/*Disable
            # - [<path_train_script>,
            #    <train_script_args>,
            #    <path_test_script>,
            #    <test_script_args>
            #   ]
            if job[0] != 'tensorflow' and job[0] != 'pytorch' and job[0] != 'mxnet' and job[0] != 'values':
                raise Exception('Wrong test case category', job[0])
            # only run the tests which mode is what we want
            if job[0] == self.mode and job[1]:
                # run 'job' in serial on local and s3
                for trial_dir in ['./local_test/trial', 's3://tornasolecodebuildtest/trial']:
                    time_stamp = time.time()
                    name = 'serial_{}_{}_{}_{}'.format(job[2][0], job[2][2], trial_dir+str(time_stamp), 'serial')
                    process_list.append(Process(name=name, target=self.run_job_in_serial, args=(job[2][0], job[2][1], job[2][2], job[2][3], trial_dir+str(time_stamp))))
                    local_trials.add(trial_dir+str(time_stamp)) if trial_dir.startswith('.') else s3_trials.add(trial_dir+str(time_stamp))

                # run 'job' in parallel on local and s3
                for trial_dir in ['./local_test/trial', 's3://tornasolecodebuildtest/trial']:
                    time_stamp = time.time()
                    name = 'train_parallel_{}_{}'.format(job[2][0], trial_dir + str(time_stamp))
                    process_list.append(Process(name=name,
                                                target=self.run_train, args=(job[2][0], job[2][1], job[2][2], trial_dir+str(time_stamp))))
                    name = 'test_parallel_{}_{}'.format(job[2][2], trial_dir + str(time_stamp))
                    process_list.append(Process(name=name, target=self.run_test, args=(job[2][2], job[2][3], job[2][0], trial_dir+str(time_stamp))))
                    local_trials.add(trial_dir+str(time_stamp)) if trial_dir.startswith('.') else s3_trials.add(trial_dir+str(time_stamp))

        # execute all 'job's in parallel
        for process in process_list:
            process.start()
        ended_processes = set()
        while True:
            if len(ended_processes) == len(process_list):
                break
            for process in process_list:
                if process not in ended_processes and not process.is_alive():
                    ended_processes.add(process)
                    logger.info('Process {} ended with exit code {}'.format(process.name, process.exitcode))
                    process.join()
            time.sleep(2)

        # once all jobs are finished, delete the outputs on local and s3
        self.delete_local_trials(local_trials)
        self.delete_s3_trials(s3_trials)

# only for codebuilding test
# enable args string with pytest
def test_test_rules(request):
    mode = request.config.getoption('mode')
    path_to_config = request.config.getoption('path_to_config')
    TestRules(mode=mode, path_to_config=path_to_config).run_jobs()

# test on local machine
# TestRules(mode='tensorflow', path_to_config='./config.yaml').run_jobs()
#






