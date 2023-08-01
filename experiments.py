import cv2
import os
import random
import math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Adam
import torchvision
from torchvision.transforms import transforms
from torchvision.datasets import ImageFolder
from torch.utils.data import DataLoader
from matplotlib import pyplot as plt

img_size = 64
batch_size = 128

def load_transformed_dataset(path, img_size=img_size, batch_size=batch_size):

    data_transforms = [
        transforms.Resize((img_size, img_size)),
        transforms.ToTensor(),
        transforms.RandomHorizontalFlip(),
        transforms.Lambda(lambda x: (x * 2) - 1)  # scales data to [-1, 1]
    ]

    data_transform = transforms.Compose(data_transforms)

    ds = ImageFolder(root=path, transform=data_transform)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=True)

    return dl


def show_images(dl, num_samples=20, cols=4):

    for data, y in dl:
        break

    plt.figure(figsize=(15, 15))
    for i in range(num_samples):
        random_idx = np.random.randint(0, data.shape[0])
        img = (data[random_idx] + 1) / 2
        plt.subplot(int(num_samples / cols + 1), cols, i + 1)
        # plt.imshow(img.permute(1, 2, 0))

    return

dl = load_transformed_dataset(path='data/cars')
# show_images(dl)


#forward process - adding noise / noise scheduler


def linear_beta_scheduler(timesteps, start=0.0001, end=0.02):

    out = torch.linspace(start, end, timesteps)

    return out


# returns an index t of list given the batch dimension
# TODO: undesrtand what this is used for
def get_index_from_list(vals, t, x_shape):

    batch_size = t.shape[0]
    out = vals.gather(-1, t.cpu())
    out = out.reshape(batch_size, *((1,) * (len(x_shape) - 1))).to(t.device)

    return out

# TODO: understand what this is used for
# takes an image and a timestep, retuns noisy image (and noise itself) at that timestep
def forward_diffusion_sample(x0, t, device=device):

    noise = torch.randn_like(x0)
    sqrt_alphas_cumprod_t = get_index_from_list(sqrt_alphas_cumprod, t, x0.shape)
    sqrt_one_minus_alphas_cumprod_t = get_index_from_list(sqrt_one_minus_alphas_cumprod, t, x0.shape)

    # mean + variance
    noisy_img = sqrt_alphas_cumprod_t.to(device) * x0.to(device) \
          + sqrt_one_minus_alphas_cumprod_t.to(device) * noise.to(device)
    noise = noise.to(device)

    return noisy_img, noise


# beta scheduler
T = 120
betas = linear_beta_scheduler(timesteps=T)

# pre-calculate terms, alphas cumulative produts
alphas = 1.0 - betas
alphas_cumprod = torch.cumprod(alphas, axis=0)
alphas_cumprod_prev = F.pad(alphas_cumprod[:-1], (1, 0), value=1.0)
sqrt_recip_alphas = torch.sqrt(1.0 / alphas)
sqrt_alphas_cumprod = torch.sqrt(alphas_cumprod)
sqrt_one_minus_alphas_cumprod = torch.sqrt(1.0 - alphas_cumprod)
posterior_variance = betas * (1.0 - alphas_cumprod_prev) / (1.0 - alphas_cumprod)


# simulate forward diffusion over single image
img = next(iter(dl))[0][0]
img = (img + 1) / 2

plt.figure(figsize=(15, 15))
plt.axis('off')
n_images = 10
step_size = int(T / n_images)

# for idx in range(0, T, step_size):
#
#     t = torch.tensor([idx]).type(torch.int64)
#     plt.subplot(1, n_images+1, int((idx/step_size)+1))
#     img, noise = forward_diffusion_sample(img, t)
#     img = img.cpu()
#     plt.imshow(img.permute(1, 2, 0))
#
# plt.show()

# U-NET - used for backward diffusion
# convlolutions, down and up sampling, residual connections
# similar to auto-encoder
# denoising score matching
# positional embeddings are used for the step in the sequence information (t)
# U-Net needs to predict the noise and subtract it from the image (to get image at noise step t-1)


# upsaling downsampling convolutions?
class Block(nn.Module):
    def __init__(self, in_ch, out_ch, time_emb_dim, up=False):
        super().__init__()
        self.time_mlp = nn.Linear(time_emb_dim, out_ch)
        if up:
            self.conv1 = nn.Conv2d(2*in_ch, out_ch, 3, padding=1)
            self.transform = nn.ConvTranspose2d(out_ch, out_ch, 4, 2, 1)
        else:
            self.conv1 = nn.Conv2d(in_ch, out_ch, 3, padding=1)
            self.transform = nn.Conv2d(out_ch, out_ch, 4, 2, 1)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, padding=1)
        self.bnorm1 = nn.BatchNorm2d(out_ch)
        self.bnorm2 = nn.BatchNorm2d(out_ch)
        self.relu = nn.ReLU()

    def forward(self, x, t, ):
        # First Conv
        h = self.bnorm1(self.relu(self.conv1(x)))
        # Time embedding
        time_emb = self.relu(self.time_mlp(t))
        # Extend last 2 dimensions
        time_emb = time_emb[(...,) + (None,) * 2]
        # Add time channel
        h = h + time_emb
        # Second Conv
        h = self.bnorm2(self.relu(self.conv2(h)))
        # Down or Upsample
        return self.transform(h)



