import tensorflow as tf
import numpy as np
import sys, os,cv2
from sklearn.utils import shuffle
from scipy.misc import imread
from scipy.misc import imresize
import matplotlib.pyplot as plt
from sklearn.preprocessing import OneHotEncoder
from skimage.transform import resize
from imgaug import augmenters as iaa
import imgaug as ia

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
np.random.seed(678)
tf.set_random_seed(678)
ia.seed(678)

def tf_elu(x): return tf.nn.elu(x)
def d_tf_elu(x): return tf.cast(tf.greater_equal(x,0),tf.float32)  + (tf_elu(tf.cast(tf.less(x,0),tf.float32) * x) + 1.0)
def tf_softmax(x): return tf.nn.softmax(x)
def unpickle(file):
    import pickle
    with open(file, 'rb') as fo:
        dict = pickle.load(fo, encoding='bytes')
    return dict

# code from: https://github.com/tensorflow/tensorflow/issues/8246
def tf_repeat(tensor, repeats):
    """
    Args:

    input: A Tensor. 1-D or higher.
    repeats: A list. Number of repeat for each dimension, length must be the same as the number of dimensions in input

    Returns:
    
    A Tensor. Has the same type as input. Has the shape of tensor.shape * repeats
    """
    expanded_tensor = tf.expand_dims(tensor, -1)
    multiples = [1] + repeats
    tiled_tensor = tf.tile(expanded_tensor, multiples = multiples)
    repeated_tesnor = tf.reshape(tiled_tensor, tf.shape(tensor) * repeats)
    return repeated_tesnor

# Def: Plain Convolution Layer
class conv_layer():
    
    def __init__(self,k,inc,out):
        self.w = tf.Variable(tf.random_normal([k,k,inc,out],stddev=0.05))
        self.m,self.v_prev = tf.Variable(tf.zeros_like(self.w)),tf.Variable(tf.zeros_like(self.w))
        self.v_hat_prev = tf.Variable(tf.zeros_like(self.w))

    def feedforward(self,input,droprate=1.0):
        self.input  = input
        self.layer  = tf.nn.dropout(tf.nn.conv2d(input,self.w,strides=[1,1,1,1],padding='SAME'),droprate)
        self.layerA = tf_elu(self.layer)
        return self.layerA 

    def backprop(self,gradient,learning_rate_change,batch_size_dynamic,strides=1,awsgrad=True,reg=False):
        grad_part_1 = gradient 
        grad_part_2 = d_tf_elu(self.layer) 
        grad_part_3 = self.input

        grad_middle = grad_part_1 * grad_part_2

        grad = tf.nn.conv2d_backprop_filter(
            input = grad_part_3,
            filter_sizes = self.w.shape,out_backprop = grad_middle,
            strides=[1,1,1,1],padding='SAME'
        )

        grad_pass = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3.shape[1:]),
            filter= self.w,out_backprop = grad_middle,
            strides=[1,1,1,1],padding='SAME'
        )

        update_w = []

        if awsgrad:
            update_w.append(tf.assign( self.m,self.m*beta1 + (1-beta1) * grad   ))
            v_t = self.v_prev *beta2 + (1-beta2) * grad ** 2 
            def f1(): return v_t
            def f2(): return self.v_hat_prev
            v_max = tf.cond(tf.greater(tf.reduce_sum(v_t), tf.reduce_sum(self.v_hat_prev) ) , true_fn=f1, false_fn=f2)
            adam_middel = learning_rate/(tf.sqrt(v_max) + adam_e)
            if reg: adam_middel = adam_middel - learning_rate_change * decoupled_weight * self.w
            update_w.append(tf.assign(self.w,tf.subtract(self.w,tf.multiply(adam_middel,self.m))))
            update_w.append(tf.assign( self.v_prev,v_t ))
            update_w.append(tf.assign( self.v_hat_prev,v_max ))        
        else:
            update_w.append(tf.assign( self.m,self.m*beta1 + (1-beta1) * (grad)   ))
            update_w.append(tf.assign( self.v_prev,self.v_prev*beta2 + (1-beta2) * (grad ** 2)   ))
            m_hat = self.m / (1-beta1)
            v_hat = self.v_prev / (1-beta2)
            adam_middel = learning_rate_change/(tf.sqrt(v_hat) + adam_e)
            adam_middel = tf.multiply(adam_middel,m_hat)
            if reg: adam_middel = adam_middel - learning_rate_change * decoupled_weight * self.w
            update_w.append(tf.assign(self.w,tf.subtract(self.w,adam_middel  )) )    

        return grad_pass,update_w   

