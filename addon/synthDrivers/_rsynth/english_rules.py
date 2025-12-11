"""
Minimal English letter-to-sound rules for fallback pronunciation.

Used when words are not found in the CMU dictionary.
Simplified from the full NRL Report 7948 rules to ~100 lines.
"""

from typing import Optional

# Simple letter to phoneme mappings
# Used as fallback when CMU dictionary lookup fails

CONSONANTS = {
    'b': 'b',
    'c': 'k',  # default, 's' before e/i/y handled below
    'd': 'd',
    'f': 'f',
    'g': 'g',  # default, 'dZ' before e/i/y handled below
    'h': 'h',
    'j': 'dZ',
    'k': 'k',
    'l': 'l',
    'm': 'm',
    'n': 'n',
    'p': 'p',
    'q': 'k',
    'r': 'r',
    's': 's',
    't': 't',
    'v': 'v',
    'w': 'w',
    'x': 'ks',
    'z': 'z',
}

VOWELS = {
    'a': '{',   # short a (cat)
    'e': 'e',   # short e (bed)
    'i': 'I',   # short i (bit)
    'o': 'Q',   # short o (hot)
    'u': 'V',   # short u (cup)
}

# Common digraphs and combinations
DIGRAPHS = {
    'ch': 'tS',
    'sh': 'S',
    'th': 'T',  # voiceless (think)
    'ph': 'f',
    'wh': 'w',
    'ck': 'k',
    'ng': 'N',
    'gh': '',   # silent in most words
    'kn': 'n',  # silent k
    'wr': 'r',  # silent w
    'qu': 'kw',
    'dg': 'dZ',
}

# Common vowel combinations
VOWEL_COMBOS = {
    'ai': 'eI',
    'ay': 'eI',
    'ea': 'i',
    'ee': 'i',
    'ei': 'i',
    'ey': 'i',
    'ie': 'i',
    'oa': '@U',
    'oo': 'u',
    'ou': 'aU',
    'ow': 'aU',
    'oi': 'OI',
    'oy': 'OI',
    'au': 'O',
    'aw': 'O',
    'ew': 'ju',
}

# Common endings
ENDINGS = {
    'tion': 'S@n',
    'sion': 'Z@n',
    'ture': 'tS@',
    'sure': 'Z@',
    'ous': '@s',
    'ious': 'i@s',
    'ing': 'IN',
    'ed': 'd',
    'es': 'Iz',
    'er': '@',
    'est': 'Ist',
    'ly': 'li',
    'le': '@l',
    'al': '@l',
    'ful': 'fUl',
    'ness': 'n@s',
    'ment': 'm@nt',
    'able': '@b@l',
    'ible': '@b@l',
}


def apply_rules(word: str) -> str:
    """
    Apply simple letter-to-sound rules to convert a word to phonemes.

    This is a simplified fallback for words not in the CMU dictionary.

    Args:
        word: Input word (lowercase)

    Returns:
        SAMPA phoneme string
    """
    word = word.lower().strip()
    if not word:
        return ''

    result = []
    i = 0
    n = len(word)

    while i < n:
        matched = False

        # Try common endings first (at end of word)
        if i > 0:
            remaining = word[i:]
            for ending, phoneme in ENDINGS.items():
                if remaining == ending:
                    result.append(phoneme)
                    i = n
                    matched = True
                    break

        if matched:
            continue

        # Try digraphs (2-letter combinations)
        if i < n - 1:
            digraph = word[i:i+2]
            if digraph in DIGRAPHS:
                result.append(DIGRAPHS[digraph])
                i += 2
                continue

        # Try vowel combinations
        if i < n - 1:
            combo = word[i:i+2]
            if combo in VOWEL_COMBOS:
                result.append(VOWEL_COMBOS[combo])
                i += 2
                continue

        # Single letter handling
        c = word[i]

        # Special consonant rules
        if c == 'c' and i < n - 1 and word[i+1] in 'eiy':
            result.append('s')  # soft c
            i += 1
            continue

        if c == 'g' and i < n - 1 and word[i+1] in 'eiy':
            result.append('dZ')  # soft g
            i += 1
            continue

        if c == 'y':
            if i == 0:
                result.append('j')  # consonant y at start
            else:
                result.append('i')  # vowel y elsewhere
            i += 1
            continue

        # Standard consonants
        if c in CONSONANTS:
            result.append(CONSONANTS[c])
            i += 1
            continue

        # Standard vowels
        if c in VOWELS:
            result.append(VOWELS[c])
            i += 1
            continue

        # Skip unknown characters
        i += 1

    return ''.join(result)
