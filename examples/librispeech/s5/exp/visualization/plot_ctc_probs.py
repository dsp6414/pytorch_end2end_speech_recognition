#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Plot the CTC posteriors (Librispeech corpus)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os.path import join, abspath, isdir
import sys
import argparse
import shutil

sys.path.append(abspath('../../../'))
from models.load_model import load
from examples.librispeech.data.load_dataset import Dataset
from utils.io.labels.character import Idx2char
from utils.io.labels.word import Idx2word
from utils.directory import mkdir_join, mkdir
from utils.visualization.ctc import plot_ctc_probs
from utils.config import load_config

parser = argparse.ArgumentParser()
parser.add_argument('--model_path', type=str,
                    help='path to the model to evaluate')
parser.add_argument('--epoch', type=int, default=-1,
                    help='the epoch to restore')
parser.add_argument('--eval_batch_size', type=int, default=1,
                    help='the size of mini-batch in evaluation')


def main():

    args = parser.parse_args()

    # Load a config file (.yml)
    params = load_config(join(args.model_path, 'config.yml'), is_eval=True)

    # Load dataset
    vocab_file_path = '../metrics/vocab_files/' + \
        params['label_type'] + '_' + params['data_size'] + '.txt'
    test_data = Dataset(
        backend=params['backend'],
        input_channel=params['input_channel'],
        use_delta=params['use_delta'],
        use_double_delta=params['use_double_delta'],
        data_type='test_clean',
        # data_type='test_other',
        data_size=params['data_size'],
        label_type=params['label_type'], vocab_file_path=vocab_file_path,
        batch_size=args.eval_batch_size, splice=params['splice'],
        num_stack=params['num_stack'], num_skip=params['num_skip'],
        sort_utt=True, reverse=False, save_format=params['save_format'])
    params['num_classes'] = test_data.num_classes

    # Load model
    model = load(model_type=params['model_type'],
                 params=params,
                 backend=params['backend'])

    # Restore the saved parameters
    model.load_checkpoint(save_path=args.model_path, epoch=args.epoch)

    # GPU setting
    model.set_cuda(deterministic=False, benchmark=True)

    space_index = 27 if params['label_type'] == 'character' else None
    # NOTE: index 0 is reserved for blank in warpctc_pytorch

    # Visualize
    plot(model=model,
         dataset=test_data,
         eval_batch_size=args.eval_batch_size,
         save_path=mkdir_join(args.model_path, 'ctc_probs'),
         space_index=space_index)


def plot(model, dataset, eval_batch_size=None, save_path=None,
         space_index=None):
    """
    Args:
        model: the model to evaluate
        dataset: An instance of a `Dataset` class
        eval_batch_size (int, optional): the batch size when evaluating the model
        save_path (string): path to save figures of CTC posteriors
        space_index (int, optional):
    """
    # Set batch size in the evaluation
    if eval_batch_size is not None:
        dataset.batch_size = eval_batch_size

    # Clean directory
    if isdir(save_path):
        shutil.rmtree(save_path)
        mkdir(save_path)

    vocab_file_path = '../metrics/vocab_files/' + \
        dataset.label_type + '_' + dataset.data_size + '.txt'
    if dataset.label_type == 'character':
        map_fn = Idx2char(vocab_file_path)
    elif dataset.label_type == 'character_capital_divide':
        map_fn = Idx2char(vocab_file_path, capital_divide=True)
    else:
        map_fn = Idx2word(vocab_file_path)

    for batch, is_new_epoch in dataset:

        # Get CTC probs
        probs = model.posteriors(batch['xs'], batch['x_lens'], temperature=1)
        # NOTE: probs: '[B, T, num_classes]'

        # Decode
        best_hyps _ = model.decode(batch['xs'], batch['x_lens'], beam_width=1)

        # Visualize
        for b in range(len(batch['xs'])):

            # Convert from list of index to string
            str_pred = map_fn(best_hyps[b])

            speaker, book = batch['input_names'][b].split('-')[:2]
            plot_ctc_probs(
                probs[b, :batch['x_lens'][b], :],
                frame_num=batch['x_lens'][b],
                num_stack=dataset.num_stack,
                space_index=space_index,
                str_pred=str_pred,
                save_path=mkdir_join(save_path, speaker, book, batch['input_names'][b] + '.png'))

        if is_new_epoch:
            break


if __name__ == '__main__':
    main()