# Def: Convolution Layer first Residual
class conv_res_1_layer():
    def __init__(self,k,inc,out):
        self.w1 = tf.Variable(tf.random_normal([k,k,inc,out],stddev=0.05))
        self.w2 = tf.Variable(tf.random_normal([k,k,out,out],stddev=0.05))
        self.wa = tf.Variable(tf.random_normal([k,k,inc,out],stddev=0.05))
        
        self.m1,self.v_prev1 = tf.Variable(tf.zeros_like(self.w1)),tf.Variable(tf.zeros_like(self.w1))
        self.v_hat_prev1 = tf.Variable(tf.zeros_like(self.w1))
        self.m2,self.v_prev2 = tf.Variable(tf.zeros_like(self.w2)),tf.Variable(tf.zeros_like(self.w2))
        self.v_hat_prev2 = tf.Variable(tf.zeros_like(self.w2))
        self.ma,self.v_preva = tf.Variable(tf.zeros_like(self.wa)),tf.Variable(tf.zeros_like(self.wa))
        self.v_hat_preva = tf.Variable(tf.zeros_like(self.wa))

    def feedforward(self,input,droprate=1.0,strides=1):
        self.input  = input

        self.layer_pass = tf.nn.dropout(tf.nn.conv2d(input,self.wa,strides=[1,strides,strides,1],padding='SAME'),droprate)

        self.layer1  = tf.nn.dropout(tf.nn.conv2d(input,self.w1,strides=[1,strides,strides,1],padding='SAME'),droprate)
        self.layerA1 = tf_elu(self.layer1)

        self.layer2 = tf.nn.dropout(tf.nn.conv2d(self.layerA1,self.w2,strides=[1,1,1,1],padding='SAME'),droprate)
        self.layerA2 = tf_elu(self.layer2)

        self.layer_add = self.layerA2 + self.layer_pass

        return self.layer_add 

    def backprop(self,gradient,learning_rate_change,batch_size_dynamic,strides=1,awsgrad=True,reg=False):
        update_w = []
        
        # ===== w2 update ======
        grad_part_1_2 = gradient 
        grad_part_2_2 = d_tf_elu(self.layer2) 
        grad_part_3_2 = self.layerA1
        grad_middle_2 = grad_part_1_2 * grad_part_2_2

        grad_2 = tf.nn.conv2d_backprop_filter(
            input = grad_part_3_2,
            filter_sizes = self.w2.shape,out_backprop = grad_middle_2,
            strides=[1,1,1,1],padding='SAME'
        )

        grad_pass_2 = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3_2.shape[1:]),
            filter= self.w2,out_backprop = grad_middle_2,
            strides=[1,1,1,1],padding='SAME'
        )

        # ==== HAVE TO UPDATE TO W2 ========
        if awsgrad:
            update_w.append(tf.assign( self.m2,self.m2*beta1 + (1-beta1) * grad_2   ))
            v_t2 = self.v_prev2 *beta2 + (1-beta2) * grad_2 ** 2 
            def f1(): return v_t2
            def f2(): return self.v_hat_prev2
            v_max2 = tf.cond(tf.greater(tf.reduce_sum(v_t2), tf.reduce_sum(self.v_hat_prev2) ) , true_fn=f1, false_fn=f2)
            adam_middel2 = learning_rate/(tf.sqrt(v_max2) + adam_e)
            if reg: adam_middel2 = adam_middel2 - learning_rate_change * decoupled_weight * self.w2
            update_w.append(tf.assign( self.w2,tf.subtract(self.w2,tf.multiply(adam_middel2,self.m2))))
            update_w.append(tf.assign( self.v_prev2,v_t2 ))
            update_w.append(tf.assign( self.v_hat_prev2,v_max2))        
        else:
            update_w.append(tf.assign( self.m2,self.m2*beta1 + (1-beta1) * (grad_2)   ))
            update_w.append(tf.assign( self.v_prev2,self.v_prev2*beta2 + (1-beta2) * (grad_2 ** 2)   ))
            m_hat2 = self.m2 / (1-beta1)
            v_hat2 = self.v_prev2 / (1-beta2)
            adam_middel2 = learning_rate_change/(tf.sqrt(v_hat2) + adam_e)
            adam_middel2 = tf.multiply(adam_middel2,m_hat2)
            if reg: adam_middel2 = adam_middel2 - learning_rate_change * decoupled_weight * self.w2
            update_w.append(tf.assign(self.w2,tf.subtract(self.w2,adam_middel2  )) )    

        # ===== w1 update ======
        grad_part_1_1 = grad_pass_2 
        grad_part_2_1 = d_tf_elu(self.layer1) 
        grad_part_3_1 = self.input
        grad_middle_1 = grad_part_1_1 * grad_part_2_1

        grad_1 = tf.nn.conv2d_backprop_filter(
            input = grad_part_3_1,
            filter_sizes = self.w1.shape,out_backprop = grad_middle_1,
            strides=[1,strides,strides,1],padding='SAME'
        )

        grad_pass_1 = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3_1.shape[1:]),
            filter= self.w1,out_backprop = grad_middle_1,
            strides=[1,strides,strides,1],padding='SAME'
        )

        # ==== HAVE TO UPDATE TO W1 ========
        if awsgrad:
            update_w.append(tf.assign( self.m1,self.m1*beta1 + (1-beta1) * grad_1   ))
            v_t1 = self.v_prev1 *beta2 + (1-beta2) * grad_1 ** 2 
            def f1(): return v_t1
            def f2(): return self.v_hat_prev1
            v_max1 = tf.cond(tf.greater(tf.reduce_sum(v_t1), tf.reduce_sum(self.v_hat_prev1) ) , true_fn=f1, false_fn=f2)
            adam_middel1 = learning_rate/(tf.sqrt(v_max1) + adam_e)
            if reg: adam_middel1 = adam_middel1 - learning_rate_change * decoupled_weight * self.w1
            update_w.append(tf.assign( self.w1,tf.subtract(self.w1,tf.multiply(adam_middel1,self.m1))))
            update_w.append(tf.assign( self.v_prev1,v_t1 ))
            update_w.append(tf.assign( self.v_hat_prev1,v_max1 ))        
        else:
            update_w.append(tf.assign( self.m1,self.m1*beta1 + (1-beta1) * (grad_1)   ))
            update_w.append(tf.assign( self.v_prev1,self.v_prev1*beta2 + (1-beta2) * (grad_1 ** 2)   ))
            m_hat1 = self.m1 / (1-beta1)
            v_hat1 = self.v_prev1 / (1-beta2)
            adam_middel1 = learning_rate_change/(tf.sqrt(v_hat1) + adam_e)
            adam_middel1 = tf.multiply(adam_middel1,m_hat1)
            if reg: adam_middel1 = adam_middel1 - learning_rate_change * decoupled_weight * self.w1
            update_w.append(tf.assign(self.w1,tf.subtract(self.w1,adam_middel1  )) )    

        # ===== wa update ======
        grad_part_1_a = gradient 
        grad_part_3_a = self.input

        grad_a = tf.nn.conv2d_backprop_filter(
            input = grad_part_3_a,
            filter_sizes = self.wa.shape,out_backprop = grad_part_1_a,
            strides=[1,strides,strides,1],padding='SAME'
        )

        grad_pass_a = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3_a.shape[1:]),
            filter= self.wa,out_backprop = grad_part_1_a,
            strides=[1,strides,strides,1],padding='SAME'
        )

        # ==== HAVE TO UPDATE TO Wa ========
        if awsgrad:
            update_w.append(tf.assign( self.ma,self.ma*beta1 + (1-beta1) * grad_a   ))
            v_ta = self.v_preva *beta2 + (1-beta2) * grad_a ** 2 
            def f1(): return v_ta
            def f2(): return self.v_hat_preva
            v_maxa = tf.cond(tf.greater(tf.reduce_sum(v_ta), tf.reduce_sum(self.v_hat_preva) ) , true_fn=f1, false_fn=f2)
            adam_middela = learning_rate/(tf.sqrt(v_maxa) + adam_e)
            if reg: adam_middela = adam_middela - learning_rate_change * decoupled_weight * self.wa
            update_w.append(tf.assign( self.wa,tf.subtract(self.wa,tf.multiply(adam_middela,self.ma))))
            update_w.append(tf.assign( self.v_preva,v_ta ))     
            update_w.append(tf.assign( self.v_hat_preva,v_maxa ))        
        else:
            update_w.append(tf.assign( self.ma,self.ma*beta1 + (1-beta1) * (grad_a)   ))
            update_w.append(tf.assign( self.v_preva,self.v_preva*beta2 + (1-beta2) * (grad_a ** 2)   ))
            m_hata = self.ma / (1-beta1)
            v_hata = self.v_preva / (1-beta2)
            adam_middela = learning_rate_change/(tf.sqrt(v_hata) + adam_e)
            adam_middela = tf.multiply(adam_middela,m_hata)
            if reg: adam_middela = adam_middela - learning_rate_change * decoupled_weight * self.a
            update_w.append(tf.assign(self.wa,tf.subtract(self.wa,adam_middela  )) )    

        return grad_pass_1 + grad_pass_a,update_w   

