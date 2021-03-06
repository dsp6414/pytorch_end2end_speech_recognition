#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Define evaluation method by Word Error Rate (Librispeech corpus)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import re
from tqdm import tqdm
import pandas as pd

from utils.io.labels.word import Idx2word
from utils.evaluation.edit_distance import compute_wer


def do_eval_wer(model, dataset, beam_width, max_decode_len,
                eval_batch_size=None, progressbar=False):
    """Evaluate trained model by Word Error Rate.
    Args:
        model: the model to evaluate
        dataset: An instance of a `Dataset' class
        beam_width: (int): the size of beam
        max_decode_len (int): the length of output sequences
            to stop prediction when EOS token have not been emitted.
            This is used for seq2seq models.
        eval_batch_size (int, optional): the batch size when evaluating the model
        progressbar (bool, optional): if True, visualize the progressbar
    Returns:
        wer (float): Word error rate
        df_wer (pd.DataFrame): dataframe of substitution, insertion, and deletion
    """
    # Reset data counter
    dataset.reset()

    idx2word = Idx2word(vocab_file_path=dataset.vocab_file_path)

    wer = 0
    sub, ins, dele, = 0, 0, 0
    num_words = 0
    if progressbar:
        pbar = tqdm(total=len(dataset))  # TODO: fix this
    while True:
        batch, is_new_epoch = dataset.next(batch_size=eval_batch_size)

        # Decode
        best_hyps, perm_idx = model.decode(batch['xs'], batch['x_lens'],
                                           beam_width=beam_width,
                                           max_decode_len=max_decode_len)
        ys = batch['ys'][perm_idx]
        y_lens = batch['y_lens'][perm_idx]

        for b in range(len(batch['xs'])):

            ##############################
            # Reference
            ##############################
            if dataset.is_test:
                str_ref = ys[b][0]
                # NOTE: transcript is seperated by space('_')
            else:
                # Convert from list of index to string
                str_ref = idx2word(ys[b][:y_lens[b]])

            ##############################
            # Hypothesis
            ##############################
            str_hyp = idx2word(best_hyps[b])
            if 'attention' in model.model_type:
                str_hyp = str_hyp.split('>')[0]
                # NOTE: Trancate by the first <EOS>

                # Remove the last space
                if len(str_hyp) > 0 and str_hyp[-1] == '_':
                    str_hyp = str_hyp[:-1]

            ##############################
            # Post-proccessing
            ##############################
            # Remove garbage labels
            str_ref = re.sub(r'[\'>]+', '', str_ref)
            str_hyp = re.sub(r'[\'>]+', '', str_hyp)
            # TODO: WER計算するときに消していい？

            # Compute WER
            wer_b, sub_b, ins_b, del_b = compute_wer(
                ref=str_ref.split('_'),
                hyp=str_hyp.split('_'),
                normalize=True)
            wer += wer_b
            sub += sub_b
            ins += ins_b
            dele += del_b
            num_words += len(str_ref.split('_'))

            if progressbar:
                pbar.update(1)

        if is_new_epoch:
            break

    if progressbar:
        pbar.close()

    wer /= num_words
    sub /= num_words
    ins /= num_words
    dele /= num_words

    df_wer = pd.DataFrame(
        {'SUB': [sub * 100], 'INS': [ins * 100], 'DEL': [dele * 100]},
        columns=['SUB', 'INS', 'DEL'], index=['WER'])

    return wer, df_wer