class SinusoidalPositionEmbeddings(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.dim = dim

    def forward(self, time):
        device = time.device
        half_dim = self.dim // 2
        embeddings = math.log(10000) / (half_dim - 1)
        embeddings = torch.exp(torch.arange(half_dim, device=device) * -embeddings)
        embeddings = time[:, None] * embeddings[None, :]
        embeddings = torch.cat((embeddings.sin(), embeddings.cos()), dim=-1)
        # TODO: Double check the ordering here
        return embeddings






class SimpleUnet(nn.Module):
    """
    A simplified variant of the Unet architecture.
    """

    def __init__(self):
        super().__init__()
        image_channels = 3
        down_channels = (64, 128, 256, 512, 1024)
        up_channels = (1024, 512, 256, 128, 64)
        out_dim = 3
        time_emb_dim = 32

        # Time embedding
        self.time_mlp = nn.Sequential(
            SinusoidalPositionEmbeddings(time_emb_dim),
            nn.Linear(time_emb_dim, time_emb_dim),
            nn.ReLU()
        )

        # Initial projection
        self.conv0 = nn.Conv2d(image_channels, down_channels[0], 3, padding=1)

        # Downsample
        self.downs = nn.ModuleList([Block(down_channels[i], down_channels[i + 1], \
                                          time_emb_dim) \
                                    for i in range(len(down_channels) - 1)])
        # Upsample
        self.ups = nn.ModuleList([Block(up_channels[i], up_channels[i + 1], \
                                        time_emb_dim, up=True) \
                                  for i in range(len(up_channels) - 1)])

        # Edit: Corrected a bug found by Jakub C (see YouTube comment)
        self.output = nn.Conv2d(up_channels[-1], out_dim, 1)

    def forward(self, x, timestep):
        # Embedd time
        t = self.time_mlp(timestep)
        # Initial conv
        x = self.conv0(x)
        # Unet
        residual_inputs = []
        for down in self.downs:
            x = down(x, t)
            residual_inputs.append(x)
        for up in self.ups:
            residual_x = residual_inputs.pop()
            # Add residual x as additional channels
            x = torch.cat((x, residual_x), dim=1)
            x = up(x, t)
        return self.output(x)


model = SimpleUnet()
print("Num params: ", sum(p.numel() for p in model.parameters()))
model

def get_loss(model, x0, t):

    x_noisy, noise = forward_diffusion_sample(x0, t)
    noise_pred = model(x_noisy, t)

    # TODO check L1 loss
    return F.l1_loss(noise, noise_pred)


# uses the model to predict the noise, next denoise the image
# applies noise to this image, if not in the last step
@torch.no_grad()
def sample_timestep(x, t):

    betas_t = get_index_from_list(betas, t, x.shape)
    sqrt_one_minus_alphas_cumprod_t = get_index_from_list(sqrt_one_minus_alphas_cumprod, t, x.shape)
    sqrt_recip_alphas_t = get_index_from_list(sqrt_recip_alphas, t, x.shape)

    # call model
    model_mean = sqrt_recip_alphas_t * (x - betas_t * model(x, t) / sqrt_one_minus_alphas_cumprod_t)
    posterior_variance_t = get_index_from_list(posterior_variance, t, x.shape)

    if t == 0:
        return model_mean
    else:
        noise = torch.randn_like(x)
        return model_mean + torch.sqrt(posterior_variance_t) * noise


@torch.no_grad()
def sample_plot_image(img_size, device, idx):

    # sample noise
    img = torch.randn((1, 3, img_size, img_size), device=device)
    plt.figure(figsize=(15, 15))
    plt.axis('off')
    n_images = 10
    step = int(T/n_images)

    for i in range(0, T)[::-1]:
        t = torch.full((1,), i, device=device, dtype=torch.long)
        img = sample_timestep(img, t)
        if i % step == 0:
            plt.subplot(1, n_images, int(i/step+1))
            show_images(img.detach().cpu())
    plt.savefig(f'samples/img{idx}.png')

device = 'cuda'
model.to(device)
opt = Adam(model.parameters(), lr=0.001)
epochs = 5

for epoch in range(epochs):
    for step, batch in enumerate(dl):

        opt.zero_grad()

        t = torch.randint(0, T, (batch_size,), device=device).long()
        loss = get_loss(model, batch[0], t)
        loss.backward()
        opt.step()

        if epoch % 5 == 0 and step == 0:
            print(f'epoch: {epoch}, step: {step}, loss: {loss.item()}')
            sample_plot_image(img_size, device, epoch)