# Def: Convolution Layer more deeper residual
class conv_res_2_layer():
    def __init__(self,k,inc,out):
        self.w1 = tf.Variable(tf.random_normal([k,k,inc,out],stddev=0.05))
        self.w2 = tf.Variable(tf.random_normal([k,k,out,out],stddev=0.05))
        
        self.m1,self.v_prev1 = tf.Variable(tf.zeros_like(self.w1)),tf.Variable(tf.zeros_like(self.w1))
        self.v_hat_prev1 = tf.Variable(tf.zeros_like(self.w1))

        self.m2,self.v_prev2 = tf.Variable(tf.zeros_like(self.w2)),tf.Variable(tf.zeros_like(self.w2))
        self.v_hat_prev2 = tf.Variable(tf.zeros_like(self.w2))

    def feedforward(self,input,droprate=1.0,strides=1):
        self.input  = input

        self.layer1  = tf.nn.dropout(tf.nn.conv2d(input,self.w1,strides=[1,strides,strides,1],padding='SAME'),droprate)
        self.layerA1 = tf_elu(self.layer1)

        self.layer2 = tf.nn.dropout(tf.nn.conv2d(self.layerA1,self.w2,strides=[1,strides,strides,1],padding='SAME'),droprate)
        self.layerA2 = tf_elu(self.layer2)

        self.layer_add = self.layerA2 + self.input

        return self.layer_add 

    def backprop(self,gradient,learning_rate_change,batch_size_dynamic,strides=1,awsgrad=True,reg=False):
        update_w = []
        
        # ===== w2 update ======
        grad_part_1_2 = gradient 
        grad_part_2_2 = d_tf_elu(self.layer2) 
        grad_part_3_2 = self.layerA1
        grad_middle_2 = grad_part_1_2 * grad_part_2_2

        grad_2 = tf.nn.conv2d_backprop_filter(
            input = grad_part_3_2,
            filter_sizes = self.w2.shape,out_backprop = grad_middle_2,
            strides=[1,1,1,1],padding='SAME'
        )

        grad_pass_2 = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3_2.shape[1:]),
            filter= self.w2,out_backprop = grad_middle_2,
            strides=[1,1,1,1],padding='SAME'
        )

        # ==== HAVE TO UPDATE TO W2 ========
        if awsgrad:
            update_w.append(tf.assign( self.m2,self.m2*beta1 + (1-beta1) * grad_2   ))
            v_t2 = self.v_prev2 *beta2 + (1-beta2) * grad_2 ** 2 
            def f1(): return v_t2
            def f2(): return self.v_hat_prev2
            v_max2 = tf.cond(tf.greater(tf.reduce_sum(v_t2), tf.reduce_sum(self.v_hat_prev2) ) , true_fn=f1, false_fn=f2)
            adam_middel2 = learning_rate/(tf.sqrt(v_max2) + adam_e)
            if reg: adam_middel2 = adam_middel2 - learning_rate_change * decoupled_weight * self.w2
            update_w.append(tf.assign( self.w2,tf.subtract(self.w2,tf.multiply(adam_middel2,self.m2))))
            update_w.append(tf.assign( self.v_prev2,v_t2 ))
            update_w.append(tf.assign( self.v_hat_prev2,v_max2))        
        else:
            update_w.append(tf.assign( self.m2,self.m2*beta1 + (1-beta1) * (grad_2)   ))
            update_w.append(tf.assign( self.v_prev2,self.v_prev2*beta2 + (1-beta2) * (grad_2 ** 2)   ))
            m_hat2 = self.m2 / (1-beta1)
            v_hat2 = self.v_prev2 / (1-beta2)
            adam_middel2 = learning_rate_change/(tf.sqrt(v_hat2) + adam_e)
            adam_middel2 = tf.multiply(adam_middel2,m_hat2)
            if reg: adam_middel2 = adam_middel2 - learning_rate_change * decoupled_weight * self.w2
            update_w.append(tf.assign(self.w2,tf.subtract(self.w2,adam_middel2  )) )    

        # ===== w1 update ======
        grad_part_1_1 = grad_pass_2 
        grad_part_2_1 = d_tf_elu(self.layer1) 
        grad_part_3_1 = self.input
        grad_middle_1 = grad_part_1_1 * grad_part_2_1

        grad_1 = tf.nn.conv2d_backprop_filter(
            input = grad_part_3_1,
            filter_sizes = self.w1.shape,out_backprop = grad_middle_1,
            strides=[1,strides,strides,1],padding='SAME'
        )

        grad_pass_1 = tf.nn.conv2d_backprop_input(
            input_sizes = [batch_size_dynamic] + list(grad_part_3_1.shape[1:]),
            filter= self.w1,out_backprop = grad_middle_1,
            strides=[1,strides,strides,1],padding='SAME'
        )

        # ==== HAVE TO UPDATE TO W1 ========
        if awsgrad:
            update_w.append(tf.assign( self.m1,self.m1*beta1 + (1-beta1) * grad_1   ))
            v_t1 = self.v_prev1 *beta2 + (1-beta2) * grad_1 ** 2 
            def f1(): return v_t1
            def f2(): return self.v_hat_prev1
            v_max1 = tf.cond(tf.greater(tf.reduce_sum(v_t1), tf.reduce_sum(self.v_hat_prev1) ) , true_fn=f1, false_fn=f2)
            adam_middel1 = learning_rate/(tf.sqrt(v_max1) + adam_e)
            if reg: adam_middel1 = adam_middel1 - learning_rate_change * decoupled_weight * self.w1
            update_w.append(tf.assign( self.w1,tf.subtract(self.w1,tf.multiply(adam_middel1,self.m1))))
            update_w.append(tf.assign( self.v_prev1,v_t1 ))
            update_w.append(tf.assign( self.v_hat_prev1,v_max1 ))        
        else:
            update_w.append(tf.assign( self.m1,self.m1*beta1 + (1-beta1) * (grad_1)   ))
            update_w.append(tf.assign( self.v_prev1,self.v_prev1*beta2 + (1-beta2) * (grad_1 ** 2)   ))
            m_hat1 = self.m1 / (1-beta1)
            v_hat1 = self.v_prev1 / (1-beta2)
            adam_middel1 = learning_rate_change/(tf.sqrt(v_hat1) + adam_e)
            adam_middel1 = tf.multiply(adam_middel1,m_hat1)
            if reg: adam_middel1 = adam_middel1 - learning_rate_change * decoupled_weight * self.w1
            update_w.append(tf.assign(self.w1,tf.subtract(self.w1,adam_middel1  )) )    

        return grad_pass_1,update_w   

