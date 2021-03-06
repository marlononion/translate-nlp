# -*- coding: utf-8 -*-

__author__ = "Marlon"
__dataset__ = "https://www.statmt.org/europarl/"

import numpy as np
import pandas as pd
import math
import re
import time
import zipfile
import random
from google.colab import drive
import tensorflow as tf
from tensorflow.keras import layers
import tensorflow_datasets as tfds


with open("/content/pt-en/europarl-v7.pt-en.en", "r", encoding="utf-8") as f:
  europarl_en = f.read()
with open("/content/pt-en/europarl-v7.pt-en.pt", "r", encoding="utf-8") as f:
  europarl_pt = f.read()

europarl_en[0:100]

en = europarl_en.split("\n")



pt = europarl_pt.split("\n")

for _ in range(5):
  print("-"*10)
  i = random.randint(0, len(en) -1 )
  print(en[i])
  print(pt[i])

len(pt)

len(en)



"""# Limpeza dos Dados"""

corpus_en = europarl_en
corpus_en = re.sub(r"\.(?=[0-9]|[a-z]|[A-Z])", ".$$$", corpus_en)
corpus_en = re.sub(r".\$\$\$", "", corpus_en)
corpus_en = re.sub(r" +", " ", corpus_en)
corpus_en = corpus_en.split("\n")

corpus_pt = europarl_pt
corpus_pt = re.sub(r"\.(?=[0-9]|[a-z]|[A-Z])", ".$$$", corpus_pt)
corpus_pt = re.sub(r".\$\$\$", "", corpus_pt)
corpus_pt = re.sub(r" +", " ", corpus_pt)
corpus_pt = corpus_pt.split("\n")

len(corpus_en), len(corpus_pt)

tokenizer_en = tfds.deprecated.text.SubwordTextEncoder.build_from_corpus(corpus_en, target_vocab_size=2**13)

tokenizer_en.vocab_size

tokenizer_pt = tfds.deprecated.text.SubwordTextEncoder.build_from_corpus(corpus_pt, target_vocab_size=2**13)

tokenizer_pt.vocab_size

vocab_size_en = tokenizer_en.vocab_size + 2
vocab_size_pt = tokenizer_pt.vocab_size + 2

inputs = [[vocab_size_en - 2] + tokenizer_en.encode(setence) + [vocab_size_en -1] for setence in corpus_en]

for _ in range(5):
  print(inputs[random.randint(0, len(inputs) - 1)])

outputs = [[vocab_size_en - 2] + tokenizer_pt.encode(setence) + [vocab_size_pt -1] for setence in corpus_pt]

for _ in range(5):
  print(outputs[random.randint(0, len(outputs) - 1)])



"""# Remoção de Sentenças Longas"""

max_len = 15
idx_remove = [count for count, sent in enumerate(inputs) if len(sent) > max_len]

len(idx_remove)

for idx in reversed(idx_remove):
  del inputs[idx]
  del outputs[idx]

idx_remove = [count for count, sent in enumerate(outputs) if len(sent) > max_len]

for idx in reversed(idx_remove):
  del inputs[idx]
  del outputs[idx]

len(inputs), len(outputs)

"""# Padding e Batches"""

inputs = tf.keras.preprocessing.sequence.pad_sequences(inputs, value=0, padding="post", maxlen=max_len)
outputs = tf.keras.preprocessing.sequence.pad_sequences(outputs, value=0, padding="post", maxlen=max_len)

for _ in range(5):
  print(outputs[random.randint(0, len(outputs) - 1)])

batch_size = 64
buffer_size = 20000

dataset = tf.data.Dataset.from_tensor_slices((inputs, outputs)) # Transformar no formato do tensorflow
dataset = dataset.cache()
dataset = dataset.shuffle(buffer_size).batch(batch_size)
dataset = dataset.prefetch(tf.data.experimental.AUTOTUNE)

"""# Construção do Modelo

## Embedding
"""

