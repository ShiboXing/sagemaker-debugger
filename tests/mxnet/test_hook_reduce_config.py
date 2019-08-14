from .mnist_gluon_model import run_mnist_gluon_model
from tornasole.mxnet.hook import TornasoleHook as t_hook
from tornasole.mxnet import SaveConfig, Collection, ReductionConfig, reset_collections
import tornasole.mxnet as tm
from tornasole.trials import create_trial
import shutil

from datetime import datetime

def test_save_config():
    reset_collections()
    global_reduce_config = ReductionConfig(reductions=["max", "mean"])
    global_save_config = SaveConfig(save_steps=[0,1,2,3])

    tm.get_collection("ReluActivation").include(["relu*"])
    tm.get_collection("ReluActivation").set_save_config(SaveConfig(save_steps=[4,5,6]))
    tm.get_collection("ReluActivation").set_reduction_config(ReductionConfig(reductions=["min"], abs_reductions=["max"]))

    tm.get_collection("flatten").include(["flatten*"])
    tm.get_collection("flatten").set_save_config(SaveConfig(save_steps=[4,5,6]))
    tm.get_collection("flatten").set_reduction_config(ReductionConfig(norms=["l1"], abs_norms=["l2"]))

    run_id = 'trial_' + datetime.now().strftime('%Y%m%d-%H%M%S%f')
    out_dir = './newlogsRunTest/' + run_id
    hook = t_hook(out_dir=out_dir, save_config=global_save_config, include_collections=['weights', 'bias','gradients',
                                                                               'default', 'ReluActivation', 'flatten'],
                reduction_config=global_reduce_config)
    run_mnist_gluon_model(hook=hook, num_steps_train=10, num_steps_eval=10)


    #Testing
    tr = create_trial(out_dir)
    assert tr
    assert len(tr.available_steps())==7

    tname = tr.tensors_matching_regex('conv._weight')[0]
    print(tr.tensors())
    # Global reduction with max and mean
    weight_tensor = tr.tensor(tname)
    max_val = weight_tensor.reduction_value(step_num=1, abs=False, reduction_name='max')
    assert max_val != None
    mean_val = weight_tensor.reduction_value(step_num=1, abs=False, reduction_name='mean')
    assert mean_val != None

    # custom reduction at step 4 with reduction = 'min and abs reduction = 'max'
    tname = tr.tensors_matching_regex('conv._relu_input_0')[0]
    relu_input = tr.tensor(tname)
    min_val = relu_input.reduction_value(step_num=4, abs=False, reduction_name='min')
    assert min_val != None
    abs_max_val = relu_input.reduction_value(step_num=4, abs=True, reduction_name='max')
    assert abs_max_val != None

    # Custom reduction with normalization
    tname = tr.tensors_matching_regex('flatten._input_0')[0]
    flatten_input = tr.tensor(tname)
    l1_norm = flatten_input.reduction_value(step_num=4, abs=False, reduction_name='l1')
    assert l1_norm != None
    l2_norm = flatten_input.reduction_value(step_num=4, abs=True, reduction_name='l2')
    assert l2_norm != None

    shutil.rmtree(out_dir)