# # data
PathDicom = "../../Dataset/cifar-10-batches-py/"
lstFilesDCM = []  # create an empty list
for dirName, subdirList, fileList in os.walk(PathDicom):
    for filename in fileList:
        if not ".html" in filename.lower() and not  ".meta" in filename.lower():  # check whether the file's DICOM
            lstFilesDCM.append(os.path.join(dirName,filename))

# Read the data traind and Test
batch0 = unpickle(lstFilesDCM[0])
batch1 = unpickle(lstFilesDCM[1])
batch2 = unpickle(lstFilesDCM[2])
batch3 = unpickle(lstFilesDCM[3])
batch4 = unpickle(lstFilesDCM[4])

onehot_encoder = OneHotEncoder(sparse=True)
train_batch = np.vstack((batch0[b'data'],batch1[b'data'],batch2[b'data'],batch3[b'data'],batch4[b'data']))
train_label = np.expand_dims(np.hstack((batch0[b'labels'],batch1[b'labels'],batch2[b'labels'],batch3[b'labels'],batch4[b'labels'])).T,axis=1).astype(np.float32)
train_label = onehot_encoder.fit_transform(train_label).toarray().astype(np.float32)

test_batch = unpickle(lstFilesDCM[5])[b'data']
test_label = np.expand_dims(np.array(unpickle(lstFilesDCM[5])[b'labels']),axis=0).T.astype(np.float32)
test_label = onehot_encoder.fit_transform(test_label).toarray().astype(np.float32)

