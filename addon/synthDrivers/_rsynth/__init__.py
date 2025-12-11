"""
RSynth - Python port of the RSynth Klatt formant synthesizer

This package provides a complete text-to-speech pipeline:
- text2phone.py: Text to SAMPA phonemes
- phonemes.py: Phonemes to element sequences
- elements.py: Element definitions with formant parameters
- klatt.py: Klatt formant synthesizer

Original RSynth code copyright (c) 1994-2004 Nick Ing-Simmons, LGPL licensed.
"""

from .klatt import KlattSynth, Speaker, Param, VOICE_IMPULSIVE, VOICE_NATURAL
from .elements import ELEMENTS, ELEMENT_LIST, Element
from .phonemes import phonemes_to_elements, FrameGenerator
from .text2phone import text_to_phonemes

__all__ = [
    'KlattSynth',
    'Speaker',
    'Param',
    'VOICE_IMPULSIVE',
    'VOICE_NATURAL',
    'ELEMENTS',
    'ELEMENT_LIST',
    'Element',
    'phonemes_to_elements',
    'FrameGenerator',
    'text_to_phonemes',
]

__version__ = '1.1.0'
