"""SqueezeNet 1.1 modified for LSTM regression."""
import logging

import torch
import torch.nn as nn
import torch.nn.init as init
import random
from torch.autograd import Variable

logging.basicConfig(filename='training.log', level=logging.DEBUG)


# from Parameters import ARGS

activation = nn.ELU
pool = nn.AvgPool2d

class Fire(nn.Module):  # pylint: disable=too-few-public-methods
    """Implementation of Fire module"""

    def __init__(self, inplanes, squeeze_planes,
                 expand1x1_planes, expand3x3_planes):
        """Sets up layers for Fire module"""
        super(Fire, self).__init__()
        self.final_output = nn.Sequential(
            torch.nn.BatchNorm2d(expand1x1_planes + expand3x3_planes),
            nn.Dropout(p=(expand3x3_planes+expand1x1_planes) / 384.),
        )
        self.inplanes = inplanes
        self.squeeze = nn.Conv2d(inplanes, squeeze_planes, kernel_size=1)
        self.squeeze_activation = activation(inplace=True)
        self.expand1x1 = nn.Conv2d(squeeze_planes, expand1x1_planes, kernel_size=1)
        self.expand1x1_activation = activation(inplace=True)
        self.expand3x3 = nn.Conv2d(squeeze_planes, expand3x3_planes, kernel_size=3, padding=1)
        self.expand3x3_activation = activation(inplace=True)
        # self.should_iterate = inplanes == (expand3x3_planes + expand1x1_planes)
        # self.passthrough = nn.Sequential(
        #     nn.Conv2d(inplanes, expand1x1_planes + expand3x3_planes, kernel_size=1),
        #     activation(inplace=True)
        # )

    def forward(self, input_data):
        """Forward-propagates data through Fire module"""
        output_data = self.squeeze_activation(self.squeeze(input_data))
        output_data = torch.cat([
            self.expand1x1_activation(self.expand1x1(output_data)),
            self.expand3x3_activation(self.expand3x3(output_data))
        ], 1)
        output_data = output_data \
                      # + self.passthrough(input_data)
        output_data = self.final_output(output_data)
        return output_data



