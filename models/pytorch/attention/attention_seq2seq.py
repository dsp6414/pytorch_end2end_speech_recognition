#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Attention-based sequence-to-sequence model (pytorch)."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import numpy as np
import copy
import torch
import torch.nn.functional as F

from models.pytorch.base import ModelBase
from models.pytorch.linear import LinearND, Embedding, Embedding_LS
from models.pytorch.encoders.load_encoder import load
from models.pytorch.attention.rnn_decoder import RNNDecoder
from models.pytorch.attention.attention_layer import AttentionMechanism
from models.pytorch.ctc.ctc import _concatenate_labels, my_warpctc
from models.pytorch.criterion import cross_entropy_label_smoothing
from models.pytorch.ctc.decoders.greedy_decoder import GreedyDecoder
from models.pytorch.ctc.decoders.beam_search_decoder import BeamSearchDecoder

LOG_1 = 0


class AttentionSeq2seq(ModelBase):
    """Attention-based sequence-to-sequence model.
    Args:
        input_size (int): the dimension of input features (freq * channel)
        encoder_type (string): the type of the encoder. Set lstm or gru or rnn.
        encoder_bidirectional (bool): if True, create a bidirectional encoder
        encoder_num_units (int): the number of units in each layer of the encoder
        encoder_num_proj (int): the number of nodes in the projection layer of the encoder
        encoder_num_layers (int): the number of layers of the encoder
        attention_type (string): the type of attention
        attention_dim: (int) the dimension of the attention layer
        decoder_type (string): lstm or gru
        decoder_num_units (int): the number of units in each layer of the decoder
        decoder_num_layers (int): the number of layers of the decoder
        embedding_dim (int): the dimension of the embedding in target spaces.
            0 means that decoder inputs are represented by one-hot vectors.
        dropout_input (float): the probability to drop nodes in input-hidden connection
        dropout_encoder (float): the probability to drop nodes in hidden-hidden
            connection of the encoder
        dropout_decoder (float): the probability to drop nodes of the decoder
        dropout_embedding (float): the probability to drop nodes of the embedding layer
        num_classes (int): the number of nodes in softmax layer
            (excluding <SOS> and <EOS> classes)
        parameter_init_distribution (string, optional): uniform or normal or
            orthogonal or constant distribution
        parameter_init (float, optional): Range of uniform distribution to
            initialize weight parameters
        recurrent_weight_orthogonal (bool, optional): if True, recurrent
            weights are orthogonalized
        init_forget_gate_bias_with_one (bool, optional): if True, initialize
            the forget gate bias with 1
        subsample_list (list, optional): subsample in the corresponding layers (True)
            ex.) [False, True, True, False] means that subsample is conducted
                in the 2nd and 3rd layers.
        subsample_type (string, optional): drop or concat
        bridge_layer (bool, optional): if True, add the bridge layer between
            the encoder and decoder
        init_dec_state (bool, optional): how to initialize decoder state
            zero => initialize with zero state
            mean => initialize with the mean of encoder outputs in all time steps
            final => initialize with tha final encoder state
            first => initialize with tha first encoder state
        sharpening_factor (float, optional): a sharpening factor in the
            softmax layer for computing attention weights
        logits_temperature (float, optional): a parameter for smoothing the
            softmax layer in outputing probabilities
        sigmoid_smoothing (bool, optional): if True, replace softmax function
            in computing attention weights with sigmoid function for smoothing
        coverage_weight (float, optional): the weight parameter for coverage computation
        ctc_loss_weight (float): A weight parameter for auxiliary CTC loss
        attention_conv_num_channels (int, optional): the number of channles of
            conv outputs. This is used for location-based attention.
        attention_conv_width (int, optional): the size of kernel.
            This must be the odd number.
        num_stack (int, optional): the number of frames to stack
        splice (int, optional): frames to splice. Default is 1 frame.
        input_channel (int, optional): the number of channels of input features
        conv_channels (list, optional): the number of channles in the
            convolution of the location-based attention
        conv_kernel_sizes (list, optional): the size of kernels in the
            convolution of the location-based attention
        conv_strides (list, optional): strides in the convolution
            of the location-based attention
        poolings (list, optional): the size of poolings in the convolution
            of the location-based attention
        activation (string, optional): The activation function of CNN layers.
            Choose from relu or prelu or hard_tanh or maxout
        batch_norm (bool, optional):
        scheduled_sampling_prob (float, optional):
        scheduled_sampling_max_step (float, optional):
        label_smoothing_prob (float, optional):
        weight_noise_std (flaot, optional):
        encoder_residual (bool, optional):
        encoder_dense_residual (bool, optional):
        decoder_residual (bool, optional):
        decoder_dense_residual (bool, optional):
        decoding_order (string, optional):
            attend_update_generate or attend_generate_update or conditional
        bottleneck_dim (int, optional): the dimension of the pre-softmax layer
        backward_loss_weight (int, optional): A weight parameter for the loss of the backward decdoer,
            where the model predicts each token in the reverse order
        num_heads (int, optional): the number of heads in the multi-head attention
    """

    def __init__(self,
                 input_size,
                 encoder_type,
                 encoder_bidirectional,
                 encoder_num_units,
                 encoder_num_proj,
                 encoder_num_layers,
                 attention_type,
                 attention_dim,
                 decoder_type,
                 decoder_num_units,
                 decoder_num_layers,
                 embedding_dim,
                 dropout_input,
                 dropout_encoder,
                 dropout_decoder,
                 dropout_embedding,
                 num_classes,
                 parameter_init_distribution='uniform',
                 parameter_init=0.1,
                 recurrent_weight_orthogonal=False,
                 init_forget_gate_bias_with_one=True,
                 subsample_list=[],
                 subsample_type='drop',
                 bridge_layer=False,
                 init_dec_state='first',
                 sharpening_factor=1,
                 logits_temperature=1,
                 sigmoid_smoothing=False,
                 coverage_weight=0,
                 ctc_loss_weight=0,
                 attention_conv_num_channels=10,
                 attention_conv_width=201,
                 num_stack=1,
                 splice=1,
                 input_channel=1,
                 conv_channels=[],
                 conv_kernel_sizes=[],
                 conv_strides=[],
                 poolings=[],
                 activation='relu',
                 batch_norm=False,
                 scheduled_sampling_prob=0,
                 scheduled_sampling_max_step=0,
                 label_smoothing_prob=0,
                 weight_noise_std=0,
                 encoder_residual=False,
                 encoder_dense_residual=False,
                 decoder_residual=False,
                 decoder_dense_residual=False,
                 decoding_order='attend_generate_update',
                 bottleneck_dim=256,
                 backward_loss_weight=0,
                 num_heads=1):

        super(ModelBase, self).__init__()
        self.model_type = 'attention'

        # Setting for the encoder
        self.input_size = input_size
        self.num_stack = num_stack
        self.encoder_type = encoder_type
        self.encoder_num_units = encoder_num_units
        if encoder_bidirectional:
            self.encoder_num_units *= 2
        self.encoder_num_proj = encoder_num_proj
        self.encoder_num_layers = encoder_num_layers
        self.subsample_list = subsample_list

        # Setting for the decoder
        self.decoder_type = decoder_type
        self.decoder_num_units_0 = decoder_num_units
        self.decoder_num_layers_0 = decoder_num_layers
        self.embedding_dim = embedding_dim
        self.num_classes = num_classes + 1  # Add <EOS> class
        self.sos_0 = num_classes
        self.eos_0 = num_classes
        # NOTE: <SOS> and <EOS> have the same index
        self.decoding_order = decoding_order
        assert 0 <= backward_loss_weight <= 1
        self.fwd_weight_0 = 1 - backward_loss_weight
        self.bwd_weight_0 = backward_loss_weight

        # Setting for the decoder initialization
        if init_dec_state not in ['zero', 'mean', 'final', 'first']:
            raise ValueError(
                'init_dec_state must be "zero" or "mean" or "final" or "first".')
        self.init_dec_state_0_fwd = init_dec_state
        self.init_dec_state_0_bwd = init_dec_state
        if backward_loss_weight > 0:
            if init_dec_state == 'first':
                self.init_dec_state_0_bwd = 'final'
            elif init_dec_state == 'final':
                self.init_dec_state_0_bwd = 'first'
        if encoder_type != decoder_type:
            self.init_dec_state_0_fwd = 'zero'
            self.init_dec_state_0_bwd = 'zero'

        # Setting for the attention
        self.sharpening_factor = sharpening_factor
        self.logits_temperature = logits_temperature
        self.sigmoid_smoothing = sigmoid_smoothing
        self.coverage_weight = coverage_weight
        self.num_heads_0 = num_heads

        # Setting for regularization
        self.weight_noise_injection = False
        self.weight_noise_std = float(weight_noise_std)
        if scheduled_sampling_prob > 0 and scheduled_sampling_max_step == 0:
            raise ValueError
        self.ss_prob = scheduled_sampling_prob
        self._ss_prob = scheduled_sampling_prob
        self.ss_max_step = scheduled_sampling_max_step
        self._step = 0
        self.ls_prob = label_smoothing_prob

        # Setting for MTL
        self.ctc_loss_weight = ctc_loss_weight

        ##############################
        # Encoder
        ##############################
        if encoder_type in ['lstm', 'gru', 'rnn']:
            self.encoder = load(encoder_type=encoder_type)(
                input_size=input_size,
                rnn_type=encoder_type,
                bidirectional=encoder_bidirectional,
                num_units=encoder_num_units,
                num_proj=encoder_num_proj,
                num_layers=encoder_num_layers,
                dropout_input=dropout_input,
                dropout_hidden=dropout_encoder,
                subsample_list=subsample_list,
                subsample_type=subsample_type,
                batch_first=True,
                merge_bidirectional=False,
                pack_sequence=True,
                num_stack=num_stack,
                splice=splice,
                input_channel=input_channel,
                conv_channels=conv_channels,
                conv_kernel_sizes=conv_kernel_sizes,
                conv_strides=conv_strides,
                poolings=poolings,
                activation=activation,
                batch_norm=batch_norm,
                residual=encoder_residual,
                dense_residual=encoder_dense_residual,
                nin=0)
        elif encoder_type == 'cnn':
            assert num_stack == 1 and splice == 1
            self.encoder = load(encoder_type='cnn')(
                input_size=input_size,
                input_channel=input_channel,
                conv_channels=conv_channels,
                conv_kernel_sizes=conv_kernel_sizes,
                conv_strides=conv_strides,
                poolings=poolings,
                dropout_input=dropout_input,
                dropout_hidden=dropout_encoder,
                activation=activation,
                batch_norm=batch_norm)
            self.init_dec_state_0 = 'zero'
        else:
            raise NotImplementedError

        ##################################################
        # Bridge layer between the encoder and decoder
        ##################################################
        if encoder_type == 'cnn':
            self.bridge_0 = LinearND(
                self.encoder.output_size, decoder_num_units,
                dropout=dropout_encoder)
            self.encoder_num_units = decoder_num_units
            self.is_bridge = True
        elif bridge_layer:
            self.bridge_0 = LinearND(self.encoder_num_units, decoder_num_units,
                                     dropout=dropout_encoder)
            self.encoder_num_units = decoder_num_units
            self.is_bridge = True
        else:
            self.is_bridge = False

        directions = []
        if self.fwd_weight_0 > 0:
            directions.append('fwd')
        if self.bwd_weight_0 > 0:
            directions.append('bwd')
        for dir in directions:
            ##################################################
            # Initialization of the decoder
            ##################################################
            if getattr(self, 'init_dec_state_0_' + dir) != 'zero':
                setattr(self, 'W_dec_init_0_' + dir, LinearND(
                    self.encoder_num_units, decoder_num_units))

            ##############################
            # Decoder
            ##############################
            if decoding_order == 'conditional':
                setattr(self, 'decoder_first_0_' + dir, RNNDecoder(
                    input_size=embedding_dim,
                    rnn_type=decoder_type,
                    num_units=decoder_num_units,
                    num_layers=1,
                    dropout=dropout_decoder,
                    residual=False,
                    dense_residual=False))
                setattr(self, 'decoder_second_0_' + dir, RNNDecoder(
                    input_size=self.encoder_num_units,
                    rnn_type=decoder_type,
                    num_units=decoder_num_units,
                    num_layers=1,
                    dropout=dropout_decoder,
                    residual=False,
                    dense_residual=False))
                # NOTE; the conditional decoder only supports the 1 layer
            else:
                setattr(self, 'decoder_0_' + dir, RNNDecoder(
                    input_size=self.encoder_num_units + embedding_dim,
                    rnn_type=decoder_type,
                    num_units=decoder_num_units,
                    num_layers=decoder_num_layers,
                    dropout=dropout_decoder,
                    residual=decoder_residual,
                    dense_residual=decoder_dense_residual))

            ##############################
            # Attention layer
            ##############################
            setattr(self, 'attend_0_' + dir, AttentionMechanism(
                encoder_num_units=self.encoder_num_units,
                decoder_num_units=decoder_num_units,
                attention_type=attention_type,
                attention_dim=attention_dim,
                sharpening_factor=sharpening_factor,
                sigmoid_smoothing=sigmoid_smoothing,
                out_channels=attention_conv_num_channels,
                kernel_size=attention_conv_width,
                num_heads=num_heads))

            ##############################
            # Output layer
            ##############################
            setattr(self, 'W_d_0_' + dir, LinearND(
                decoder_num_units, bottleneck_dim,
                dropout=dropout_decoder))
            setattr(self, 'W_c_0_' + dir, LinearND(
                self.encoder_num_units, bottleneck_dim,
                dropout=dropout_decoder))
            setattr(self, 'fc_0_' + dir,
                    LinearND(bottleneck_dim, self.num_classes))

        ##############################
        # Embedding
        ##############################
        if label_smoothing_prob > 0:
            self.embed_0 = Embedding_LS(
                num_classes=self.num_classes,
                embedding_dim=embedding_dim,
                dropout=dropout_embedding,
                label_smoothing_prob=label_smoothing_prob)
        else:
            self.embed_0 = Embedding(
                num_classes=self.num_classes,
                embedding_dim=embedding_dim,
                dropout=dropout_embedding)

        ##############################
        # CTC
        ##############################
        if ctc_loss_weight > 0:
            if self.is_bridge:
                self.fc_ctc_0 = LinearND(
                    decoder_num_units, num_classes + 1)
            else:
                self.fc_ctc_0 = LinearND(
                    self.encoder_num_units, num_classes + 1)

            # Set CTC decoders
            self._decode_ctc_greedy_np = GreedyDecoder(blank_index=0)
            self._decode_ctc_beam_np = BeamSearchDecoder(blank_index=0)
            # TODO: set space index

        ##################################################
        # Initialize parameters
        ##################################################
        self.init_weights(parameter_init,
                          distribution=parameter_init_distribution,
                          ignore_keys=['bias'])

        # Initialize all biases with 0
        self.init_weights(0, distribution='constant', keys=['bias'])

        # Recurrent weights are orthogonalized
        if recurrent_weight_orthogonal:
            if encoder_type != 'cnn':
                self.init_weights(parameter_init,
                                  distribution='orthogonal',
                                  keys=[encoder_type, 'weight'],
                                  ignore_keys=['bias'])
            self.init_weights(parameter_init,
                              distribution='orthogonal',
                              keys=[decoder_type, 'weight'],
                              ignore_keys=['bias'])

        # Initialize bias in forget gate with 1
        if init_forget_gate_bias_with_one:
            self.init_forget_gate_bias_with_one()

    def forward(self, xs, ys, x_lens, y_lens, is_eval=False):
        """Forward computation.
        Args:
            xs (np.ndarray): A tensor of size `[B, T_in, input_size]`
            ys (np.ndarray): A tensor of size `[B, T_out]`, which should be padded with -1.
            x_lens (np.ndarray): A tensor of size `[B]`
            y_lens (np.ndarray): A tensor of size `[B]`
            is_eval (bool): if True, the history will not be saved.
                This should be used in inference model for memory efficiency.
        Returns:
            loss (torch.FloatTensor or float): A tensor of size `[]`
        """
        if is_eval:
            self.eval()
            with torch.no_grad():
                loss = self._forward(xs, ys, x_lens, y_lens).item()
        else:
            self.train()

            # Gaussian noise injection
            if self.weight_noise_injection:
                self.inject_weight_noise(mean=0, std=self.weight_noise_std)

            loss = self._forward(xs, ys, x_lens, y_lens)

            # Update the probability of scheduled sampling
            self._step += 1
            if self.ss_prob > 0:
                self._ss_prob = min(
                    self.ss_prob, self.ss_prob / self.ss_max_step * self._step)

        return loss

    def _forward(self, xs, ys, x_lens, y_lens):
        # Wrap by Tensor
        xs = self.np2tensor(xs, dtype=torch.float)
        x_lens = self.np2tensor(x_lens, dtype=torch.int)

        # Encode acoustic features
        xs, x_lens, perm_idx = self._encode(xs, x_lens)

        ##################################################
        # Compute loss for the forward decoder
        ##################################################
        if self.fwd_weight_0 > 0:
            # NOTE: ys is padded with -1 here
            # ys_in_fwd is padded with <EOS> in order to convert to one-hot vector,
            # and added <SOS> before the first token
            # ys_out_fwd is padded with -1, and added <EOS> after the last token
            ys_in_fwd = self._create_tensor((ys.shape[0], ys.shape[1] + 1),
                                            fill_value=self.eos_0, dtype=torch.long)
            ys_out_fwd = self._create_tensor((ys.shape[0], ys.shape[1] + 1),
                                             fill_value=-1, dtype=torch.long)

            ys_in_fwd[:, 0] = self.sos_0
            for b in range(len(xs)):
                ys_in_fwd[b, 1:y_lens[b] + 1] = torch.from_numpy(
                    ys[b, :y_lens[b]])
                ys_out_fwd[b, :y_lens[b]] = torch.from_numpy(ys[b, :y_lens[b]])
                ys_out_fwd[b, y_lens[b]] = self.eos_0

            # Wrap by Tensor
            y_lens_fwd = self.np2tensor(y_lens, dtype=torch.int)

            # Permutate indices
            ys_in_fwd = ys_in_fwd[perm_idx]
            ys_out_fwd = ys_out_fwd[perm_idx]
            y_lens_fwd = y_lens_fwd[perm_idx]

            # Compute XE loss
            loss = self.compute_xe_loss(
                xs, ys_in_fwd, ys_out_fwd, x_lens, y_lens_fwd,
                task=0, dir='fwd') * self.fwd_weight_0
        else:
            loss = self._create_tensor((1,), fill_value=0, dtype=torch.float)

        ##################################################
        # Compute loss for the backward decoder
        ##################################################
        if self.bwd_weight_0 > 0:
            # Reverse the order
            ys_tmp = copy.deepcopy(ys)
            for b in range(len(xs)):
                ys_tmp[b, :y_lens[b]] = ys[b, :y_lens[b]][::-1]

            ys_in_bwd = self._create_tensor((ys.shape[0], ys.shape[1] + 1),
                                            fill_value=self.eos_0, dtype=torch.long)
            ys_out_bwd = self._create_tensor((ys.shape[0], ys.shape[1] + 1),
                                             fill_value=-1, dtype=torch.long)

            ys_in_bwd[:, 0] = self.sos_0
            for b in range(len(xs)):
                ys_in_bwd[b, 1:y_lens[b] + 1] = torch.from_numpy(
                    ys_tmp[b, :y_lens[b]])
                ys_out_bwd[b, :y_lens[b]] = torch.from_numpy(
                    ys_tmp[b, :y_lens[b]])
                ys_out_bwd[b, y_lens[b]] = self.eos_0

            # Wrap by Tensor
            y_lens_bwd = self.np2tensor(y_lens, dtype=torch.int)

            # Permutate indices
            ys_in_bwd = ys_in_bwd[perm_idx]
            ys_out_bwd = ys_out_bwd[perm_idx]
            y_lens_bwd = y_lens_bwd[perm_idx]

            # Compute XE loss
            loss += self.compute_xe_loss(
                xs, ys_in_bwd, ys_out_bwd, x_lens, y_lens_bwd,
                task=0, dir='bwd') * self.bwd_weight_0

        ##################################################
        # Auxiliary CTC loss (optional)
        ##################################################
        if self.ctc_loss_weight > 0:
            # Wrap by Tensor
            ys_ctc = self.np2tensor(ys, dtype=torch.long)
            y_lens_ctc = self.np2tensor(y_lens, dtype=torch.int)

            # Permutate indices
            ys_ctc = ys_ctc[perm_idx]
            y_lens_ctc = y_lens_ctc[perm_idx]

            loss += self.compute_ctc_loss(
                xs, ys_ctc + 1,
                x_lens, y_lens_ctc) * self.ctc_loss_weight
            # NOTE: exclude <SOS>
            # NOTE: index 0 is reserved for blank in warpctc_pytorch

        return loss

    def compute_xe_loss(self, enc_out, ys_in, ys_out, x_lens, y_lens,
                        task, dir):
        """Compute XE loss.
        Args:
            enc_out (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            ys_in (torch.LongTensor): A tensor of size
                `[B, T_out]`, which includes <SOS>
            ys_out (torch.LongTensor): A tensor of size
                `[B, T_out]`, which includes <EOS>
            x_lens (torch.IntTensor): A tensor of size `[B]`
            y_lens (torch.IntTensor): A tensor of size `[B]`
            task (int): the index of a task
            dir (str): fwd or bwd
        Returns:
            loss (torch.FloatTensor): A tensor of size `[]`
        """
        # Teacher-forcing
        logits, aw = self._decode_train(enc_out, x_lens, ys_in, task, dir)

        # Output smoothing
        if self.logits_temperature != 1:
            logits /= self.logits_temperature

        # Compute XE sequence loss
        loss = F.cross_entropy(
            input=logits.view((-1, logits.size(2))),
            target=ys_out.view(-1),
            ignore_index=-1, size_average=False) / len(enc_out)

        # Label smoothing (with uniform distribution)
        if self.ls_prob > 0:
            loss_ls = cross_entropy_label_smoothing(
                logits,
                y_lens=y_lens + 1,  # Add <EOS>
                label_smoothing_prob=self.ls_prob,
                distribution='uniform',
                size_average=True)
            loss = loss * (1 - self.ls_prob) + loss_ls

        # Add coverage term
        if self.coverage_weight != 0:
            raise NotImplementedError

        return loss

    def compute_ctc_loss(self, enc_out, ys, x_lens, y_lens, task=0):
        """Compute CTC loss.
        Args:
            enc_out (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            ys (torch.LongTensor): A tensor of size `[B, T_out]`,
                which includes <SOS> nor <EOS>
            x_lens (torch.IntTensor): A tensor of size `[B]`
            y_lens (torch.IntTensor): A tensor of size `[B]`,
                which includes <SOS> nor <EOS>
            task (int, optional): the index of a task
        Returns:
            loss (torch.FloatTensor): A tensor of size `[]`
        """
        # Concatenate all _ys for warpctc_pytorch
        # `[B, T_out]` -> `[1,]`
        concatenated_labels = _concatenate_labels(ys, y_lens)

        # Path through the fully-connected layer
        logits = getattr(self, 'fc_ctc_' + str(task))(enc_out)

        # Compute CTC loss
        loss = my_warpctc(logits.transpose(0, 1),  # time-major
                          concatenated_labels.cpu(),
                          x_lens.cpu(),
                          y_lens.cpu(),
                          size_average=False).to(self.device)

        # Label smoothing (with uniform distribution)
        # if self.ls_prob > 0:
        #     # XE
        #     loss_ls = cross_entropy_label_smoothing(
        #         logits,
        #         y_lens=x_lens,  # NOTE: CTC is frame-synchronous
        #         label_smoothing_prob=self.ls_prob,
        #         distribution='uniform',
        #         size_average=False)
        #     loss = loss * (1 - self.ls_prob) + loss_ls

        loss /= len(enc_out)

        return loss.sum()
        # NOTE: to convert to 0-dim tensor

    def _encode(self, xs, x_lens, is_multi_task=False):
        """Encode acoustic features.
        Args:
            xs (torch.FloatTensor): A tensor of size
                `[B, T_in, input_size]`
            x_lens (torch.IntTensor): A tensor of size `[B]`
            is_multi_task (bool, optional):
        Returns:
            xs (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            x_lens (torch.IntTensor): A tensor of size `[B]`
            OPTION:
                xs_sub (torch.FloatTensor): A tensor of size
                    `[B, T_in, encoder_num_units]`
                x_lens_sub (torch.IntTensor): A tensor of size `[B]`
            perm_idx (torch.LongTensor): A tensor of size `[B]`
        """
        if is_multi_task:
            if self.encoder_type == 'cnn':
                xs, x_lens, perm_idx = self.encoder(xs, x_lens)
                xs_sub = xs.clone()
                x_lens_sub = x_lens.clone()
            else:
                xs, x_lens, xs_sub, x_lens_sub, perm_idx = self.encoder(
                    xs, x_lens)
        else:
            xs, x_lens, perm_idx = self.encoder(xs, x_lens)

        # Bridge between the encoder and decoder in the main task
        if self.is_bridge:
            xs = self.bridge_0(xs)
        if is_multi_task and self.is_bridge_sub:
            xs_sub = self.bridge_1(xs_sub)

        if is_multi_task:
            return xs, x_lens, xs_sub, x_lens_sub, perm_idx
        else:
            return xs, x_lens, perm_idx

    def _compute_coverage(self, aw):
        batch_size, max_time_out, max_time_in = aw.size()
        raise NotImplementedError

    def _decode_train(self, enc_out, x_lens, ys, task, dir):
        """Decoding in the training stage.
        Args:
            enc_out (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            x_lens (torch.IntTensor): A tensor of size `[B]`
            ys (torch.LongTensor): A tensor of size `[B, T_out]`,
                which should be padded with <EOS>.
            task (int): the index of a task
            dir (str): fwd or bwd
        Returns:
            logits (torch.FloatTensor): A tensor of size
                `[B, T_out, num_classes]`
            aw (torch.FloatTensor): A tensor of size
                `[B, T_out, T_in, num_heads]`
        """
        batch_size, max_time = enc_out.size()[:2]

        # Initialize decoder state, decoder output, attention_weights
        dec_state, dec_out = self._init_dec_state(enc_out, x_lens, task, dir)
        aw_step = self._create_tensor(
            (batch_size, max_time, getattr(self, 'num_heads_' + str(task))),
            fill_value=0, dtype=torch.float)

        logits, aw = [], []
        for t in range(ys.size(1)):
            # for scheduled sampling
            is_sample = self.ss_prob > 0 and t > 0 and self._step > 0 and random.random(
            ) < self._ss_prob

            if self.decoding_order == 'attend_generate_update':
                # Score
                context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                    enc_out, x_lens, dec_out, aw_step)

                # Generate
                logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                    getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                    getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

                if t < ys.size(1) - 1:
                    # Sample
                    y = torch.max(
                        logits_step, dim=2)[1].detach() if is_sample else ys[:, t + 1:t + 2]
                    # NOTE; detach from history as input
                    y = getattr(self, 'embed_' + str(task))(y)

                    # Recurrency
                    dec_in = torch.cat([y, context_vec], dim=-1)
                    dec_out, dec_state = getattr(
                        self, 'decoder_' + str(task) + '_' + dir)(dec_in, dec_state)

            elif self.decoding_order == 'attend_update_generate':
                # Score
                context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                    enc_out, x_lens, dec_out, aw_step)

                # Sample
                y = torch.max(
                    logits[-1], dim=2)[1].detach() if is_sample else ys[:, t:t + 1]
                # NOTE; detach from history as input
                y = getattr(self, 'embed_' + str(task))(y)

                # Recurrency
                dec_in = torch.cat([y, context_vec], dim=-1)
                dec_out, dec_state = getattr(
                    self, 'decoder_' + str(task) + '_' + dir)(dec_in, dec_state)

                # Generate
                logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                    getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                    getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

            elif self.decoding_order == 'conditional':
                # Sample
                y = torch.max(
                    logits[-1], dim=2)[1].detach() if is_sample else ys[:, t:t + 1]
                # NOTE; detach from history as input
                y = getattr(self, 'embed_' + str(task))(y)

                # Recurrency of the first decoder
                _dec_out, _dec_state = getattr(self, 'decoder_first_' + str(task) + '_' + dir)(
                    y, dec_state)

                # Score
                context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                    enc_out, x_lens, _dec_out, aw_step)

                # Recurrency of the second decoder
                dec_out, dec_state = getattr(self, 'decoder_second_' + str(task) + '_' + dir)(
                    context_vec, _dec_state)

                # Generate
                logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                    getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                    getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

            logits.append(logits_step)
            aw.append(aw_step)

        # Concatenate in T_out-dimension
        logits = torch.cat(logits, dim=1)
        aw = torch.stack(aw, dim=1)
        # NOTE; aw in the training stage may be used for computing the
        # coverage, so do not convert to numpy yet.

        return logits, aw

    def _init_dec_state(self, enc_out, x_lens, task, dir):
        """Initialize decoder state.
        Args:
            enc_out (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            x_lens (torch.IntTensor): A tensor of size `[B]`
            task (int): the index of a task
            dir (str): fwd or bwd
        Returns:
            dec_state (list or tuple of list):
            dec_out (torch.FloatTensor): A tensor of size
                `[B, 1, decoder_num_units]`
        """
        zero_state = self._create_tensor((enc_out.size(0), getattr(
            self, 'decoder_num_units_' + str(task))),
            fill_value=0, dtype=torch.float)

        if getattr(self, 'init_dec_state_' + str(task) + '_' + dir) == 'zero':
            if self.decoder_type == 'lstm':
                hx_list = [zero_state] * \
                    getattr(self, 'decoder_num_layers_' + str(task))
                cx_list = [zero_state] * \
                    getattr(self, 'decoder_num_layers_' + str(task))
            else:
                hx_list = [zero_state] * \
                    getattr(self, 'decoder_num_layers_' + str(task))

            dec_out = self._create_tensor((enc_out.size(0), 1, getattr(
                self, 'decoder_num_units_' + str(task))),
                fill_value=0, dtype=torch.float)
        else:
            # TODO: consider x_lens

            if getattr(self, 'init_dec_state_' + str(task) + '_' + dir) == 'mean':
                # Initialize with mean of all encoder outputs
                h_0 = enc_out.mean(dim=1, keepdim=False)
            elif getattr(self, 'init_dec_state_' + str(task) + '_' + dir) == 'final':
                # Initialize with the final encoder output
                h_0 = enc_out[:, -1, :]
            elif getattr(self, 'init_dec_state_' + str(task) + '_' + dir) == 'first':
                # Initialize with the first encoder output
                h_0 = enc_out[:, 0, :]
            # NOTE: h_0: `[B, encoder_num_units]`

            # Path through the linear layer
            h_0 = F.tanh(getattr(self, 'W_dec_init_' +
                                 str(task) + '_' + dir)(h_0))

            hx_list = [h_0] * \
                getattr(self, 'decoder_num_layers_' + str(task))
            # NOTE: all layers are initialized with the same values

            if self.decoder_type == 'lstm':
                cx_list = [zero_state] * \
                    getattr(self, 'decoder_num_layers_' + str(task))

            dec_out = h_0.unsqueeze(1)

        if self.decoder_type == 'lstm':
            dec_state = (hx_list, cx_list)
        else:
            dec_state = hx_list

        return dec_state, dec_out

    def decode(self, xs, x_lens, beam_width, max_decode_len,
               length_penalty=0, coverage_penalty=0, task_index=0,
               resolving_unk=False):
        """Decoding in the inference stage.
        Args:
            xs (np.ndarray): A tensor of size `[B, T_in, input_size]`
            x_lens (np.ndarray): A tensor of size `[B]`
            beam_width (int): the size of beam
            max_decode_len (int): the length of output sequences
                to stop prediction when EOS token have not been emitted
            length_penalty (float, optional):
            coverage_penalty (float, optional):
            task_index (int, optional): not used (to make compatible)
            resolving_unk (bool, optional): not used (to make compatible)
        Returns:
            best_hyps (np.ndarray): A tensor of size `[B]`
            # aw (np.ndarray): A tensor of size `[B, T_out, T_in, num_heads]`
            aw (np.ndarray): A tensor of size `[B, T_out, T_in]`
            perm_idx (np.ndarray): A tensor of size `[B]`
        """
        self.eval()
        with torch.no_grad():
            # Wrap by Tensor
            xs = self.np2tensor(xs, dtype=torch.float)
            x_lens = self.np2tensor(x_lens, dtype=torch.int)

            # Encode acoustic features
            enc_out, x_lens, perm_idx = self._encode(xs, x_lens)

            dir = 'fwd'if self.fwd_weight_0 >= self.bwd_weight_0 else 'bwd'

            if beam_width == 1:
                best_hyps, aw = self._decode_infer_greedy(
                    enc_out, x_lens, max_decode_len, task=0, dir=dir)
            else:
                best_hyps, aw = self._decode_infer_beam(
                    enc_out, x_lens, beam_width, max_decode_len,
                    length_penalty, coverage_penalty, task=0, dir=dir)

        # TODO: fix this
        if beam_width == 1:
            aw = aw[:, :, :, 0]

        # Permutate indices to the original order
        perm_idx = self.tensor2np(perm_idx)

        return best_hyps, aw, perm_idx

    def _decode_infer_greedy(self, enc_out, x_lens, max_decode_len, task, dir):
        """Greedy decoding in the inference stage.
        Args:
            enc_out (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            x_lens (torch.IntTensor): A tensor of size `[B]`
            max_decode_len (int): the length of output sequences
                to stop prediction when EOS token have not been emitted
            task (int, optional): the index of a task
            dir (str): fwd or bwd
        Returns:
            best_hyps (np.ndarray): A tensor of size `[B, T_out]`
            aw (np.ndarray): A tensor of size `[B, T_out, T_in, num_heads]`
        """
        if dir == 'bwd':
            assert getattr(self, 'bwd_weight_' + str(task)) > 0

        batch_size, max_time = enc_out.size()[:2]

        # Initialize decoder state
        dec_state, dec_out = self._init_dec_state(enc_out, x_lens, task, dir)
        aw_step = self._create_tensor((
            batch_size, max_time, getattr(self, 'num_heads_' + str(task))),
            fill_value=0, dtype=torch.float)

        # Start from <SOS>
        sos = getattr(self, 'sos_' + str(task))
        eos = getattr(self, 'eos_' + str(task))
        y = self._create_tensor(
            (batch_size, 1), fill_value=sos, dtype=torch.long)
        y_emb = getattr(self, 'embed_' + str(task))(y)

        best_hyps, aw = [], []
        y_lens = np.zeros((batch_size,), dtype=np.int32)
        eos_flag = [False] * batch_size
        for _ in range(max_decode_len):
            if self.decoding_order == 'attend_generate_update':
                # Score
                context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                    enc_out, x_lens, dec_out, aw_step)

                # Generate
                logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                    getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                    getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

                # Pick up 1-best
                y = torch.max(logits_step.squeeze(1), dim=1)[1].unsqueeze(1)
                best_hyps.append(y)
                y_emb = getattr(self, 'embed_' + str(task))(y)

                # Recurrency
                dec_in = torch.cat([y_emb, context_vec], dim=-1)
                dec_out, dec_state = getattr(
                    self, 'decoder_' + str(task) + '_' + dir)(dec_in, dec_state)

            elif self.decoding_order == 'attend_update_generate':
                # Score
                context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                    enc_out, x_lens, dec_out, aw_step)

                # Recurrency
                dec_in = torch.cat([y_emb, context_vec], dim=-1)
                dec_out, dec_state = getattr(
                    self, 'decoder_' + str(task) + '_' + dir)(dec_in, dec_state)

                # Generate
                logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                    getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                    getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

                # Pick up 1-best
                y = torch.max(logits_step.squeeze(1), dim=1)[1].unsqueeze(1)
                best_hyps.append(y)
                y_emb = getattr(self, 'embed_' + str(task))(y)

            elif self.decoding_order == 'conditional':
                # Recurrency of the first decoder
                _dec_out, _dec_state = getattr(self, 'decoder_first_' + str(task) + '_' + dir)(
                    y_emb, dec_state)

                # Score
                context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                    enc_out, x_lens, _dec_out, aw_step)

                # Recurrency of the second decoder
                dec_out, dec_state = getattr(self, 'decoder_second_' + str(task) + '_' + dir)(
                    context_vec, _dec_state)

                # Generate
                logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                    getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                    getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

                # Pick up 1-best
                y = torch.max(logits_step.squeeze(1), dim=1)[1].unsqueeze(1)
                best_hyps.append(y)
                y_emb = getattr(self, 'embed_' + str(task))(y)

            aw.append(aw_step)

            # Count lengths of hypotheses
            if dir == 'bwd':
                for b in range(batch_size):
                    if not eos_flag[b]:
                        if y.cpu().numpy()[b] == eos:
                            eos_flag[b] = True
                        else:
                            y_lens[b] += 1
                        # NOTE: exclude <EOS>

            # Break if <EOS> is outputed in all mini-batch
            if torch.sum(y == eos) == y.numel():
                break

        # Concatenate in T_out dimension
        best_hyps = torch.cat(best_hyps, dim=1)
        aw = torch.stack(aw, dim=1)

        # Convert to numpy
        best_hyps = self.tensor2np(best_hyps)
        aw = self.tensor2np(aw)

        # Reverse the order
        if dir == 'bwd':
            for b in range(batch_size):
                best_hyps[b, :y_lens[b]] = best_hyps[b, :y_lens[b]][::-1]

        return best_hyps, aw

    def _decode_infer_beam(self, enc_out, x_lens, beam_width, max_decode_len,
                           length_penalty, coverage_penalty, task, dir):
        """Beam search decoding in the inference stage.
        Args:
            enc_out (torch.FloatTensor): A tensor of size
                `[B, T_in, encoder_num_units]`
            x_lens (torch.IntTensor): A tensor of size `[B]`
            beam_width (int): the size of beam
            max_decode_len (int, optional): the length of output sequences
                to stop prediction when EOS token have not been emitted
            length_penalty (float):
            coverage_penalty (float):
            task (int): the index of a task
            dir (str): fwd or bwd
        Returns:
            best_hyps (np.ndarray): A tensor of size `[B]`
        """
        if dir == 'bwd':
            assert getattr(self, 'bwd_weight_' + str(task)) > 0

        # Start from <SOS>
        sos = getattr(self, 'sos_' + str(task))
        eos = getattr(self, 'eos_' + str(task))

        best_hyps, aw = [], []
        for b in range(enc_out.size(0)):
            # Initialization per utterance
            dec_state, dec_out = self._init_dec_state(
                enc_out[b:b + 1], x_lens[b:b + 1], task, dir)
            aw_step = self._create_tensor(
                (1, x_lens[b].item(), getattr(self, 'num_heads_' + str(task))),
                fill_value=0, dtype=torch.float)

            complete = []
            beam = [{'hyp': [sos],
                     'score': LOG_1,
                     'dec_state': dec_state,
                     'dec_out': dec_out,
                     'aw_steps': [aw_step]}]
            for t in range(max_decode_len):
                new_beam = []
                for i_beam in range(len(beam)):
                    if self.decoding_order == 'attend_generate_update':
                        # Score
                        context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                            enc_out[b:b + 1], x_lens[b:b + 1],
                            beam[i_beam]['dec_out'], beam[i_beam]['aw_steps'][-1])

                        # Generate
                        logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                            getattr(self, 'W_d_' + str(task) + '_' + dir)(beam[i_beam]['dec_out']) +
                            getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))
                        # NOTE: Recurrency is placed at the latter stage

                    elif self.decoding_order == 'attend_update_generate':
                        y = self._create_tensor(
                            (1,), fill_value=beam[i_beam]['hyp'][-1], dtype=torch.long).unsqueeze(1)
                        y = getattr(self, 'embed_' + str(task))(y)

                        # Score
                        context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                            enc_out[b:b + 1], x_lens[b:b + 1],
                            beam[i_beam]['dec_out'], beam[i_beam]['aw_steps'][-1])

                        # Recurrency
                        dec_in = torch.cat([y, context_vec], dim=-1)
                        dec_out, dec_state = getattr(self, 'decoder_' + str(task) + '_' + dir)(
                            dec_in, beam[i_beam]['dec_state'])

                        # Generate
                        logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                            getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                            getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

                    elif self.decoding_order == 'conditional':
                        y = self._create_tensor(
                            (1,), fill_value=beam[i_beam]['hyp'][-1], dtype=torch.long).unsqueeze(1)
                        y = getattr(self, 'embed_' + str(task))(y)

                        # Recurrency of the first decoder
                        _dec_out, _dec_state = getattr(self, 'decoder_first_' + str(task) + '_' + dir)(
                            y, beam[i_beam]['dec_state'])

                        # Score
                        context_vec, aw_step = getattr(self, 'attend_' + str(task) + '_' + dir)(
                            enc_out[b:b + 1], x_lens[b:b + 1],
                            _dec_out, beam[i_beam]['aw_steps'][-1])

                        # Recurrency of the second decoder
                        dec_out, dec_state = getattr(self, 'decoder_second_' + str(task) + '_' + dir)(
                            context_vec, _dec_state)

                        # Generate
                        logits_step = getattr(self, 'fc_' + str(task) + '_' + dir)(F.tanh(
                            getattr(self, 'W_d_' + str(task) + '_' + dir)(dec_out) +
                            getattr(self, 'W_c_' + str(task) + '_' + dir)(context_vec)))

                    # Path through the softmax layer & convert to log-scale
                    log_probs = F.log_softmax(logits_step.squeeze(1), dim=1)
                    # NOTE: `[1 (B), 1, num_classes]` -> `[1 (B), num_classes]`

                    # Pick up the top-k scores
                    log_probs_topk, indices_topk = log_probs.topk(
                        beam_width, dim=1, largest=True, sorted=True)

                    for k in range(beam_width):
                        if self.decoding_order == 'attend_generate_update':
                            y = self._create_tensor(
                                (1,), fill_value=indices_topk[0, k].item(), dtype=torch.long).unsqueeze(1)
                            y = getattr(self, 'embed_' + str(task))(y)

                            # Recurrency
                            dec_in = torch.cat([y, context_vec], dim=-1)
                            dec_out, dec_state = getattr(
                                self, 'decoder_' + str(task) + '_' + dir)(dec_in, beam[i_beam]['dec_state'])

                        new_beam.append(
                            {'hyp': beam[i_beam]['hyp'] + [indices_topk[0, k].item()],
                             'score': beam[i_beam]['score'] + log_probs_topk[0, k].item(),
                             'dec_state': copy.deepcopy(dec_state),
                             'dec_out': dec_out,
                             'aw_steps': beam[i_beam]['aw_steps'] + [aw_step]})

                new_beam = sorted(
                    new_beam, key=lambda x: x['score'], reverse=True)

                # Remove complete hypotheses
                not_complete = []
                for cand in new_beam[:beam_width]:
                    if cand['hyp'][-1] == eos:
                        complete.append(cand)
                    else:
                        not_complete.append(cand)
                if len(complete) >= beam_width:
                    complete = complete[:beam_width]
                    break
                beam = not_complete[:beam_width]

            if len(complete) == 0:
                complete = beam

            # Renormalized hypotheses by length
            if length_penalty > 0:
                for j in range(len(complete)):
                    complete[j]['score'] += len(complete[j]
                                                ['hyp']) * length_penalty

            complete = sorted(
                complete, key=lambda x: x['score'], reverse=True)
            best_hyps.append(np.array(complete[0]['hyp'][1:]))
            # NOTE: Exclude <SOS>
            aw.append(complete[0]['aw_steps'])

        # Concatenate in T_out dimension
        for j in range(len(aw)):
            aw[j] = aw[j][1:]
            # NOTE: exclude the first atteniton weights

            for k in range(len(aw[j])):
                aw[j][k] = aw[j][k][:, :, 0]
                # TODO: fix for multi-head atteniton

            aw[j] = self.tensor2np(torch.stack(aw[j], dim=1).squeeze(0))

        # Reverse the order
        if dir == 'bwd':
            raise NotImplementedError
            # for b in range(batch_size):
            #     best_hyps[b, :y_lens[b]] = best_hyps[b, :y_lens[b]][::-1]

        return np.array(best_hyps), aw

    def decode_ctc(self, xs, x_lens, beam_width=1, task_index=0):
        """Decoding by the CTC layer in the inference stage.
            This is only used for Joint CTC-Attention model.
        Args:
            xs (np.ndarray): A tensor of size `[B, T_in, input_size]`
            x_lens (np.ndarray): A tensor of size `[B]`
            beam_width (int, optional): the size of beam
            task_index (int, optional): the index of a task
        Returns:
            best_hyps (np.ndarray): A tensor of size `[B]`
            perm_idx (np.ndarray): A tensor of size `[B]`
        """
        self.eval()
        with torch.no_grad():
            # Wrap by Tensor
            xs = self.np2tensor(xs, dtype=torch.float)
            x_lens = self.np2tensor(x_lens, dtype=torch.int)

            # Encode acoustic features
            if task_index == 0:
                enc_out, x_lens, perm_idx = self._encode(xs, x_lens)
            elif task_index == 1:
                _, _, enc_out, x_lens, perm_idx = self._encode(
                    xs, x_lens, is_multi_task=True)
            else:
                raise NotImplementedError

            # Path through the softmax layer
            batch_size, max_time = enc_out.size()[:2]
            enc_out = enc_out.contiguous().view(batch_size * max_time, -1)
            logits_ctc = getattr(self, 'fc_ctc_' + str(task_index))(enc_out)
            logits_ctc = logits_ctc.view(batch_size, max_time, -1)

        if beam_width == 1:
            best_hyps = self._decode_ctc_greedy_np(
                self.tensor2np(logits_ctc), self.tensor2np(x_lens))
        else:
            best_hyps = self._decode_ctc_beam_np(
                self.tensor2np(F.log_softmax(logits_ctc, dim=-1)),
                self.tensor2np(x_lens), beam_width=beam_width)

        # NOTE: index 0 is reserved for blank in warpctc_pytorch
        best_hyps -= 1

        # Permutate indices to the original order
        perm_idx = self.tensor2np(perm_idx)

        return best_hyps, perm_idx
