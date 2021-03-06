#!/usr/bin/env python
# coding=utf-8

import numpy as np
import tensorflow as tf

import utils.model_layer as my_layer
import utils.model_op as op


def model_fn(labels, features, mode, params):
    use_deep = True
    use_fm = True
    tf.set_random_seed(2019)

    cont_feats = features["cont_feats"]
    cate_feats = features["cate_feats"]
    vector_feats = features["vector_feats"]

    cont_feats_index = tf.Variable([[i for i in range(params.cont_field_size)]], trainable=False, dtype=tf.int64, name="cont_feats_index")

    index_max_size = params.cont_field_size + params.cate_feats_size
    fm_first_order_emb = my_layer.emb_init(name='fm_first_order_emb', feat_num=index_max_size, embedding_size=1)
    feats_emb = my_layer.emb_init(name='feats_emb', feat_num=index_max_size, embedding_size=params.embedding_size)

    with tf.name_scope('fm_part'):
        input_field_size = params.cont_field_size + params.cate_field_size + len(params.multi_feats_range)
        cont_index_add = tf.add(cont_feats_index, params.cate_feats_size)

        # FM_first_order [?, input_field_size]
        # cont
        first_cont_emb = tf.nn.embedding_lookup(fm_first_order_emb, ids=cont_index_add)
        first_cont_emb = tf.reshape(first_cont_emb, shape=[-1, params.cont_field_size])
        first_cont_mul = tf.multiply(first_cont_emb, cont_feats)
        # cate
        first_cate_emb = tf.nn.embedding_lookup(fm_first_order_emb, ids=cate_feats)
        first_cate_emb = tf.reshape(first_cate_emb, shape=[-1, params.cate_field_size])
        # concat cont & cate
        first_order_emb = tf.concat([first_cont_mul, first_cate_emb], axis=1)
        first_order = tf.nn.dropout(first_order_emb, params.dropout_keep_fm[0])

        # FM_second_order [?, embedding_size]
        # cont
        second_cont_emb = tf.nn.embedding_lookup(feats_emb, ids=cont_index_add)
        second_cont_value = tf.reshape(cont_feats, shape=[-1, params.cont_field_size, 1])
        second_cont_emb = tf.multiply(second_cont_emb, second_cont_value)
        # single_cate
        second_cate_emb = tf.nn.embedding_lookup(feats_emb, ids=cate_feats)
        # concat cont & cate
        second_order_emb = tf.concat([second_cont_emb, second_cate_emb], axis=1)

        sum_emb = tf.reduce_sum(second_order_emb, 1)
        sum_square_emb = tf.square(sum_emb)
        square_emb = tf.square(second_order_emb)
        square_sum_emb = tf.reduce_sum(square_emb, 1)
        second_order = 0.5 * tf.subtract(sum_square_emb, square_sum_emb)
        second_order = tf.nn.dropout(second_order, params.dropout_keep_fm[1])

        # FM_res [?, self.input_field_size + embedding_size]
        fm_res = tf.concat([first_order, second_order], axis=1)

    with tf.name_scope('deep_part'):
        # category -> Embedding
        cate_emb = tf.nn.embedding_lookup(feats_emb, ids=cate_feats)
        cate_emb = tf.reshape(cate_emb, shape=[-1, params.cate_field_size * params.embedding_size])

        deep_res = tf.concat([cont_feats, vector_feats, cate_emb], axis=1, name='dense_vector')
        # deep
        len_layers = len(params.hidden_units)
        for i in range(0, len_layers):
            deep_res = tf.layers.dense(inputs=deep_res, units=params.hidden_units[i], activation=tf.nn.relu)

    with tf.name_scope('deep_fm'):
        if use_fm and use_deep:
            feats_input = tf.concat([fm_res, deep_res], axis=1)
            feats_input_size = input_field_size + params.embedding_size + params.hidden_units[-1]
        elif use_fm:
            feats_input = fm_res
            feats_input_size = input_field_size + params.embedding_size
        elif use_deep:
            feats_input = deep_res
            feats_input_size = params.hidden_units[-1]

        glorot = np.sqrt(2.0 / (feats_input_size + 1))
        deep_fm_weight = tf.Variable(
            np.random.normal(loc=0, scale=glorot, size=(feats_input_size, 1)), dtype=np.float32)
        deep_fm_bias = tf.Variable(tf.random_normal([1]))

        out = tf.add(tf.matmul(feats_input, deep_fm_weight), deep_fm_bias)

    score = tf.identity(tf.nn.sigmoid(out), name='score')
    model_estimator_spec = op.model_optimizer(params, mode, labels, score)

    return model_estimator_spec


def model_estimator(params):
    # shutil.rmtree(conf.model_dir, ignore_errors=True)
    tf.reset_default_graph()
    config = tf.estimator.RunConfig() \
        .replace(session_config=tf.ConfigProto(device_count={'GPU': params.is_GPU}),
                 log_step_count_steps=params.log_step_count_steps,
                 save_checkpoints_steps=params.save_checkpoints_steps,
                 keep_checkpoint_max=params.keep_checkpoint_max,
                 save_summary_steps=params.save_summary_steps)

    model = tf.estimator.Estimator(
        model_fn=model_fn,
        config=config,
        model_dir=params.model_dir,
        params=params,
    )
    return model
