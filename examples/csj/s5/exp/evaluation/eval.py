#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Evaluate the trained model (CSJ corpus)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import join, abspath
import sys
import argparse

sys.path.append(abspath('../../../'))
from models.load_model import load
from examples.csj.s5.exp.dataset.load_dataset import Dataset
from examples.csj.s5.exp.metrics.character import eval_char
from examples.csj.s5.exp.metrics.word import eval_word
from utils.config import load_config

parser = argparse.ArgumentParser()
parser.add_argument('--data_save_path', type=str,
                    help='path to saved data')
parser.add_argument('--model_path', type=str,
                    help='path to the model to evaluate')
parser.add_argument('--epoch', type=int, default=-1,
                    help='the epoch to restore')
parser.add_argument('--eval_batch_size', type=int, default=1,
                    help='the size of mini-batch in evaluation')
parser.add_argument('--beam_width', type=int, default=1,
                    help='the size of beam')
parser.add_argument('--length_penalty', type=float,
                    help='length penalty in beam search decodding')

MAX_DECODE_LEN_WORD = 100
MAX_DECODE_LEN_CHAR = 200


def main():

    args = parser.parse_args()

    # Load a config file (.yml)
    params = load_config(join(args.model_path, 'config.yml'), is_eval=True)

    wer_mean, cer_mean = 0, 0
    with open(join(args.model_path, 'RESULTS'), 'w') as f:
        for i, data_type in enumerate(['eval1', 'eval2', 'eval3']):
            # Load dataset
            eval_data = Dataset(
                data_save_path=args.data_save_path,
                backend=params['backend'],
                input_freq=params['input_freq'],
                use_delta=params['use_delta'],
                use_double_delta=params['use_double_delta'],
                data_type=data_type, data_size=params['data_size'],
                label_type=params['label_type'],
                batch_size=args.eval_batch_size, splice=params['splice'],
                num_stack=params['num_stack'], num_skip=params['num_skip'],
                shuffle=False, tool=params['tool'])

            if i == 0:
                params['num_classes'] = eval_data.num_classes

                # Load model
                model = load(model_type=params['model_type'],
                             params=params,
                             backend=params['backend'])

                # Restore the saved parameters
                model.load_checkpoint(
                    save_path=args.model_path, epoch=args.epoch)

                # GPU setting
                model.set_cuda(deterministic=False, benchmark=True)

            print('beam width: %d' % args.beam_width)
            f.write('beam width: %d\n' % args.beam_width)

            if params['label_type'] == 'word':
                wer, df = eval_word(
                    models=[model],
                    dataset=eval_data,
                    eval_batch_size=args.eval_batch_size,
                    beam_width=args.beam_width,
                    max_decode_len=MAX_DECODE_LEN_WORD,
                    length_penalty=args.length_penalty,
                    progressbar=True)
                wer_mean += wer
                print('  WER (%s): %.3f %%' % (data_type, (wer * 100)))
                f.write('  WER (%s): %.3f %%' % (data_type, (wer * 100)))
                print(df)
            else:
                wer, cer, df = eval_char(
                    models=[model],
                    dataset=eval_data,
                    eval_batch_size=args.eval_batch_size,
                    beam_width=args.beam_width,
                    max_decode_len=MAX_DECODE_LEN_CHAR,
                    length_penalty=args.length_penalty,
                    progressbar=True)
                wer_mean += wer
                cer_mean += cer
                print(' WER / CER (%s, sub): %.3f / %.3f %%' %
                      (data_type, (wer * 100), (cer * 100)))
                f.write(' WER / CER (%s, sub): %.3f / %.3f %%' %
                        (data_type, (wer * 100), (cer * 100)))
                print(df)

        if params['label_type'] == 'word':
            print('  WER (mean): %.3f %%' % (wer * 100 / 3))
            f.write('  WER (mean): %.3f %%' % (wer * 100 / 3))
        else:
            print('  WER / CER (mean): %.3f / %.3f %%' %
                  ((wer * 100 / 3), (cer * 100 / 3)))
            f.write('  WER / CER (mean): %.3f / %.3f %%' %
                    ((wer * 100 / 3), (cer * 100 / 3)))


if __name__ == '__main__':
    main()
