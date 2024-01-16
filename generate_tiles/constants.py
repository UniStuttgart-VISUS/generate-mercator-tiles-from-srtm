import numpy as np

HILLSHADE_AZIMUTH = 60
DIM = 3601  # arcsecond resolution per degree x degree cell
IN_DTYPE = np.dtype('>i2')  # binary representation in .hgt files
INTERMEDIATE_DTYPE = np.float32  # numpy ndarray representation for calculations
IN_IMAGE_MODE = 'I;16B'  # PIL/Pillow image mode for input HGT images
INTERMEDIATE_IMAGE_MODE = 'F'  # PIL/Pillow image mode for intermediate images
INTERMEDIATE_NAN = 0  # "no value" value to use
OUT_DTYPE = np.uint8