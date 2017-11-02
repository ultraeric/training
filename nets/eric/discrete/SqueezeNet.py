"""SqueezeNet 1.1 modified for regression."""
import torch
import torch.nn as nn
import torch.nn.init as init
from torch.autograd import Variable
import logging
logging.basicConfig(filename='training.log', level=logging.DEBUG)


class Fire(nn.Module):

    def __init__(self, inplanes, squeeze_planes,
                 expand1x1_planes, expand3x3_planes):
        super(Fire, self).__init__()
        self.norm = torch.nn.BatchNorm2d(expand1x1_planes + expand3x3_planes)
        self.inplanes = inplanes
        self.squeeze = nn.Conv2d(inplanes, squeeze_planes, kernel_size=1)
        self.squeeze_activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)
        self.expand1x1 = nn.Conv2d(squeeze_planes, expand1x1_planes,
                                   kernel_size=1)
        self.expand1x1_activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)
        self.expand3x3 = nn.Conv2d(squeeze_planes, expand3x3_planes,
                                   kernel_size=3, padding=1)
        self.expand3x3_activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)
        self.should_iterate = inplanes == (expand3x3_planes + expand1x1_planes)

    def forward(self, input_data):
        """Forward-propagates data through Fire module"""
        output_data = self.squeeze_activation(self.squeeze(input_data))
        output_data = torch.cat([
            self.expand1x1_activation(self.expand1x1(output_data)),
            self.expand3x3_activation(self.expand3x3(output_data))
        ], 1)
        output_data = output_data + input_data if self.should_iterate else output_data
        output_data = self.norm(output_data)
        return output_data


class SqueezeNet(nn.Module):

    def __init__(self, n_steps=10, n_frames=2):
        super(SqueezeNet, self).__init__()

        self.n_steps = n_steps
        self.n_frames = n_frames
        self.final_output = nn.Sequential(
            nn.Conv2d(6 * self.n_frames, 12, kernel_size=3, stride=1, padding=1),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.BatchNorm2d(12),
            nn.Conv2d(12, 16, kernel_size=3, stride=1, padding=1),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.BatchNorm2d(16),
            nn.Conv2d(16, 16, kernel_size=3, stride=2),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.AvgPool2d(kernel_size=3, stride=2, ceil_mode=True),
            nn.BatchNorm2d(16),

            nn.Dropout2d(p=0.5),
            Fire(16, 4, 8, 8),
            Fire(16, 12, 12, 12),
            Fire(24, 16, 16, 16),
            nn.AvgPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(32, 16, 16, 16),
            Fire(32, 24, 24, 24),
            nn.Dropout2d(p=0.5),
            Fire(48, 24, 24, 24),
            Fire(48, 32, 32, 32),
            nn.AvgPool2d(kernel_size=3, stride=2, ceil_mode=True),
            Fire(64, 32, 32, 32),

            nn.Conv2d(64, 32, kernel_size=3, stride=2, padding=1),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.BatchNorm2d(32),
            nn.Dropout2d(p=0.5),
            nn.Conv2d(32, 16, kernel_size=3, stride=2, padding=1),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.BatchNorm2d(16),
            nn.Dropout2d(p=0.5),
            nn.Conv2d(16, 10, kernel_size=3, stride=2, padding=1),
        )
        self.lsm = nn.LogSoftmax()
        self.lsm2 = nn.LogSoftmax()

        for mod in self.modules():
            if hasattr(mod, 'weight') and hasattr(mod.weight, 'data'):
                if isinstance(mod, nn.Conv2d):
                    init.kaiming_uniform(mod.weight.data)
                elif len(mod.weight.data.size()) >= 2:
                    init.xavier_uniform(mod.weight.data)
                else:
                    init.normal(mod.weight.data)
            if hasattr(mod, 'bias') and hasattr(mod.bias, 'data'):
                init.normal(mod.bias.data)

    def forward(self, x, metadata):
        x = torch.unbind(self.final_output(x).squeeze(2), 2)
        steering, controls = self.lsm(x[0]), self.lsm2(x[1])
        return steering, controls

    def num_params(self):
        return sum([reduce(lambda x, y: x * y, [dim for dim in p.size()], 1) for p in self.parameters()])

def unit_test():
    test_net = SqueezeNet(5, 6)
    a = test_net(Variable(torch.randn(2, 6*6, 94, 168)),
                 Variable(torch.randn(2, 8, 23, 41)))
    print(a[0].size())
    logging.debug('Net Test Output = {}'.format(a))
    logging.debug('Network was Unit Tested')
    print(test_net.num_params())

unit_test()

Net = SqueezeNet