# reshape data
train_batch = np.reshape(train_batch,(len(train_batch),3,32,32))
test_batch = np.reshape(test_batch,(len(test_batch),3,32,32))

# rotate data
train_batch = np.rot90(np.rot90(train_batch,1,axes=(1,3)),3,axes=(1,2)).astype(np.float32)
test_batch = np.rot90(np.rot90(test_batch,1,axes=(1,3)),3,axes=(1,2)).astype(np.float32)

# standardize Normalize data per channel
test_batch[:,:,:,0]  = (test_batch[:,:,:,0] - test_batch[:,:,:,0].mean(axis=0)) / ( test_batch[:,:,:,0].std(axis=0)+ 1e-20)
test_batch[:,:,:,1]  = (test_batch[:,:,:,1] - test_batch[:,:,:,1].mean(axis=0)) / ( test_batch[:,:,:,1].std(axis=0)+ 1e-20)
test_batch[:,:,:,2]  = (test_batch[:,:,:,2] - test_batch[:,:,:,2].mean(axis=0)) / ( test_batch[:,:,:,2].std(axis=0)+ 1e-20)

# # print out the data shape
print(train_batch.shape)
print(train_label.shape)
print(test_batch.shape)
print(test_label.shape)

# hyper
num_epoch = 31  
batch_size = 50
print_size = 1
beta1,beta2,adam_e = 0.9,0.9,1e-8

