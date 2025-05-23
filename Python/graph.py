import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
import random

# Create initial line
x = []
y = []
z = []

# Set up the figure and 3D axis
fig = plt.figure()
ax = fig.add_subplot(111, projection="3d")  # 3d axis
ax.set_xlim(-5, 5)
ax.set_ylim(-5, 5)
ax.set_zlim(-5, 5)

# Plot the initial 3D line
(line,) = ax.plot(x, y, z, label="3D Line")


plt.ion()  # Turn on interactive mode
plt.show()


# Randomly add a point to a line after 5 seconds
def update_line(x, y, z):
    global line
    # random point from -5 to 5
    x.append(random.randint(-5, 5))
    y.append(random.randint(-5, 5))
    z.append(random.randint(-5, 5))
    # update line
    line.set_data(x, y)
    line.set_3d_properties(z)
    # show line
    plt.draw()
    plt.pause(5)  # 5 seconds delay


# adding 10 points
# notes: would need 2 points to form first line
for i in range(1, 10):
    update_line(x, y, z)
