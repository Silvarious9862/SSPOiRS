from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
    Extension(
        "src.handlers_udp._download_core",
        ["src/handlers_udp/_download_core.pyx"],
    ),
]

setup(
    name="udp_download_core",
    ext_modules=cythonize(
        extensions,
        language_level=3,
    ),
)