learning_rate = 0.0001
learnind_rate_decay = 0

proportion_rate = 0.000001
decay_rate = 10

k = 2
decoupled_weight  = 0.0000001

# define class
l1 = conv_layer(3,3,16)

l2_1 = conv_res_1_layer(3,16,16*k)
l2_2 = conv_res_2_layer(3,16*k,16*k)
l2_3 = conv_res_2_layer(3,16*k,16*k)
l2_4 = conv_res_2_layer(3,16*k,16*k)

l3_1 = conv_res_1_layer(3,16*k,32*k)
l3_2 = conv_res_2_layer(3,32*k,32*k)
l3_3 = conv_res_2_layer(3,32*k,32*k)
l3_4 = conv_res_2_layer(3,32*k,32*k)

l4_1 = conv_res_1_layer(3,32*k,64*k)
l4_2 = conv_res_2_layer(3,64*k,64*k)
l4_3 = conv_res_2_layer(3,64*k,64*k)
l4_4 = conv_res_2_layer(3,64*k,64*k)

final_l = conv_layer(1,64*k,10)

# graph
x = tf.placeholder(shape=[None,32,32,3],dtype=tf.float32)
y = tf.placeholder(shape=[None,10],dtype=tf.float32)

batch_size_dynamic= tf.placeholder(tf.int32, shape=())

droprate1,droprate2,droprate3,droprate4 = tf.placeholder(tf.float32, shape=()),tf.placeholder(tf.float32, shape=()),tf.placeholder(tf.float32, shape=()),tf.placeholder(tf.float32, shape=())
iter_variable = tf.placeholder(tf.float32, shape=())
learning_rate_dynamic  = tf.placeholder(tf.float32, shape=())
learning_rate_change = learning_rate_dynamic * (1.0/(1.0+learnind_rate_decay*iter_variable))
decay_dilated_rate   = proportion_rate       * (1.0/(1.0+decay_rate*iter_variable))

layer1 = l1.feedforward(x,droprate=droprate1)

layer2_1 = l2_1.feedforward(layer1,droprate=droprate1)
layer2_2 = l2_2.feedforward(layer2_1,droprate=droprate2)
layer2_3 = l2_3.feedforward(layer2_2+decay_dilated_rate*layer2_1,droprate=droprate3)
layer2_4 = l2_4.feedforward(layer2_3+decay_dilated_rate*(layer2_1 + layer2_2),droprate=droprate4)

layer3_1 = l3_1.feedforward(layer2_4,strides=2,droprate=droprate4)
layer3_2 = l3_2.feedforward(layer3_1,droprate=droprate1)
layer3_3 = l3_3.feedforward(layer3_2+decay_dilated_rate*layer3_1,droprate=droprate2)
layer3_4 = l3_4.feedforward(layer3_3+decay_dilated_rate*(layer3_1 + layer3_2),droprate=droprate3)

layer4_1 = l4_1.feedforward(layer3_4,strides=2,droprate=droprate3)
layer4_2 = l4_2.feedforward(layer4_1,droprate=droprate4)
layer4_3 = l4_3.feedforward(layer4_2+decay_dilated_rate*layer4_1,droprate=droprate1)
layer4_4 = l4_4.feedforward(layer4_3+decay_dilated_rate*(layer4_1 + layer4_2),droprate=droprate2)