class PositionalEncoding(layers.Layer):

  def __init__(self):
    super(PositionalEncoding, self).__init__()

  def get_angles(self, pos, i, d_model):
    angles = 1/np.power(10000., (2*(i // 2)) / np.float32(d_model))
    return pos * angles # (seq_len, d_model)

  def call(self, inputs):
    seq_len = inputs.shape.as_list()[-2]
    d_model = inputs.shape.as_list()[-1]
    angles = self.get_angles(np.arange(seq_len)[:, np.newaxis], 
                             np.arange(d_model)[np.newaxis, :], d_model)
    
    angles[:, 0::2] = np.sin(angles[:, 0::2])
    angles[:, 1::2] = np.cos(angles[:, 1::2])
    pos_encoding = angles[np.newaxis, ...]
    return inputs + tf.cast(pos_encoding, tf.float32)

"""## Mecanismo de Atenção"""

def scaled_dot_product_attention(queries, keys, values, mask):
  product = tf.matmul(queries, keys, transpose_b=True)
  keys_dim = tf.cast(tf.shape(keys)[-1], tf.float32)
  scaled_product = product / tf.math.sqrt(keys_dim)

  if mask is not None:
    scaled_product += (mask * -1e9)

  attention = tf.matmul(tf.nn.softmax(scaled_product, axis=-1), values)

  return attention

class MultiHeadAttention(layers.Layer):
    
    def __init__(self, nb_proj):
      super(MultiHeadAttention, self).__init__()
      self.nb_proj = nb_proj
        
    def build(self, input_shape):
      self.d_model = input_shape[-1]
      assert self.d_model % self.nb_proj == 0

      self.d_proj = self.d_model // self.nb_proj

      self.query_lin = layers.Dense(units = self.d_model)
      self.key_lin = layers.Dense(units = self.d_model)
      self.value_lin = layers.Dense(units = self.d_model)

      self.final_lin = layers.Dense(units = self.d_model)
    
    def split_proj(self, inputs, batch_size): # inputs: (batch_size, seq_lenght, d_model)
      shape = (batch_size, -1, self.nb_proj, self.d_proj)
      splited_inputs = tf.reshape(inputs, shape = shape) # (batch_size, seq_lenght, nb_proj, d_proj)
      return tf.transpose(splited_inputs, perm=[0, 2, 1, 3]) # (batch_size, nb_proj, seq_lenght, d_proj)
   
    def call(self, queries, keys, values, mask):
      batch_size = tf.shape(queries)[0]

      queries = self.query_lin(queries)
      keys = self.key_lin(keys)
      values = self.value_lin(values)

      queries = self.split_proj(queries, batch_size)
      keys = self.split_proj(keys, batch_size)
      values = self.split_proj(values, batch_size)

      attention = scaled_dot_product_attention(queries, keys, values, mask)

      attention = tf.transpose(attention, perm=[0, 2, 1, 3])

      concat_attention = tf.reshape(attention, shape=(batch_size, -1, self.d_model))

      outputs = self.final_lin(concat_attention)
      
      return outputs

"""## Encoder"""

class EncoderLayer(layers.Layer):
    
    def __init__(self, FFN_units, nb_proj, dropout_rate):
      super(EncoderLayer, self).__init__()
      self.FFN_units = FFN_units
      self.nb_proj = nb_proj
      self.dropout_rate = dropout_rate
    
    def build(self, input_shape):
      self.d_model = input_shape[-1]

      self.multi_head_attention = MultiHeadAttention(self.nb_proj)
      self.dropout_1 = layers.Dropout(rate=self.dropout_rate)
      self.norm_1 = layers.LayerNormalization(epsilon=1e-6) # 0.0000001

      self.dense_1 = layers.Dense(units=self.FFN_units, activation='relu')
      self.dense_2 = layers.Dense(units=self.d_model, activation='relu')
      self.dropout_2 = layers.Dropout(rate=self.dropout_rate)

      self.norm_2 = layers.LayerNormalization(epsilon=1e-6)
        
    def call(self, inputs, mask, training):
      attention = self.multi_head_attention(inputs, inputs, inputs, mask)
      attention = self.dropout_1(attention, training = training)
      attention = self.norm_1(attention + inputs)

      outputs = self.dense_1(attention)
      outputs = self.dense_2(outputs)
      outputs = self.dropout_2(outputs, training=training)
      outputs = self.norm_2(outputs + attention)

      return outputs

class Encoder(layers.Layer):
    
    def __init__(self,
                 nb_layers,
                 FFN_units,
                 nb_proj,
                 dropout_rate,
                 vocab_size,
                 d_model,
                 name="encoder"):
      super(Encoder, self).__init__(name=name)
      self.nb_layers = nb_layers
      self.d_model = d_model

      self.embedding = layers.Embedding(vocab_size, d_model)
      self.pos_encoding = PositionalEncoding()
      self.dropout = layers.Dropout(rate=dropout_rate)
      self.enc_layers = [EncoderLayer(FFN_units, nb_proj, dropout_rate) for _ in range(nb_layers)]

    
    def call(self, inputs, mask, training):
      outputs = self.embedding(inputs)
      outputs *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
      outputs = self.pos_encoding(outputs)
      outputs = self.dropout(outputs, training)

      for i in range(self.nb_layers):
        outputs = self.enc_layers[i](outputs, mask, training)

      return outputs

"""## Decoder"""

class DecoderLayer(layers.Layer):
    
    def __init__(self, FFN_units, nb_proj, dropout_rate):
      super(DecoderLayer, self).__init__()
      self.FFN_units = FFN_units
      self.nb_proj = nb_proj
      self.dropout_rate = dropout_rate
        
    def build(self, input_shape):
      self.d_model = input_shape[-1]

      self.multi_head_attention_1 = MultiHeadAttention(self.nb_proj)
      self.dropout_1 = layers.Dropout(rate=self.dropout_rate)
      self.norm_1 = layers.LayerNormalization(epsilon=1e-6)

      self.multi_head_attention_2 = MultiHeadAttention(self.nb_proj)
      self.dropout_2 = layers.Dropout(rate=self.dropout_rate)
      self.norm_2 = layers.LayerNormalization(epsilon=1e-6)

      self.dense_1 = layers.Dense(units = self.FFN_units, activation='relu')
      self.dense_2 = layers.Dense(units = self.d_model, activation='relu')
      self.dropout_3 = layers.Dropout(rate=self.dropout_rate)
      self.norm_3 = layers.LayerNormalization(epsilon=1e-6)
               
    def call(self, inputs, enc_outputs, mask_1, mask_2, training):
      attention = self.multi_head_attention_1(inputs, inputs, inputs, mask_1)
      attention = self.dropout_1(attention, training)
      attention = self.norm_1(attention + inputs)

      attention_2 = self.multi_head_attention_2(attention, enc_outputs, enc_outputs, mask_2)
      attention_2 = self.dropout_2(attention_2, training)
      attention_2 = self.norm_2(attention_2 + attention)

      outputs = self.dense_1(attention_2)
      outputs = self.dense_2(outputs)
      outputs = self.dropout_3(outputs, training)
      outputs = self.norm_3(outputs + attention_2)

      return outputs

class Decoder(layers.Layer):
    
    def __init__(self,
                 nb_layers,
                 FFN_units,
                 nb_proj,
                 dropout_rate,
                 vocab_size,
                 d_model,
                 name="decoder"):
      super(Decoder, self).__init__(name=name)
      self.d_model = d_model
      self.nb_layers = nb_layers

      self.embedding = layers.Embedding(vocab_size, d_model)
      self.pos_encoding = PositionalEncoding()
      self.dropout = layers.Dropout(rate=dropout_rate)

      self.dec_layers = [DecoderLayer(FFN_units, nb_proj, dropout_rate) for i in range(nb_layers)]
        
    def call(self, inputs, enc_outputs, mask_1, mask_2, training):
      outputs = self.embedding(inputs)
      outputs *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
      outputs = self.pos_encoding(outputs)
      outputs = self.dropout(outputs, training)

      for i in range(self.nb_layers):
        outputs = self.dec_layers[i](outputs, enc_outputs, mask_1, mask_2, training)

      return outputs

"""## Transformer"""

class Transformer(tf.keras.Model):
    
    def __init__(self,
                 vocab_size_enc,
                 vocab_size_dec,
                 d_model,
                 nb_layers,
                 FFN_units,
                 nb_proj,
                 dropout_rate,
                 name="transformer"):
        super(Transformer, self).__init__(name=name)

        self.encoder = Encoder(nb_layers, FFN_units, nb_proj, dropout_rate, 
                               vocab_size_enc, d_model)
        self.decoder = Decoder(nb_layers, FFN_units, nb_proj, dropout_rate,
                               vocab_size_dec, d_model)
        self.last_linear = layers.Dense(units=vocab_size_dec, name='lin_output')
                
    def create_padding_mask(self, seq): # (batch_size, seq_length) -> (batch_size, nb_proj, seq_lenght, d_proj)
      mask = tf.cast(tf.math.equal(seq, 0), tf.float32)
      return mask[:, tf.newaxis, tf.newaxis, :]
    
    def create_look_ahead_mask(self, seq):
      seq_len = tf.shape(seq)[1]
      look_ahed_mask = 1 - tf.linalg.band_part(tf.ones((seq_len, seq_len)), -1, 0)
      return look_ahed_mask
    
    def call(self, enc_inputs, dec_inputs, training):
      enc_mask = self.create_padding_mask(enc_inputs)
      dec_mask_1 = tf.maximum(self.create_padding_mask(dec_inputs), self.create_look_ahead_mask(dec_inputs))
      dec_mask_2 = self.create_padding_mask(enc_inputs)

      enc_outputs = self.encoder(enc_inputs, enc_mask, training)
      dec_outputs = self.decoder(dec_inputs, enc_outputs, dec_mask_1, dec_mask_2, training)

      outputs = self.last_linear(dec_outputs)

      return outputs

"""# Treinamento"""

tf.keras.backend.clear_session()


d_model = 128 
nb_layers = 4
ffn_units = 512
nb_proj = 8
dropout_rate = 0.1

transformer = Transformer(vocab_size_enc=vocab_size_en, vocab_size_dec=vocab_size_pt, d_model=d_model, 
                          nb_layers=nb_layers, FFN_units=ffn_units, nb_proj=nb_proj, dropout_rate=dropout_rate)

loss_object = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True, reduction='none')

def loss_function(target, pred):
  mask = tf.math.logical_not(tf.math.equal(target, 0))
  loss_ = loss_object(target, pred)

  mask = tf.cast(mask, dtype=loss_.dtype)
  loss_ *= mask

  return tf.reduce_mean(loss_)

train_loss = tf.keras.metrics.Mean(name="train_loss")
train_accuracy = tf.keras.metrics.SparseCategoricalAccuracy(name="train_accuracy")

class CustomSchedule(tf.keras.optimizers.schedules.LearningRateSchedule):

  def __init__(self, d_model, warmup_steps=4000):
    super(CustomSchedule, self).__init__()

    self.d_model = tf.cast(d_model, tf.float32)
    self.warmup_steps = warmup_steps

  def __call__(self, step):
    arg1 = tf.math.rsqrt(step)
    arg2 = step * (self.warmup_steps ** -1.5)

    return tf.math.rsqrt(self.d_model) * tf.math.minimum(arg1, arg2)

learning_rate = CustomSchedule(d_model)

optimizer = tf.keras.optimizers.Adam(learning_rate, beta_1=0.9, beta_2=0.98, epsilon=1e-9)

checkpoint_path = "/content/drive/MyDrive/"
ckpt = tf.train.Checkpoint(transformer=transformer, optimizer=optimizer)
ckpt_manager = tf.train.CheckpointManager(ckpt, checkpoint_path, max_to_keep=5)
if ckpt_manager.latest_checkpoint:
  ckpt.restore(ckpt_manager.latest_checkpoint)
  print("Último Checkpoint Restaurado")

epochs = 10
for epoch in range(epochs):
  print('Start or epoch {}'.format(epoch + 1))
  start = time.time()

  train_loss.reset_states()
  train_accuracy.reset_states()

  for (batch, (enc_inputs, targets)) in enumerate(dataset):
    dec_inputs = targets[:, :-1]
    dec_outputs_real = targets[:, 1:]
    with tf.GradientTape() as tape:
      predictions = transformer(enc_inputs, dec_inputs, True)
      loss = loss_function(dec_outputs_real, predictions)
    
    gradients = tape.gradient(loss, transformer.trainable_variables)
    optimizer.apply_gradients(zip(gradients, transformer.trainable_variables))

    train_loss(loss)
    train_accuracy(dec_outputs_real, predictions)

    if batch % 50 == 0:
      print('Epoch {} Batch {} Loss {:.4f} Accuracy {:.4f}'.format(epoch+1, batch, train_loss.result(), train_accuracy.result()))
  
  ckpt_save_path = ckpt_manager.save()
  print('Saving checkpoint for epoch {} at {}'.format(epoch + 1, ckpt_save_path))
  print('Time taken for 1 epoch {} secs\n'.format(time.time() - start))

