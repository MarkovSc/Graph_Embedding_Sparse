# -*- coding:utf-8 -*-

"""



Author:

    origin author from Weichen Shen,wcshen1994@163.com
    use the sparse matrix to implement from yongsaima yongsaima@163.com


Reference:

    [1] Wang D, Cui P, Zhu W. Structural deep network embedding[C]//Proceedings of the 22nd ACM SIGKDD international conference on Knowledge discovery and data mining. ACM, 2016: 1225-1234.(https://www.kdd.org/kdd2016/papers/files/rfp0191-wangAemb.pdf)



"""
import time
import numpy as np
import tensorflow as tf
from tensorflow.python.keras import backend as K
from tensorflow.python.keras.callbacks import History
from tensorflow.python.keras.layers import Dense, Input
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.regularizers import l1_l2
from scipy.sparse import *
from networkx import nx
from tqdm import tqdm

def l_2nd(beta):
    def loss_2nd(y_true, y_pred):
        b_ = np.ones_like(y_true)
        b_[y_true != 0] = beta
        x = K.square((y_true - y_pred) * b_)
        t = K.sum(x, axis=-1, )
        return K.mean(t)

    return loss_2nd


def l_1st(alpha):
    def loss_1st(y_true, y_pred):
        L = y_true
        Y = y_pred
        batch_size = tf.to_float(K.shape(L)[0])
        return alpha * 2 * tf.linalg.trace(tf.matmul(tf.matmul(Y, L, transpose_a=True), Y)) / batch_size
    return loss_1st


def create_model(node_size, hidden_size=[256, 128], l1=1e-5, l2=1e-4):
    A = Input(shape=(node_size,))
    L = Input(shape=(None,))
    fc = A
    for i in range(len(hidden_size)):
        if i == len(hidden_size) - 1:
            fc = Dense(hidden_size[i], activation='relu',
                       kernel_regularizer=l1_l2(l1, l2), name='1st')(fc)
        else:
            fc = Dense(hidden_size[i], activation='relu',
                       kernel_regularizer=l1_l2(l1, l2))(fc)
    Y = fc
    for i in reversed(range(len(hidden_size) - 1)):
        fc = Dense(hidden_size[i], activation='relu',
                   kernel_regularizer=l1_l2(l1, l2))(fc)

    A_ = Dense(node_size, 'relu', name='2nd')(fc)
    model = Model(inputs=[A, L], outputs=[A_, Y])
    emb = Model(inputs=A, outputs=Y)
    return model, emb


class SDNE(object):
    def __init__(self, graph, hidden_size=[32, 16], alpha=1e-6, beta=5., nu1=1e-5, nu2=1e-4, ):

        self.graph = graph
        self.idx2node = list(self.graph.nodes())
        self.node2idx = dict([(self.idx2node[index], index) for index in range(len(self.idx2node))])
        self.node_size = self.graph.number_of_nodes()
        self.hidden_size = hidden_size
        self.alpha = alpha
        self.beta = beta
        self.nu1 = nu1
        self.nu2 = nu2

        self.A, self.L = self._create_A_L(
            self.graph, self.node2idx)  # Adj Matrix,L Matrix
        self.reset_model()
        self.inputs = [self.A, self.L]
        self._embeddings = {}

    def reset_model(self, opt='adam'):

        self.model, self.emb_model = create_model(self.node_size, hidden_size=self.hidden_size, l1=self.nu1,
                                                  l2=self.nu2)
        self.model.compile(opt, [l_2nd(self.beta), l_1st(self.alpha)])

    def train(self, batch_size=1024, epochs=1, initial_epoch=0, verbose=1):
        if batch_size >= self.node_size:
            if batch_size > self.node_size:
                print('batch_size({0}) > node_size({1}),set batch_size = {1}'.format(
                    batch_size, self.node_size))
                batch_size = self.node_size
            return self.model.fit([self.A.toarray(), self.L.toarray()], [self.A.toarray(), self.L.toarray()], batch_size=batch_size, epochs=epochs, initial_epoch=initial_epoch, verbose=verbose, shuffle=False,)
        else:
            print("use the batch model to run")
            steps_per_epoch = (self.node_size - 1) // batch_size + 1
            hist = History()
            hist.on_train_begin()
            logs = {}
            for epoch in range(initial_epoch, epochs):
                start_time = time.time()
                losses = np.zeros(3)
                for i in tqdm(range(steps_per_epoch)):
                    index = np.arange(
                        i * batch_size, min((i + 1) * batch_size, self.node_size))
                    A_train = self.A[index, :].toarray()
                    L_mat_train = self.L[index][:, index].toarray()
                    inp = [A_train, L_mat_train]
                    batch_losses = self.model.train_on_batch(inp, inp)
                    losses += batch_losses
                losses = losses/steps_per_epoch

                logs['loss'] = losses[0]
                logs['2nd_loss'] = losses[1]
                logs['1st_loss'] = losses[2]
                epoch_time = int(time.time() - start_time)
                hist.on_epoch_end(epoch, logs)
                if verbose > 0:
                    print('Epoch {0}/{1}'.format(epoch + 1, epochs))
                    print('{0}s - loss: {1: .4f} - 2nd_loss: {2: .4f} - 1st_loss: {3: .4f}'.format(
                        epoch_time, losses[0], losses[1], losses[2]))
            return hist

    def evaluate(self, ):
        return self.model.evaluate(x=self.inputs, y=self.inputs, batch_size=self.node_size)

    def get_embeddings(self, batch_size = 1024):
        self._embeddings = {}
        look_back = self.idx2node
        if batch_size >= self.node_size:
            embeddings = self.emb_model.predict(self.A.toarray(), batch_size=self.node_size)
            for i, embedding in enumerate(embeddings):
                self._embeddings[look_back[i]] = embedding
        else:
            print("use the batch model to run")
            steps_per_epoch = (self.node_size - 1) // batch_size + 1
            for i in tqdm(range(steps_per_epoch)):
                index = np.arange(
                        i * batch_size, min((i + 1) * batch_size, self.node_size))
                A_train = self.A[index, :].toarray()
                embeddings = self.emb_model.predict(A_train, batch_size=self.node_size)

                for j, embedding in enumerate(embeddings):
                    self._embeddings[look_back[j + i * batch_size]] = embedding

        return self._embeddings

    def _create_A_L(self, graph, node2idx):
        from pympler.asizeof import asizeof
        from scipy.sparse import csgraph
        A = nx.to_scipy_sparse_matrix(graph)
        rows, cols = A.nonzero()
        A_ = A.copy()
        A_[cols, rows] = A[rows, cols]
        L = csgraph.laplacian(A_, normed=False).tocsr()
        return A, L
