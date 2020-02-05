#!/usr/bin/env python
# coding: utf-8

# In[1]:


# Copyright (c) Facebook, Inc. and its affiliates. All rights reserved.


# # Deform a source mesh to form a target mesh using 3D loss functions

# In this tutorial, we learn to deform an initial generic shape (e.g. sphere) to fit a target shape.
# 
# We will cover: 
# 
# - How to **load a mesh** from an `.obj` file
# - How to use the PyTorch3d **Meshes** datastructure
# - How to use 4 different PyTorch3d **mesh loss functions**
# - How to set up an **optimization loop**
# 
# 
# Starting from a sphere mesh, we learn the offset to each vertex in the mesh such that
# the predicted mesh is closer to the target mesh at each optimization step. To achieve this we minimize:
# 
# + `chamfer_distance`, the distance between the predicted (deformed) and target mesh, defined as the chamfer distance between the set of pointclouds resulting from **differentiably sampling points** from their surfaces. 
# 
# However, solely minimizing the chamfer distance between the predicted and the target mesh will lead to a non-smooth shape (verify this by setting  `w_chamfer=1.0` and all other weights to `0.0`). 
# 
# We enforce smoothness by adding **shape regularizers** to the objective. Namely, we add:
# 
# + `mesh_edge_length`, which minimizes the length of the edges in the predicted mesh.
# + `mesh_normal_consistency`, which enforces consistency across the normals of neighboring faces.
# + `mesh_laplacian_smoothing`, which is the laplacian regularizer.

# ## 0. Import modules

# In[2]:


import os
import torch
from pytorch3d.io import load_obj, save_obj
from pytorch3d.structures import Meshes
from pytorch3d.utils import ico_sphere
from pytorch3d.ops import sample_points_from_meshes
from pytorch3d.loss import (
    chamfer_distance, 
    mesh_edge_loss, 
    mesh_laplacian_smoothing, 
    mesh_normal_consistency,
)
import numpy as np
from tqdm import tqdm_notebook
get_ipython().run_line_magic('matplotlib', 'notebook')
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt
import matplotlib as mpl
mpl.rcParams['savefig.dpi'] = 80
mpl.rcParams['figure.dpi'] = 80

# Set the device
device = torch.device("cuda:0")


# ## 1. Load an obj file and create a Meshes object

# In[4]:


# The path to the target 3D model we wish to fit
# e.g. download https://free3d.com/3d-model/-dolphin-v1--12175.html and save in ./data/dolphin
trg_obj = os.path.join('./data/doplhin', '10014_dolphin_v2_max2011_it2.obj')


# In[6]:


# We read the target 3D model using load_obj
verts, faces, aux = load_obj(trg_obj)

# verts is a FloatTensor of shape (V, 3) where V is the number of vertices in the mesh
# faces is an object which contains the following LongTensors: verts_idx, normals_idx and textures_idx
# For this tutorial, normals and textures are ignored.
faces_idx = faces.verts_idx.to(device)
verts = verts.to(device)

# We scale normalize and center the target mesh to fit in a sphere of radius 1 centered at (0,0,0). 
# (scale, center) will be used to bring the predicted mesh to its original center and scale
# Note that normalizing the target mesh, speeds up the optimization but is not necessary!
center = verts.mean(0)
verts = verts - center
scale = max(verts.abs().max(0)[0])
verts = verts / scale

# We construct a Meshes structure for the target mesh
trg_mesh = Meshes(verts=[verts], faces=[faces_idx])


# In[11]:


# We initialize the source shape to be a sphere of radius 1
src_mesh = ico_sphere(4, device)


# ###  Visualize the source and target meshes

# In[12]:


def plot_pointcloud(mesh, title=""):
    verts = mesh.verts_packed()
    faces = mesh.faces_packed()
    x, y, z = verts.clone().detach().cpu().unbind(1)    
    fig = plt.figure(figsize=(5, 5))
    ax = Axes3D(fig)
    ax.scatter3D(x, z, -y)
    ax.set_xlabel('x')
    ax.set_ylabel('z')
    ax.set_zlabel('y')
    ax.set_title(title)
    plt.show()


