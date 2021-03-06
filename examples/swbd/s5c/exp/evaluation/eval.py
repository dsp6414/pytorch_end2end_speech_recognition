#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Evaluate the trained model (Switchboard corpus)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import join, abspath
import sys
import argparse

sys.path.append(abspath('../../../'))
from models.load_model import load
from examples.swbd.s5c.exp.dataset.load_dataset import Dataset
from examples.swbd.s5c.exp.metrics.character import eval_char
from examples.swbd.s5c.exp.metrics.word import eval_word
from utils.config import load_config

parser = argparse.ArgumentParser()
parser.add_argument('--data_save_path', type=str,
                    help='path to saved data')
parser.add_argument('--model_path', type=str,
                    help='path to the model to evaluate')
parser.add_argument('--epoch', type=int, default=-1,
                    help='the epoch to restore')
parser.add_argument('--beam_width', type=int, default=1,
                    help='the size of beam')
parser.add_argument('--eval_batch_size', type=int, default=1,
                    help='the size of mini-batch in evaluation')

MAX_DECODE_LEN_WORD = 100
MAX_DECODE_LEN_CHAR = 300


def main():

    args = parser.parse_args()

    # Load a config file (.yml)
    params = load_config(join(args.model_path, 'config.yml'), is_eval=True)

    # Load dataset
    eval2000_swbd_data = Dataset(
        data_save_path=args.data_save_path,
        backend=params['backend'],
        input_freq=params['input_freq'],
        use_delta=params['use_delta'],
        use_double_delta=params['use_double_delta'],
        data_type='eval2000_swbd', data_size=params['data_size'],
        label_type=params['label_type'],
        batch_size=args.eval_batch_size, splice=params['splice'],
        num_stack=params['num_stack'], num_skip=params['num_skip'],
        sort_utt=False, tool=params['tool'])
    eval2000_ch_data = Dataset(
        data_save_path=args.data_save_path,
        backend=params['backend'],
        input_freq=params['input_freq'],
        use_delta=params['use_delta'],
        use_double_delta=params['use_double_delta'],
        data_type='eval2000_ch', data_size=params['data_size'],
        label_type=params['label_type'],
        batch_size=args.eval_batch_size, splice=params['splice'],
        num_stack=params['num_stack'], num_skip=params['num_skip'],
        sort_utt=False, tool=params['tool'])

    params['num_classes'] = eval2000_swbd_data.num_classes

    # Load model
    model = load(model_type=params['model_type'],
                 params=params,
                 backend=params['backend'])

    # Restore the saved parameters
    model.load_checkpoint(save_path=args.model_path, epoch=args.epoch)

    # GPU setting
    model.set_cuda(deterministic=False, benchmark=True)

    if 'word' in params['label_type']:
        wer_eval2000_swbd, df_wer_eval2000_swbd = eval_word(
            models=[model],
            dataset=eval2000_swbd_data,
            beam_width=args.beam_width,
            max_decode_len=MAX_DECODE_LEN_WORD,
            eval_batch_size=args.eval_batch_size,
            progressbar=True)
        print('  WER (SWB): %.3f %%' % (wer_eval2000_swbd * 100))
        print(df_wer_eval2000_swbd)

        wer_eval2000_ch, df_wer_eval2000_ch = eval_word(
            models=[model],
            dataset=eval2000_ch_data,
            beam_width=args.beam_width,
            max_decode_len=MAX_DECODE_LEN_WORD,
            eval_batch_size=args.eval_batch_size,
            progressbar=True)
        print('  WER (CHE): %.3f %%' % (wer_eval2000_ch * 100))
        print(df_wer_eval2000_ch)

        print('  WER (mean): %.3f %%' %
              ((wer_eval2000_swbd + wer_eval2000_ch) * 100 / 2))
    else:
        wer_eval2000_swbd, cer_eval2000_swbd, df_wer_cer_eval2000_swbd = eval_char(
            models=[model],
            dataset=eval2000_swbd_data,
            beam_width=args.beam_width,
            max_decode_len=MAX_DECODE_LEN_CHAR,
            eval_batch_size=args.eval_batch_size,
            progressbar=True)
        print(' WER / CER (SWB): %.3f / %.3f %%' %
              ((wer_eval2000_swbd * 100), (cer_eval2000_swbd * 100)))
        print(df_wer_cer_eval2000_swbd)

        wer_eval2000_ch, cer_eval2000_ch, df_wer_cer_eval2000_ch = eval_char(
            models=[model],
            dataset=eval2000_ch_data,
            beam_width=args.beam_width,
            max_decode_len=MAX_DECODE_LEN_CHAR,
            eval_batch_size=args.eval_batch_size,
            progressbar=True)
        print('  WER / CER (CHE): %.3f / %.3f %%' %
              ((wer_eval2000_ch * 100), (cer_eval2000_ch * 100)))
        print(df_wer_cer_eval2000_ch)

        print('  WER / CER (mean): %.3f / %.3f %%' %
              (((wer_eval2000_swbd + wer_eval2000_ch) * 100 / 2),
               ((cer_eval2000_swbd + cer_eval2000_ch) * 100 / 2)))


if __name__ == '__main__':
    main()
