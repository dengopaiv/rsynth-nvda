import sys
from setuptools import setup, Extension

extra_compile_args = []
if sys.platform == 'win32':
    extra_compile_args = ['/O2']
else:
    extra_compile_args = ['-O2', '-ffast-math']

klatt_ext = Extension(
    '_rsynth._klatt_c',
    sources=[
        '_rsynth/_klatt_c/klatt_module.c',
        '_rsynth/_klatt_c/resonator.c',
        '_rsynth/_klatt_c/voice_gen.c',
        '_rsynth/_klatt_c/filter_chain.c',
    ],
    include_dirs=['_rsynth/_klatt_c'],
    extra_compile_args=extra_compile_args,
)

setup(
    name='rsynth',
    version='2.0.0',
    ext_modules=[klatt_ext],
    packages=['_rsynth'],
)