# In[13]:


get_ipython().run_line_magic('matplotlib', 'notebook')
plot_pointcloud(trg_mesh, "Target mesh")
plot_pointcloud(src_mesh, "Source mesh")


# ## 3. Optimization loop 

# In[14]:


# We will learn to deform the source mesh by offsetting its vertices
# The shape of the derform parameters is equal to the total number of vertices in src_mesh
deform_verts = torch.full(src_mesh.verts_packed().shape, 0.0, device=device, requires_grad=True)


# In[15]:


# The optimizer
optimizer = torch.optim.SGD([deform_verts], lr=1.0, momentum=0.9)


# In[16]:


# Number of optimization steps
Niter = 2000
# Weight for the chamfer loss
w_chamfer = 1.0 
# Weight for mesh edge loss
w_edge = 1.0 
# Weight for mesh normal consistency
w_normal = 0.01 
# Weight for mesh laplacian smoothing
w_laplacian = 0.1 
# Plot period for the losses
plot_period = 250
loop = tqdm_notebook(range(Niter))

chamfer_losses = []
laplacian_losses = []
edge_losses = []
normal_losses = []

get_ipython().run_line_magic('matplotlib', 'inline')

for i in loop:
    # Initialize optimizer
    optimizer.zero_grad()
    
    # Deform the mesh
    new_src_mesh = src_mesh.offset_verts(deform_verts)
    
    # We sample 5k points from the surface of each mesh 
    sample_trg = sample_points_from_meshes(trg_mesh, 5000)
    sample_src = sample_points_from_meshes(new_src_mesh, 5000)
    
    # We compare the two sets of pointclouds by computing (a) the chamfer loss
    loss_chamfer, _ = chamfer_distance(sample_trg, sample_src)
    
    # and (b) the edge length of the predicted mesh
    loss_edge = mesh_edge_loss(new_src_mesh)
    
    # mesh normal consistency
    loss_normal = mesh_normal_consistency(new_src_mesh)
    
    # mesh laplacian smoothing
    loss_laplacian = mesh_laplacian_smoothing(new_src_mesh, method="uniform")
    
    # Weighted sum of the losses
    loss = loss_chamfer * w_chamfer + loss_edge * w_edge + loss_normal * w_normal + loss_laplacian * w_laplacian
    
    # Print the losses
    loop.set_description('total_loss = %.6f' % loss)
    
    # Save the losses for plotting
    chamfer_losses.append(loss_chamfer)
    edge_losses.append(loss_edge)
    normal_losses.append(loss_normal)
    laplacian_losses.append(loss_laplacian)
    
    # Plot mesh
    if i % plot_period == 0:
        plot_pointcloud(new_src_mesh, title="iter: %d" % i)
        
    # Optimization step
    loss.backward()
    optimizer.step()


# ## 4. Visualize the loss

# In[17]:


fig = plt.figure(figsize=(13, 5))
ax = fig.gca()
ax.plot(chamfer_losses, label="chamfer loss")
ax.plot(edge_losses, label="edge loss")
ax.plot(normal_losses, label="normal loss")
ax.plot(laplacian_losses, label="laplacian loss")
ax.legend(fontsize="16")
ax.set_xlabel("Iteration", fontsize="16")
ax.set_ylabel("Loss", fontsize="16")
ax.set_title("Loss vs iterations", fontsize="16")


# ## 5. Save the predicted mesh

# In[ ]:


# Fetch the verts and faces of the final predicted mesh
final_verts, final_faces = new_src_mesh.get_mesh_verts_faces(0)

# Scale normalize back to the original target size
final_verts = final_verts * scale + center

# Store the predicted mesh using save_obj
final_obj = os.path.join('./', 'final_model.obj')
save_obj(final_obj, final_verts, final_faces)


# ## 6. Conclusion 
# 
# In this tutorial we learnt how to load a mesh from an obj file, initialize a PyTorch3d datastructure called **Meshes**, set up an optimization loop and use four different PyTorch3d mesh loss functions. 