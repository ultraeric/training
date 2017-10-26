"""SqueezeNet 1.1 modified for regression."""
import torch
import torch.nn as nn
import torch.nn.init as init
from torch.autograd import Variable
import logging
logging.basicConfig(filename='training.log', level=logging.DEBUG)

class Feedforward(nn.Module):

    def __init__(self, n_steps=10, n_frames=2):
        super(Feedforward, self).__init__()

        self.n_steps = n_steps
        self.n_frames = n_frames
        self.pre_metadata_features = nn.Sequential(
            nn.Conv2d(3 * 2 * n_frames, 8, kernel_size=3, stride=2),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            nn.Conv2d(8, 8, kernel_size=3, padding=1)
        )
        self.post_metadata_features = nn.Sequential(
            nn.Conv2d(16, 12, kernel_size=3, padding=1),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            nn.Conv2d(12, 12, kernel_size=3, padding=1),
            nn.Conv2d(12, 16, kernel_size=3, padding=1),
            nn.MaxPool2d(kernel_size=3, stride=2, ceil_mode=True),
            nn.Conv2d(16, 16, kernel_size=3, padding=1),
            nn.Conv2d(16, 24, kernel_size=3, padding=1),
            nn.Conv2d(24, 24, kernel_size=3, padding=1)
        )
        final_conv = nn.Conv2d(24, self.n_steps, kernel_size=1)
        self.final_output = nn.Sequential(
            nn.Dropout(p=0.5),
            final_conv,
            # nn.ReLU(inplace=True),
            nn.AvgPool2d(kernel_size=5, stride=5)
        )

        for mod in self.modules():
            init.normal(mod.weight.data, 0, 3)
            if mod.bias is not None:
                init.normal(mod.weight.data, 0, 0.5)

    def forward(self, x, metadata):
        x = self.pre_metadata_features(x)
        x = torch.cat((x, metadata), 1)
        x = self.post_metadata_features(x)
        x = self.final_output(x)
        x = x.view(x.size(0), -1, 2)
        return x

    def num_params(self):
        return sum([reduce(lambda x, y: x * y, [dim for dim in p.size()], 1) for p in self.parameters()])

def unit_test():
    test_net = Feedforward(20, 6)
    a = test_net(Variable(torch.randn(1, 36, 94, 168)),
                 Variable(torch.randn(1, 8, 23, 41)))
    sizes = [1, 20, 2]
    assert(all(a.size(i) == sizes[i] for i in range(len(sizes))))
    logging.debug('Net Test Output = {}'.format(a))
    logging.debug('Network was Unit Tested')
    print(test_net.num_params())

unit_test()

Net = Feedforward