final_layer = final_l.feedforward(layer4_4)
final_global = tf.reduce_mean(final_layer,[1,2])
final_soft = tf_softmax(final_global)

cost = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(logits=final_global,labels=y))
correct_prediction = tf.equal(tf.argmax(final_soft, 1), tf.argmax(y, 1))
accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))

grad_prepare = tf.reshape(final_soft-y,[batch_size_dynamic,1,1,10])
grad_final,grad_final_up = final_l.backprop(grad_prepare,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False)

grad4_4,grad4_4_up = l4_4.backprop(grad_final,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=False,reg=False)
grad4_3,grad4_3_up = l4_3.backprop(grad4_4,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False)
grad4_2,grad4_2_up = l4_2.backprop(grad4_3 + decay_dilated_rate*grad4_4,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=True)
grad4_1,grad4_1_up = l4_1.backprop(grad4_2 + decay_dilated_rate*(grad4_4+grad4_3),
learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False,strides=2)

grad3_4,grad3_4_up = l3_4.backprop(grad4_1,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False)
grad3_3,grad3_3_up = l3_3.backprop(grad3_4,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=False,reg=True)
grad3_2,grad3_2_up = l3_2.backprop(grad3_3+ decay_dilated_rate*grad3_4,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=False,reg=True)
grad3_1,grad3_1_up = l3_1.backprop(grad3_2+ decay_dilated_rate*(grad3_4+grad3_3),
learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False,strides=2)

grad2_4,grad2_4_up = l2_4.backprop(grad3_1,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=False,reg=False)
grad2_3,grad2_3_up = l2_3.backprop(grad2_4,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False)
grad2_2,grad2_2_up = l2_2.backprop(grad2_3+ decay_dilated_rate*grad2_4,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=True)
grad2_1,grad2_1_up = l2_1.backprop(grad2_2+ decay_dilated_rate*(grad2_4+grad2_3),
learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=False)

grad1,grad1_up = l1.backprop(grad2_1,learning_rate_change=learning_rate_change,batch_size_dynamic=batch_size_dynamic,awsgrad=True,reg=True)

#   grad4_4_up + grad4_3_up + grad4_2_up + grad4_1_up + 
grad_update = grad_final_up + \
              grad4_4_up+grad4_3_up + grad4_2_up + grad4_1_up + \
              grad3_4_up+grad3_3_up + grad3_2_up + grad3_1_up + \
              grad2_4_up+grad2_3_up + grad2_2_up + grad2_1_up + \
              grad1_up

