#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Evaluate the trained model (TIMIT corpus)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import join, abspath
import sys
import yaml
import argparse

sys.path.append(abspath('../../../'))
from models.pytorch.load_model import load
from examples.timit.data.load_dataset_ctc import Dataset as Dataset_ctc
from examples.timit.data.load_dataset_attention import Dataset as Dataset_attention
from examples.timit.metrics.per import do_eval_per

parser = argparse.ArgumentParser()
parser.add_argument('--model_path', type=str,
                    help='path to the model to evaluate')
parser.add_argument('--epoch', type=int, default=-1,
                    help='the epoch to restore')
parser.add_argument('--beam_width', type=int, default=10,
                    help='beam_width (int, optional): beam width for beam search.' +
                    ' 1 disables beam search, which mean greedy decoding.')
parser.add_argument('--eval_batch_size', type=int, default=1,
                    help='the size of mini-batch in evaluation')
parser.add_argument('--max_decode_length', type=int, default=40,
                    help='the length of output sequences to stop prediction when EOS token have not been emitted')


def main():

    args = parser.parse_args()

    # Load config file
    with open(join(args.model_path, 'config.yml'), "r") as f:
        config = yaml.load(f)
        params = config['param']

    # Get voabulary number (excluding blank, <SOS>, <EOS> classes)
    with open('../metrics/vocab_num.yml', "r") as f:
        vocab_num = yaml.load(f)
        params['num_classes'] = vocab_num['phone39']

    # Model setting
    model = load(model_type=params['model_type'], params=params)

    # Load dataset
    if params['model_type'] == 'ctc':
        Dataset = Dataset_ctc
    elif params['model_type'] == 'attention':
        Dataset = Dataset_attention
    test_data = Dataset(
        data_type='test', label_type='phone39',
        num_classes=params['num_classes'],
        batch_size=args.eval_batch_size, splice=params['splice'],
        num_stack=params['num_stack'], num_skip=params['num_skip'],
        soft_utt=False)

    # GPU setting
    model.set_cuda(deterministic=False)

    # Load the saved model
    checkpoint = model.load_checkpoint(
        save_path=args.model_path, epoch=args.epoch)
    model.load_state_dict(checkpoint['state_dict'])

    # Change to evaluation mode
    model.eval()

    print('=== Test Data Evaluation ===')
    per_test = do_eval_per(
        model=model,
        model_type=params['model_type'],
        dataset=test_data,
        label_type=params['label_type'],
        beam_width=args.beam_width,
        max_decode_length=args.max_decode_length,
        progressbar=True)
    print('  PER: %f %%' % (per_test * 100))


if __name__ == '__main__':
    main()