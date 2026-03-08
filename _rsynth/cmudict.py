"""
CMU Pronouncing Dictionary Interface for RSynth

Loads the CMU dictionary and converts ARPAbet phonemes to SAMPA format.
The CMU dictionary contains ~130,000 English word pronunciations.

Dictionary source: http://www.speech.cs.cmu.edu/cgi-bin/cmudict
"""

import os
import sys
from typing import Optional, Dict

# ARPAbet to SAMPA phoneme mapping
# CMU uses ARPAbet with stress markers (0=no stress, 1=primary, 2=secondary)
ARPABET_TO_SAMPA = {
    # Vowels - stress markers stripped, we add our own
    'AA': 'A',    # odd -> A
    'AE': '{',    # at -> {
    'AH': '@',    # unstressed schwa (stressed AH handled specially)
    'AO': 'O',    # ought -> O
    'AW': 'aU',   # cow -> aU
    'AY': 'aI',   # hide -> aI
    'EH': 'e',    # Ed -> e
    'ER': '3',    # hurt -> 3
    'EY': 'eI',   # ate -> eI
    'IH': 'I',    # it -> I
    'IY': 'i',    # eat -> i
    'OW': '@U',   # oat -> @U
    'OY': 'OI',   # toy -> OI
    'UH': 'U',    # hood -> U
    'UW': 'u',    # two -> u

    # Consonants
    'B': 'b',
    'CH': 'tS',
    'D': 'd',
    'DH': 'D',
    'F': 'f',
    'G': 'g',
    'HH': 'h',
    'JH': 'dZ',
    'K': 'k',
    'L': 'l',
    'M': 'm',
    'N': 'n',
    'NG': 'N',
    'P': 'p',
    'R': 'r',
    'S': 's',
    'SH': 'S',
    'T': 't',
    'TH': 'T',
    'V': 'v',
    'W': 'w',
    'Y': 'j',
    'Z': 'z',
    'ZH': 'Z',
}


class CMUDict:
    """
    CMU Pronouncing Dictionary with ARPAbet to SAMPA conversion.
    """

    def __init__(self, dict_path: Optional[str] = None):
        """
        Initialize CMU dictionary.

        Args:
            dict_path: Path to CMU dict file. If None, searches for bundled dict.
        """
        self._dict: Dict[str, str] = {}
        self._loaded = False

        if dict_path is None:
            dict_path = self._find_dict()

        if dict_path and os.path.exists(dict_path):
            self._load(dict_path)

    def _find_dict(self) -> Optional[str]:
        """Find bundled CMU dictionary file."""
        # Handle PyInstaller frozen executables
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running as frozen executable - data is in _MEIPASS
            base_dir = sys._MEIPASS
            module_dir = os.path.join(base_dir, '_rsynth')
        else:
            # Running as script or NVDA addon - use __file__ location
            module_dir = os.path.dirname(os.path.abspath(__file__))

        candidates = [
            os.path.join(module_dir, 'cmudict.txt'),
            os.path.join(module_dir, 'cmudict.dict'),
            os.path.join(module_dir, '..', 'cmudict.txt'),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _load(self, path: str):
        """
        Load CMU dictionary from file.

        Format: WORD P1 P2 P3 ...
        Lines starting with ;;; are comments.
        Words with multiple pronunciations have (2), (3), etc.
        """
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(';;;'):
                        continue

                    # Split on first space - word is first token, rest are phonemes
                    parts = line.split(' ', 1)
                    if len(parts) != 2:
                        continue

                    word = parts[0].strip().upper()
                    phonemes = parts[1].strip()

                    # Remove variant markers like (2), (3)
                    if '(' in word:
                        word = word.split('(')[0]

                    # Only keep first pronunciation for each word
                    if word not in self._dict:
                        sampa = self._convert_to_sampa(phonemes)
                        if sampa:
                            self._dict[word] = sampa

            self._loaded = True
        except Exception as e:
            self._loaded = False

    def _convert_to_sampa(self, arpabet: str) -> str:
        """
        Convert ARPAbet phoneme string to SAMPA.

        Args:
            arpabet: Space-separated ARPAbet phonemes (e.g., "HH AH0 L OW1")

        Returns:
            SAMPA phoneme string with stress markers
        """
        result = []
        phonemes = arpabet.split()

        for ph in phonemes:
            # Extract stress marker (0, 1, 2) from end of vowels
            stress = ''
            stress_level = 0  # Default: unstressed
            if ph and ph[-1].isdigit():
                stress_level = int(ph[-1])
                ph = ph[:-1]  # Remove stress digit
                if stress_level == 1:
                    stress = "'"  # Primary stress
                elif stress_level == 2:
                    stress = ","  # Secondary stress

            # Convert to SAMPA
            # Special case: stressed AH uses strut vowel 'V', unstressed uses schwa '@'
            if ph == 'AH' and stress_level > 0:
                sampa = 'V'  # Strut vowel for stressed AH (love, dove)
            else:
                sampa = ARPABET_TO_SAMPA.get(ph, '')
            if sampa:
                if stress:
                    result.append(stress + sampa)
                else:
                    result.append(sampa)

        return ''.join(result)

    def lookup(self, word: str) -> Optional[str]:
        """
        Look up word pronunciation.

        Args:
            word: Word to look up

        Returns:
            SAMPA phoneme string, or None if not found
        """
        return self._dict.get(word.upper())

    def __contains__(self, word: str) -> bool:
        """Check if word is in dictionary."""
        return word.upper() in self._dict

    def __len__(self) -> int:
        """Return number of words in dictionary."""
        return len(self._dict)

    @property
    def loaded(self) -> bool:
        """Check if dictionary was loaded successfully."""
        return self._loaded


# Global dictionary instance (lazy loaded)
_cmu_dict: Optional[CMUDict] = None


def get_cmu_dict() -> CMUDict:
    """Get the global CMU dictionary instance."""
    global _cmu_dict
    if _cmu_dict is None:
        _cmu_dict = CMUDict()
    return _cmu_dict


def cmu_lookup(word: str) -> Optional[str]:
    """
    Look up word in CMU dictionary.

    Args:
        word: Word to look up

    Returns:
        SAMPA phoneme string, or None if not found
    """
    return get_cmu_dict().lookup(word)