# sess
with tf.Session() as sess:

    sess.run(tf.global_variables_initializer())
    
    train_cota,train_acca = 0,0
    train_cot,train_acc = [],[]
    
    test_cota,test_acca = 0,0
    test_cot,test_acc = [],[]
    data_input_type = 0 

    for iter in range(num_epoch):

        train_batch,train_label = shuffle(train_batch,train_label)

        lower_bound = 0.005 * (iter+1)/num_epoch
        random_drop1 = np.random.uniform(low=0.995+lower_bound,high=1.000000000000001)
        random_drop2 = np.random.uniform(low=0.995+lower_bound,high=1.000000000000001)
        random_drop3 = np.random.uniform(low=0.995+lower_bound,high=1.000000000000001)
        random_drop4 = np.random.uniform(low=0.995+lower_bound,high=1.000000000000001)

        for batch_size_index in range(0,len(train_batch),batch_size//2):
            current_batch = train_batch[batch_size_index:batch_size_index+batch_size//2]
            current_batch_label = train_label[batch_size_index:batch_size_index+batch_size//2]

            # data aug
            seq = iaa.Sequential([  
                iaa.Sometimes(  (0.1 + lower_bound * 6) ,
                    iaa.Affine(
                        translate_percent={"x": (-0.2, 0.2), "y": (-0.2, 0.2)},
                    )
                ),
                iaa.Sometimes( (0.2 + lower_bound * 6),
                    iaa.Affine(
                        rotate=(-25, 25),
                    )
                ),
                iaa.Sometimes( (0.1 + lower_bound * 6),
                    iaa.Affine(
                        scale={"x": (0.8, 1.2), "y": (0.8, 1.2)},
                    )
                ),
                iaa.Fliplr(1.0), # Horizontal flips
            ], random_order=True) # apply augmenters in random order

            images_aug = seq.augment_images(current_batch.astype(np.float32))
            current_batch = np.vstack((current_batch,images_aug)).astype(np.float32)
            current_batch_label = np.vstack((current_batch_label,current_batch_label)).astype(np.float32)

            input_sess_array = [cost,accuracy,correct_prediction,grad_update]
            input_feed_dict= {x:current_batch,y:current_batch_label,iter_variable:iter,learning_rate_dynamic:learning_rate,
            batch_size_dynamic:current_batch.shape[0],
            droprate1:random_drop1,droprate2:random_drop2,droprate3:random_drop3,droprate4:random_drop4}

            # online data augmentation here and standard normalization
            current_batch[:,:,:,0]  = (current_batch[:,:,:,0] - current_batch[:,:,:,0].mean(axis=0)) / ( current_batch[:,:,:,0].std(axis=0)+ 1e-20)
            current_batch[:,:,:,1]  = (current_batch[:,:,:,1] - current_batch[:,:,:,1].mean(axis=0)) / ( current_batch[:,:,:,1].std(axis=0)+ 1e-20)
            current_batch[:,:,:,2]  = (current_batch[:,:,:,2] - current_batch[:,:,:,2].mean(axis=0)) / ( current_batch[:,:,:,2].std(axis=0)+ 1e-20)
            current_batch,current_batch_label  = shuffle(current_batch,current_batch_label)
            # online data augmentation here and standard normalization

            sess_result = sess.run(input_sess_array,feed_dict=input_feed_dict  )
            print("Current Iter : ",iter, " current batch: ",batch_size_index, ' Current cost: ', sess_result[0],
            ' Current Acc: ', sess_result[1],end='\r')
            train_cota = train_cota + sess_result[0]
            train_acca = train_acca + sess_result[1]
            
        for test_batch_index in range(0,len(test_batch),batch_size):
            current_batch = test_batch[test_batch_index:test_batch_index+batch_size]
            current_batch_label = test_label[test_batch_index:test_batch_index+batch_size]
            sess_result = sess.run([cost,accuracy,correct_prediction],feed_dict={x:current_batch,y:current_batch_label,iter_variable:iter,batch_size_dynamic:current_batch.shape[0]
            ,droprate1:1.0,droprate2:1.0,droprate3:1.0,droprate4:1.0})
            print("Current Iter : ",iter, " current batch: ",test_batch_index, ' Current cost: ', sess_result[0],
            ' Current Acc: ', sess_result[1],end='\r')
            test_acca = sess_result[1] + test_acca
            test_cota = sess_result[0] + test_cota

        if iter % print_size==0:
            print("\n----------" )
            print('Train Current cost: ', train_cota/(len(train_batch)/(batch_size//2)),' Current Acc: ', 
            train_acca/(len(train_batch)/(batch_size//2) ),end='\n')
            print('Test Current cost: ', test_cota/(len(test_batch)/batch_size),' Current Acc: ', 
            test_acca/(len(test_batch)/batch_size),end='\n')
            print("----------")

        train_acc.append(train_acca/(len(train_batch)/batch_size//2))
        train_cot.append(train_cota/(len(train_batch)/batch_size//2))
        test_acc.append(test_acca/(len(test_batch)/batch_size))
        test_cot.append(test_cota/(len(test_batch)/batch_size))
        test_cota,test_acca = 0,0
        train_cota,train_acca = 0,0

    # Normalize the cost of the training
    train_cot = (train_cot-min(train_cot) ) / (max(train_cot)-min(train_cot))
    test_cot = (test_cot-min(test_cot) ) / (max(test_cot)-min(test_cot))

    # training done now plot
    plt.figure()
    plt.plot(range(len(train_acc)),train_acc,color='red',label='acc ovt')
    plt.plot(range(len(train_cot)),train_cot,color='green',label='cost ovt')
    plt.legend()
    plt.title("Train Average Accuracy / Cost Over Time")
    plt.savefig("Case a Train.png")

    plt.figure()
    plt.plot(range(len(test_acc)),test_acc,color='red',label='acc ovt')
    plt.plot(range(len(test_cot)),test_cot,color='green',label='cost ovt')
    plt.legend()
    plt.title("Test Average Accuracy / Cost Over Time")
    plt.savefig("Case a Test.png")




# -- end code --