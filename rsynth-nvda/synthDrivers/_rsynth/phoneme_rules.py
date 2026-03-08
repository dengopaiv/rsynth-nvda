"""
Phoneme Rewriting Rules for RSynth

Applies context-sensitive transformations to phonemes after dictionary lookup.
Based on SAM's parser.py rules, adapted for SAMPA phoneme format.

These rules improve pronunciation naturalness by applying coarticulation effects.
"""

import re
from typing import List, Tuple

# SAMPA vowels for context matching
VOWELS = set('iIeE{VQ@aAoOuU23')
VOWEL_PATTERN = '[iIeE{VQ@aAoOuU23]'

# Stressed vowel markers
STRESS_MARKERS = set("',+")


def apply_phoneme_rules(phonemes: str) -> str:
    """
    Apply context-sensitive phoneme rewriting rules.

    Transforms phonemes to sound more natural by applying:
    - Affrication: TR -> tS, DR -> dZ
    - Rhoticization: Vowel + r -> rhotacized vowel
    - Flapping: T/D between vowels -> flap
    - Syllabic consonants: schwa + l/m/n -> syllabic

    Args:
        phonemes: SAMPA phoneme string with stress markers

    Returns:
        Transformed phoneme string
    """
    if not phonemes:
        return phonemes

    # Apply rules in sequence
    result = phonemes

    # 1. Affrication: tr -> tSr (more natural "tree" sound)
    #    Note: SAM does TR -> CH but we keep the r for continuity
    result = re.sub(r'\btr', 'tSr', result)
    result = re.sub(r'\bdr', 'dZr', result)

    # 2. T/D flapping between vowels (American English) - DISABLED
    #    butter -> bV4@, ladder -> l{4@
    #    The flap sound (4 or D in SAMPA) replaces t/d between vowels
    # result = _apply_flapping(result)

    # 3. Syllabic consonants
    #    @l -> l= (bottle -> bQtl=)
    #    @n -> n= (button -> bVtn=)
    #    @m -> m= (bottom -> bQtm=)
    result = re.sub(r'@l\b', 'l=', result)
    result = re.sub(r'@n\b', 'n=', result)
    result = re.sub(r'@m\b', 'm=', result)

    # 4. Glottal stop insertion before word-final voiceless stops
    #    This is optional - some dialects use it
    # result = re.sub(r'([iIeE{VQ@aAoOuU23])([ptk])\b', r'\1?\2', result)

    return result


def _apply_flapping(phonemes: str) -> str:
    """
    Apply t/d flapping rule.

    In American English, /t/ and /d/ become a flap [4] (alveolar tap)
    when occurring between vowels and the following vowel is unstressed.

    Examples:
    - butter -> bV43 (flaps: V before, unstressed 3 after)
    - water -> wO43 (flaps: O before, unstressed 3 after)
    - city -> sI4i (flaps: I before, unstressed i after)
    - attack -> @t{k (NO flap: t precedes stressed vowel)
    """
    # Split into tokens (phonemes and stress markers)
    tokens = _tokenize_phonemes(phonemes)
    result = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Check for t or d that might need flapping
        if token in ('t', 'd'):
            # Look for vowel before
            has_vowel_before = False
            j = i - 1
            while j >= 0:
                if tokens[j] in VOWELS:
                    has_vowel_before = True
                    break
                elif tokens[j] in STRESS_MARKERS or tokens[j] == ' ':
                    j -= 1
                else:
                    break

            # Look for vowel after (must be unstressed)
            has_unstressed_vowel_after = False
            k = i + 1
            while k < len(tokens):
                if tokens[k] == "'":
                    # Primary stress coming - don't flap
                    break
                elif tokens[k] in VOWELS:
                    has_unstressed_vowel_after = True
                    break
                elif tokens[k] in (',', '+', ' '):
                    k += 1
                else:
                    break

            # Flap when intervocalic and following vowel is unstressed
            if has_vowel_before and has_unstressed_vowel_after:
                result.append('4')  # Flap (alveolar tap)
            else:
                result.append(token)
        else:
            result.append(token)

        i += 1

    return ''.join(result)


def _tokenize_phonemes(phonemes: str) -> List[str]:
    """
    Tokenize a SAMPA phoneme string into individual phonemes and markers.

    Handles:
    - Multi-character phonemes (tS, dZ, etc.)
    - Stress markers (', ,, +)
    - Spaces
    """
    tokens = []
    i = 0
    n = len(phonemes)

    # Multi-character phonemes to check
    digraphs = {'tS', 'dZ', 'eI', 'aI', 'OI', 'aU', '@U', 'I@', 'e@', 'U@'}

    while i < n:
        # Check for digraphs first
        if i < n - 1:
            pair = phonemes[i:i+2]
            if pair in digraphs:
                tokens.append(pair)
                i += 2
                continue

        # Single character
        tokens.append(phonemes[i])
        i += 1

    return tokens


def apply_coarticulation(phonemes: str) -> str:
    """
    Apply coarticulation effects for more natural speech.

    This is a lighter-weight version that just smooths transitions.
    """
    # Nasal assimilation: n before p/b -> m, n before k/g -> N
    result = re.sub(r'n([pb])', r'm\1', phonemes)
    result = re.sub(r'n([kg])', r'N\1', result)

    return result
