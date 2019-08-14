from mxnet import gluon, init, autograd
from mxnet.gluon import nn
from mxnet.gluon.data.vision import datasets, transforms
import time
import mxnet as mx
from tornasole import modes
import numpy as np

def acc(output, label):
    return (output.argmax(axis=1) ==
            label.astype('float32')).mean().asscalar()


def run_mnist_gluon_model(hook=None, hybridize=False, set_modes=False,
                          num_steps_train=None, num_steps_eval=None, make_input_zero=False, normalize_mean=0.13,
                          normalize_std=0.31):
    batch_size = 1024
    if make_input_zero:
        mnist_train = datasets.FashionMNIST(train=True,
                                            transform=lambda data, label: (data.astype(np.float32) * 0, label))
        normalize_mean=0.0
    else:
        mnist_train = datasets.FashionMNIST(train=True)

    X, y = mnist_train[0]
    ('X shape: ', X.shape, 'X dtype', X.dtype, 'y:', y)

    text_labels = ['t-shirt', 'trouser', 'pullover', 'dress', 'coat',
                   'sandal', 'shirt', 'sneaker', 'bag', 'ankle boot']
    X, y = mnist_train[0:10]
    transformer = transforms.Compose([
                transforms.ToTensor(),
                transforms.Normalize(normalize_mean, 0.31)])

    mnist_train = mnist_train.transform_first(transformer)
    mnist_valid = gluon.data.vision.FashionMNIST(train=False)

    train_data = gluon.data.DataLoader(
        mnist_train, batch_size=batch_size, shuffle=True, num_workers=4)
    valid_data = gluon.data.DataLoader(
        mnist_valid.transform_first(transformer),
        batch_size=batch_size, num_workers=4)

    # Create Model in Gluon
    net = nn.HybridSequential()
    net.add(nn.Conv2D(channels=6, kernel_size=5, activation='relu'),
            nn.MaxPool2D(pool_size=2, strides=2),
            nn.Conv2D(channels=16, kernel_size=3, activation='relu'),
            nn.MaxPool2D(pool_size=2, strides=2),
            nn.Flatten(),
            nn.Dense(120, activation="relu"),
            nn.Dense(84, activation="relu"),
            nn.Dense(10))
    net.initialize(init=init.Xavier(),ctx=mx.cpu())
    if hybridize:
        net.hybridize(())

    if hook is not None:
    # Register the forward Hook
        hook.register_hook(net)

    softmax_cross_entropy = gluon.loss.SoftmaxCrossEntropyLoss()
    trainer = gluon.Trainer(net.collect_params(), 'sgd', {'learning_rate': 0.1})

    # Start the training.
    for epoch in range(2):
        train_loss, train_acc, valid_acc = 0., 0., 0.
        tic = time.time()
        if set_modes:
            hook.set_mode(modes.TRAIN)

        i = 0
        for data, label in train_data:
            data = data.as_in_context(mx.cpu(0))
        # forward + backward
            with autograd.record():
                output = net(data)
                loss = softmax_cross_entropy(output, label)
            loss.backward()
        # update parameters
            trainer.step(batch_size)
        # calculate training metrics
            train_loss += loss.mean().asscalar()
            train_acc += acc(output, label)
            i += 1
            if num_steps_train is not None and i > num_steps_train:
                break
        # calculate validation accuracy
        if set_modes:
            hook.set_mode(modes.EVAL)
        i = 0
        for data, label in valid_data:
            data = data.as_in_context(mx.cpu(0))
            valid_acc += acc(net(data), label)
            i += 1
            if num_steps_eval is not None and i > num_steps_eval:
                break
        print("Epoch %d: loss %.3f, train acc %.3f, test acc %.3f, in %.1f sec" % (
                epoch, train_loss/len(train_data), train_acc/len(train_data),
                valid_acc/len(valid_data), time.time()-tic))