class SqueezeNetTimeLSTM(nn.Module):  # pylint: disable=too-few-public-methods
    """SqueezeNet+LSTM for end to end autonomous driving"""

    def __init__(self, n_frames=2, n_steps=10):
        """Sets up layers"""
        super(SqueezeNetTimeLSTM, self).__init__()

        self.is_cuda = False
        self.requires_controls = True

        self.n_frames = n_frames
        self.n_steps = n_steps
        self.pre_lstm_output = nn.Sequential(
            nn.Conv2d(6, 12, kernel_size=3, stride=1, padding=1),
            activation(inplace=True),
            nn.BatchNorm2d(12),
            nn.Conv2d(12, 24, kernel_size=3, stride=1, padding=1),
            activation(inplace=True),
            nn.BatchNorm2d(24),
            nn.Conv2d(24, 32, kernel_size=3, stride=2),
            activation(inplace=True),
            nn.BatchNorm2d(32),
            pool(kernel_size=3, stride=2, ceil_mode=True),
            nn.Dropout(p=0.5),

            Fire(32, 16, 16, 16),
            Fire(32, 24, 24, 24),
            Fire(48, 24, 24, 24),
            pool(kernel_size=3, stride=2, ceil_mode=True),
            Fire(48, 32, 32, 32),
            Fire(64, 32, 32, 32),
            Fire(64, 48, 48, 48),
            Fire(96, 48, 48, 48),
            pool(kernel_size=3, stride=2, ceil_mode=True),
            Fire(96, 64, 64, 64),
            Fire(128, 64, 64, 64),

            nn.Conv2d(128, 64, kernel_size=3, stride=2, padding=1),
            activation(inplace=True),
            nn.BatchNorm2d(64),
            nn.Dropout(p=0.5),
            nn.Conv2d(64, 32, kernel_size=3, stride=2, padding=1),
            activation(inplace=True),
            nn.BatchNorm2d(32),
            # nn.Dropout2d(p=0.2),
            nn.Conv2d(32, 31, kernel_size=3, stride=2, padding=1),
            activation(inplace=True),
            nn.BatchNorm2d(31),
        )
        self.lstm_encoder = nn.ModuleList([
            nn.LSTM(64, 128, 2, batch_first=True)
        ])
        self.lstm_decoder = nn.ModuleList([
            nn.LSTM(1, 128, 2, batch_first=True)
        ])
        self.output_linear = nn.Sequential(
                                            nn.BatchNorm1d(128),
                                            nn.Dropout(p=0.5),
                                            nn.Linear(128, 64),
                                            activation(inplace=True),
                                            nn.BatchNorm1d(64),
                                            nn.Dropout(p=0.5),
                                            nn.Linear(64, 32),
                                            activation(inplace=True),
                                            nn.BatchNorm1d(32),
                                            nn.Linear(32, 2),
                                            nn.Sigmoid()
                                           )

        for mod in self.pre_lstm_output.modules():
            if hasattr(mod, 'weight') and hasattr(mod.weight, 'data'):
                if isinstance(mod, nn.Conv2d):
                    init.kaiming_normal(mod.weight.data)
                elif len(mod.weight.data.size()) >= 2:
                    init.xavier_normal(mod.weight.data)
                else:
                    init.normal(mod.weight.data)
            # elif hasattr(mod, 'bias') and hasattr(mod.bias, 'data'):
            #     init.normal(mod.bias.data, mean=0, std=0.000000001)


    def forward(self, camera_data, metadata, previous_controls, controls=None):
        """Forward-propagates data through SqueezeNetTimeLSTM"""
        batch_size = camera_data.size(0)

        net_output = camera_data.contiguous().view(-1, 6, 94, 168)
        net_output = self.pre_lstm_output(net_output)
        net_output = net_output.contiguous().view(batch_size, -1, 62)
        previous_controls = previous_controls.contiguous().view(batch_size, -1, 2)
        net_output = torch.cat([net_output, previous_controls], 2)
        for lstm in self.lstm_encoder:
            lstm_output, last_hidden_cell = lstm(net_output)
        for lstm in self.lstm_decoder:
            if last_hidden_cell:
                net_output = lstm(self.get_decoder_input(camera_data), last_hidden_cell)[0]
                last_hidden_cell = None
            else:
                net_output = lstm(net_output)[0]

        # net_output = torch.unbind(camera_data.contiguous().view(batch_size, -1,  6, 94, 168), dim=1)
        # init_input = self.pre_lstm_output(net_output[0]).contiguous().view(batch_size, -1, 24)
        # last_hidden_cell = None
        # for i in range(1, len(net_output)):
        #     for lstm in self.lstm_encoder:
        #         lstm_output, last_hidden_cell = lstm(init_input, last_hidden_cell)
        #         init_input = self.pre_lstm_output(net_output[i]).contiguous().view(batch_size, -1, 24)
        # lstm_output, last_hidden_cell = lstm(init_input, last_hidden_cell)

        # for lstm in   self.lstm_decoder:
        #     if last_hidden_cell:
        #         net_output = lstm(self.get_decoder_input(camera_data), last_hidden_cell)[0]
        #         last_hidden_cell = None
        #     else:
        #         net_output = lstm(net_output)[0]

        # Initialize the decoder sequence
        # init_input = Variable(torch.ones(batch_size, 1, 24) * 0.5)
        # init_input = init_input.cuda() if self.is_cuda else init_input
        # lstm_output, last_hidden_cell = self.lstm_decoder[0](init_input, last_hidden_cell)
        # init_input = self.post_lstm_linear(lstm_output.contiguous().squeeze(1)).unsqueeze(1)

        net_output = self.output_linear(net_output.contiguous().view(-1, 128))
        net_output = net_output.contiguous().view(batch_size, -1, 2)
        return net_output

    def get_decoder_input(self, camera_data):
        batch_size = camera_data.size(0)
        input = Variable(torch.zeros(batch_size, self.n_steps, 1))
        return input.cuda() if self.is_cuda else input


    def get_decoder_seq(self, controls):
        controls = controls.clone()
        if controls.size(1) > 1:
            controls[:,1:,:] = controls[:,0:controls.size(1)-1,:]
        controls[:,0,:] = 0
        decoder_input_seq = Variable(controls)
        return decoder_input_seq.cuda() if self.is_cuda else decoder_input_seq


    def cuda(self, device_id=None):
        self.is_cuda = True
        return super(SqueezeNetTimeLSTM, self).cuda(device_id)

    def num_params(self):
        return sum([reduce(lambda x, y: x * y, [dim for dim in p.size()], 1) for p in self.parameters()])

def unit_test():
    """Tests SqueezeNetTimeLSTM for size constitency"""
    test_net = SqueezeNetTimeLSTM(20, 10)
    test_net_output = test_net(
        Variable(torch.randn(2, 20 * 6, 94, 168)),
        Variable(torch.randn(2, 20, 8, 23, 41)),
        Variable(torch.randn(2, 20 * 2))
    )
    sizes = [2, 10, 2]
    print(test_net_output.size())
    assert(all(test_net_output.size(i) == sizes[i] for i in range(len(sizes))))
    logging.debug('Net Test Output = {}'.format(test_net_output))
    logging.debug('Network was Unit Tested')
    print(test_net.num_params())

unit_test()

Net = SqueezeNetTimeLSTM