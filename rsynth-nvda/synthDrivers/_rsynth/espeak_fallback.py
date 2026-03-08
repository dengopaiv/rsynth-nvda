"""
eSpeak Fallback for RSynth

Provides phoneme lookup using eSpeak-NG as a fallback when CMU dictionary
doesn't contain a word. Uses ctypes to call libespeak-ng directly.

eSpeak is bundled with NVDA, so this should work on NVDA systems.
"""

import ctypes
import os
from typing import Optional
from functools import lru_cache


class EspeakFallback:
    """
    Fallback phoneme lookup using eSpeak-NG.

    eSpeak provides broader vocabulary coverage than CMU dictionary,
    especially for:
    - Proper nouns and names
    - Technical terms
    - Foreign words
    - Neologisms
    """

    # eSpeak phoneme mode flags
    PHONEMES_IPA = 0x02
    PHONEMES_XSAMPA = 0x10  # X-SAMPA output

    # Phoneme conversion: eSpeak X-SAMPA -> RSynth SAMPA
    # Most are direct matches, but some need adjustment
    PHONEME_MAP = {
        # Vowels - mostly direct matches
        'i:': 'i',      # fleece
        'I': 'I',       # kit
        'e': 'e',       # dress (some dialects)
        'E': 'e',       # dress
        '{': '{',       # trap
        'A:': 'A',      # palm/father
        'Q': 'Q',       # lot (British)
        'O:': 'O',      # thought
        'U': 'U',       # foot
        'u:': 'u',      # goose
        'V': 'V',       # strut
        '@': '@',       # schwa (comma)
        '3:': '3',      # nurse
        '3': '3',       # nurse (unstressed)

        # Diphthongs
        'eI': 'eI',     # face
        'aI': 'aI',     # price
        'OI': 'OI',     # choice
        '@U': '@U',     # goat
        'aU': 'aU',     # mouth
        'I@': 'I@',     # near
        'e@': 'e@',     # square
        'U@': 'U@',     # cure

        # Consonants - direct matches
        'p': 'p', 'b': 'b', 't': 't', 'd': 'd', 'k': 'k', 'g': 'g',
        'f': 'f', 'v': 'v', 'T': 'T', 'D': 'D', 's': 's', 'z': 'z',
        'S': 'S', 'Z': 'Z', 'h': 'h',
        'm': 'm', 'n': 'n', 'N': 'N',
        'l': 'l', 'r': 'r', 'w': 'w', 'j': 'j',

        # Affricates
        'tS': 'tS',     # church
        'dZ': 'dZ',     # judge

        # Syllabic consonants
        'l=': 'l=',     # bottle
        'n=': 'n=',     # button
        'm=': 'm=',     # bottom

        # Glottal stop
        '?': '?',

        # R-colored vowels (American)
        '@r': '3',      # letter (rhotic schwa)
        '3r': '3',      # nurse (rhotic)

        # Stress markers - eSpeak uses ' for primary, , for secondary
        "'": "'",       # primary stress
        ',': ',',       # secondary stress
        '%': ',',       # alternate secondary stress marker
    }

    def __init__(self):
        """Initialize eSpeak fallback."""
        self._lib = None
        self._initialized = False
        self._load_espeak()

    def _load_espeak(self):
        """Try to load eSpeak-NG library."""
        # Common locations for eSpeak-NG DLL
        possible_paths = [
            # NVDA bundled location
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'NVDA', 'synthDrivers', 'espeak-ng.dll'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'NVDA', 'synthDrivers', 'espeak-ng.dll'),
            # Standalone eSpeak installation
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'eSpeak NG', 'libespeak-ng.dll'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'eSpeak NG', 'libespeak-ng.dll'),
            # System PATH
            'espeak-ng.dll',
            'libespeak-ng.dll',
        ]

        for path in possible_paths:
            try:
                self._lib = ctypes.CDLL(path)
                break
            except OSError:
                continue

        if self._lib is None:
            return

        # Initialize eSpeak
        try:
            # espeak_Initialize(output, buflength, path, options)
            # output=0 means no audio output (just phoneme conversion)
            self._lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
            self._lib.espeak_Initialize.restype = ctypes.c_int

            # espeak_SetVoiceByName
            self._lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
            self._lib.espeak_SetVoiceByName.restype = ctypes.c_int

            # espeak_TextToPhonemes
            self._lib.espeak_TextToPhonemes.argtypes = [
                ctypes.POINTER(ctypes.c_void_p),  # textptr
                ctypes.c_int,                      # textmode
                ctypes.c_int                       # phonememode
            ]
            self._lib.espeak_TextToPhonemes.restype = ctypes.c_char_p

            # Initialize with no audio output
            result = self._lib.espeak_Initialize(0, 0, None, 0)
            if result < 0:
                self._lib = None
                return

            # Set to English voice
            self._lib.espeak_SetVoiceByName(b'en')
            self._initialized = True

        except Exception:
            self._lib = None

    @property
    def available(self) -> bool:
        """Check if eSpeak is available."""
        return self._initialized

    @lru_cache(maxsize=1000)
    def lookup(self, word: str) -> Optional[str]:
        """
        Look up phonemes for a word using eSpeak.

        Args:
            word: Word to look up

        Returns:
            SAMPA phoneme string, or None if lookup fails
        """
        if not self._initialized:
            return None

        try:
            # Prepare text buffer
            text = word.encode('utf-8') + b'\0'
            text_ptr = ctypes.c_void_p(ctypes.cast(ctypes.c_char_p(text), ctypes.c_void_p).value)
            text_ptr_ref = ctypes.pointer(text_ptr)

            # Get phonemes in X-SAMPA format
            # textmode=1 means UTF-8 input
            # phonememode with PHONEMES_XSAMPA flag
            result = self._lib.espeak_TextToPhonemes(
                text_ptr_ref,
                1,  # UTF-8
                self.PHONEMES_XSAMPA
            )

            if result:
                raw_phonemes = result.decode('utf-8', errors='ignore').strip()
                return self._convert_phonemes(raw_phonemes)

        except Exception:
            pass

        return None

    def _convert_phonemes(self, espeak_phonemes: str) -> str:
        """
        Convert eSpeak X-SAMPA to RSynth SAMPA format.

        Args:
            espeak_phonemes: Phoneme string from eSpeak

        Returns:
            RSynth-compatible SAMPA string
        """
        result = []
        i = 0
        n = len(espeak_phonemes)

        while i < n:
            matched = False

            # Try matching longer sequences first (2 chars, then 1)
            for length in [2, 1]:
                if i + length <= n:
                    chunk = espeak_phonemes[i:i+length]
                    if chunk in self.PHONEME_MAP:
                        result.append(self.PHONEME_MAP[chunk])
                        i += length
                        matched = True
                        break

            if not matched:
                # Skip unknown characters (like tie bars, length markers)
                char = espeak_phonemes[i]
                # Keep spaces and basic punctuation
                if char in ' -':
                    result.append(char)
                # Skip eSpeak-specific markers we don't use
                elif char not in '_:ˈˌ':
                    # Unknown phoneme - pass through
                    result.append(char)
                i += 1

        return ''.join(result)


# Global instance
_espeak = None


def get_espeak() -> EspeakFallback:
    """Get the global eSpeak fallback instance."""
    global _espeak
    if _espeak is None:
        _espeak = EspeakFallback()
    return _espeak


def espeak_lookup(word: str) -> Optional[str]:
    """
    Look up phonemes using eSpeak fallback.

    Args:
        word: Word to look up

    Returns:
        SAMPA phoneme string, or None if eSpeak unavailable or lookup fails
    """
    espeak = get_espeak()
    if espeak.available:
        return espeak.lookup(word)
    return None
