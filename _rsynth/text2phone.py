"""
Text-to-Phoneme Conversion for RSynth

Converts English text to SAMPA phonemes using:
1. CMU Pronouncing Dictionary (primary)
2. Simple letter-to-sound rules (fallback)

Includes context-aware numeral processing for years, phone numbers, prices, etc.

Phonemes are in SAMPA format.
"""

import re
from typing import List, Tuple, Optional

from .cmudict import cmu_lookup, get_cmu_dict
from .english_rules import apply_rules
from .phoneme_rules import apply_phoneme_rules
from .espeak_fallback import espeak_lookup


# Number word tables for NumeralProcessor
ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
        'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
        'seventeen', 'eighteen', 'nineteen']
TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
ORDINALS = {
    '1': 'first', '2': 'second', '3': 'third', '4': 'fourth', '5': 'fifth',
    '6': 'sixth', '7': 'seventh', '8': 'eighth', '9': 'ninth', '10': 'tenth',
    '11': 'eleventh', '12': 'twelfth', '13': 'thirteenth', '14': 'fourteenth',
    '15': 'fifteenth', '16': 'sixteenth', '17': 'seventeenth', '18': 'eighteenth',
    '19': 'nineteenth', '20': 'twentieth', '30': 'thirtieth', '40': 'fortieth',
    '50': 'fiftieth', '60': 'sixtieth', '70': 'seventieth', '80': 'eightieth',
    '90': 'ninetieth', '100': 'hundredth', '1000': 'thousandth'
}


class NumeralProcessor:
    """
    Context-aware numeral to text conversion.

    Detects and appropriately converts:
    - Years: 2024 -> "twenty twenty-four"
    - Phone numbers: 555-1234 -> "five five five, one two three four"
    - Prices: $19.99 -> "nineteen dollars and ninety-nine cents"
    - Ordinals: 1st, 2nd -> "first", "second"
    - Plain numbers: 42 -> "forty-two"
    - Large numbers: 1,234 -> "one thousand two hundred thirty-four"
    """

    # Pattern for years (1800-2099)
    YEAR_PATTERN = re.compile(r'\b(1[89]\d{2}|20\d{2})\b')
    YEAR_CONTEXT_BEFORE = {'in', 'year', 'since', 'from', 'to', 'by', 'around', 'circa', 'during', 'until', 'before', 'after'}
    YEAR_CONTEXT_AFTER = {'ad', 'bc', 'ce', 'bce'}

    # Phone number patterns
    PHONE_PATTERNS = [
        re.compile(r'\((\d{3})\)\s*(\d{3})[-.\s]?(\d{4})'),  # (555) 123-4567
        re.compile(r'\b(\d{3})[-.\s](\d{3})[-.\s](\d{4})\b'),  # 555-123-4567
        re.compile(r'\b(\d{3})[-.\s](\d{4})\b'),  # 555-1234
    ]

    # Price pattern
    PRICE_PATTERN = re.compile(r'\$(\d+)(?:\.(\d{2}))?')

    # Ordinal pattern (1st, 2nd, 3rd, 4th, etc.)
    ORDINAL_PATTERN = re.compile(r'\b(\d+)(st|nd|rd|th)\b', re.IGNORECASE)

    # Number with commas
    COMMA_NUMBER_PATTERN = re.compile(r'\b(\d{1,3}(?:,\d{3})+)\b')

    # Decade plurals (90s, 80s, etc.)
    DECADE_PATTERN = re.compile(r'\b([1-9])0s\b', re.IGNORECASE)
    DECADE_WORDS = {
        '1': 'tens',
        '2': 'twenties',
        '3': 'thirties',
        '4': 'forties',
        '5': 'fifties',
        '6': 'sixties',
        '7': 'seventies',
        '8': 'eighties',
        '9': 'nineties',
    }

    # Plain number
    PLAIN_NUMBER_PATTERN = re.compile(r'\b(\d+)\b')

    @classmethod
    def process_text(cls, text: str) -> str:
        """
        Process text, converting all numerals to speakable words.

        Args:
            text: Input text with numerals

        Returns:
            Text with numerals converted to words
        """
        # Process in order of specificity (most specific patterns first)

        # 1. Prices
        text = cls.PRICE_PATTERN.sub(cls._format_price, text)

        # 2. Phone numbers
        for pattern in cls.PHONE_PATTERNS:
            text = pattern.sub(cls._format_phone, text)

        # 3. Ordinals
        text = cls.ORDINAL_PATTERN.sub(cls._format_ordinal, text)

        # 4. Years (with context awareness)
        text = cls._process_years(text)

        # 5. Decade plurals (90s, 80s, etc.)
        text = cls.DECADE_PATTERN.sub(cls._format_decade, text)

        # 6. Numbers with commas
        text = cls.COMMA_NUMBER_PATTERN.sub(lambda m: cls._number_to_words(int(m.group(1).replace(',', ''))), text)

        # 7. Remaining plain numbers
        text = cls.PLAIN_NUMBER_PATTERN.sub(lambda m: cls._number_to_words(int(m.group(1))), text)

        return text

    @classmethod
    def _format_price(cls, match) -> str:
        """Format price: $19.99 -> 'nineteen dollars and ninety-nine cents'"""
        dollars = int(match.group(1))
        cents = match.group(2)

        if cents:
            cents_val = int(cents)
            if cents_val == 0:
                return f"{cls._number_to_words(dollars)} dollars"
            elif dollars == 0:
                return f"{cls._number_to_words(cents_val)} cents"
            else:
                return f"{cls._number_to_words(dollars)} dollars and {cls._number_to_words(cents_val)} cents"
        else:
            if dollars == 1:
                return "one dollar"
            return f"{cls._number_to_words(dollars)} dollars"

    @classmethod
    def _format_phone(cls, match) -> str:
        """Format phone number: 555-1234 -> 'five five five, one two three four'"""
        groups = match.groups()
        result_parts = []

        for group in groups:
            if group:
                # Spell each digit
                digits = ' '.join(cls._digit_to_word(d) for d in group)
                result_parts.append(digits)

        return ', '.join(result_parts)

    @classmethod
    def _format_decade(cls, match) -> str:
        """Format decade plural: 90s -> 'nineties'"""
        digit = match.group(1)
        return cls.DECADE_WORDS.get(digit, f"{digit}0s")

    @classmethod
    def _format_ordinal(cls, match) -> str:
        """Format ordinal: 1st -> 'first', 23rd -> 'twenty-third'"""
        num_str = match.group(1)
        num = int(num_str)

        # Check if we have a direct ordinal
        if num_str in ORDINALS:
            return ORDINALS[num_str]

        # For compound numbers like 21st, 32nd
        if num < 100:
            tens = (num // 10) * 10
            ones = num % 10

            if ones == 0:
                # 20th, 30th, etc.
                return ORDINALS.get(str(tens), cls._number_to_words(num) + 'th')
            else:
                # 21st, 32nd, etc.
                tens_word = TENS[tens // 10]
                ones_ordinal = ORDINALS.get(str(ones), str(ones) + 'th')
                return f"{tens_word}-{ones_ordinal}"

        # For larger numbers, append 'th' to the cardinal
        return cls._number_to_words(num) + 'th'

    @classmethod
    def _process_years(cls, text: str) -> str:
        """Process years with context awareness."""
        def replace_year(match):
            year_str = match.group(1)
            start, end = match.span()

            # Get surrounding context
            before = text[:start].lower().split()
            after = text[end:].lower().split()

            word_before = before[-1] if before else ''
            word_after = after[0] if after else ''

            # Clean punctuation
            word_before = word_before.strip('.,;:!?')
            word_after = word_after.strip('.,;:!?')

            # Check if context suggests it's a year
            is_year = (
                word_before in cls.YEAR_CONTEXT_BEFORE or
                word_after in cls.YEAR_CONTEXT_AFTER
            )

            # Default: treat 4-digit numbers in typical year range as years
            year = int(year_str)
            if 1800 <= year <= 2099:
                is_year = True

            if is_year:
                return cls._year_to_words(year)
            else:
                return cls._number_to_words(year)

        return cls.YEAR_PATTERN.sub(replace_year, text)

    @classmethod
    def _year_to_words(cls, year: int) -> str:
        """Convert year to words: 2024 -> 'twenty twenty-four'"""
        if year == 2000:
            return "two thousand"
        elif 2001 <= year <= 2009:
            return f"two thousand {ONES[year - 2000]}"
        elif 2010 <= year <= 2019:
            return f"twenty {ONES[year - 2010]}" if year > 2010 else "twenty ten"
        elif year >= 2020:
            # 2024 -> "twenty twenty-four", 2100 -> "twenty-one hundred"
            first_half = year // 100
            second_half = year % 100
            first_word = cls._two_digit_to_words(first_half)
            if second_half == 0:
                return f"{first_word} hundred"
            second_word = cls._two_digit_to_words(second_half)
            return f"{first_word} {second_word}"
        elif 1900 <= year <= 1999:
            # 1984 -> "nineteen eighty-four", 1900 -> "nineteen hundred"
            first_half = year // 100
            second_half = year % 100
            first_word = cls._two_digit_to_words(first_half)
            if second_half == 0:
                return f"{first_word} hundred"
            second_word = cls._two_digit_to_words(second_half)
            return f"{first_word} {second_word}"
        elif 1800 <= year <= 1899:
            # 1850 -> "eighteen fifty", 1800 -> "eighteen hundred"
            first_half = year // 100
            second_half = year % 100
            first_word = cls._two_digit_to_words(first_half)
            if second_half == 0:
                return f"{first_word} hundred"
            second_word = cls._two_digit_to_words(second_half)
            return f"{first_word} {second_word}"
        else:
            return cls._number_to_words(year)

    @classmethod
    def _two_digit_to_words(cls, n: int) -> str:
        """Convert two-digit number to words."""
        if n == 0:
            return "zero"
        elif n < 20:
            return ONES[n]
        else:
            tens = n // 10
            ones = n % 10
            if ones == 0:
                return TENS[tens]
            else:
                return f"{TENS[tens]}-{ONES[ones]}"

    @classmethod
    def _number_to_words(cls, n: int) -> str:
        """Convert integer to English words."""
        if n == 0:
            return "zero"
        if n < 0:
            return "negative " + cls._number_to_words(-n)

        if n < 20:
            return ONES[n]
        elif n < 100:
            tens = n // 10
            ones = n % 10
            if ones == 0:
                return TENS[tens]
            return f"{TENS[tens]}-{ONES[ones]}"
        elif n < 1000:
            hundreds = n // 100
            remainder = n % 100
            result = f"{ONES[hundreds]} hundred"
            if remainder > 0:
                result += f" {cls._number_to_words(remainder)}"
            return result
        elif n < 1000000:
            thousands = n // 1000
            remainder = n % 1000
            result = f"{cls._number_to_words(thousands)} thousand"
            if remainder > 0:
                result += f" {cls._number_to_words(remainder)}"
            return result
        elif n < 1000000000:
            millions = n // 1000000
            remainder = n % 1000000
            result = f"{cls._number_to_words(millions)} million"
            if remainder > 0:
                result += f" {cls._number_to_words(remainder)}"
            return result
        else:
            billions = n // 1000000000
            remainder = n % 1000000000
            result = f"{cls._number_to_words(billions)} billion"
            if remainder > 0:
                result += f" {cls._number_to_words(remainder)}"
            return result

    @classmethod
    def _digit_to_word(cls, d: str) -> str:
        """Convert single digit to word."""
        digits = {
            '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
            '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine'
        }
        return digits.get(d, d)

# Letter names for spelling unknown words
LETTER_NAMES = {
    'A': 'eI', 'B': 'bi', 'C': 'si', 'D': 'di', 'E': 'i',
    'F': 'ef', 'G': 'dZi', 'H': 'eItS', 'I': 'aI', 'J': 'dZeI',
    'K': 'keI', 'L': 'el', 'M': 'em', 'N': 'en', 'O': '@U',
    'P': 'pi', 'Q': 'kju', 'R': 'A', 'S': 'es', 'T': 'ti',
    'U': 'ju', 'V': 'vi', 'W': 'dVb@lju', 'X': 'eks', 'Y': 'waI',
    'Z': 'zed',
}

# Digit pronunciations
DIGITS = {
    '0': 'zI@r@U',
    '1': 'wVn',
    '2': 'tu',
    '3': 'Tri',
    '4': 'fO',
    '5': 'faIv',
    '6': 'sIks',
    '7': 'sev@n',
    '8': 'eIt',
    '9': 'naIn',
}

# Common abbreviations and special words
SPECIAL_WORDS = {
    # Screen readers and accessibility
    'nvda': 'en vi di eI',
    'jaws': 'dZOz',
    'orca': 'Ork@',

    # Words with tricky pronunciations (avoid flapping errors)
    'untitled': "Vn'taIt@ld",
    'entitled': "In'taIt@ld",
    'title': "'taIt@l",
    'titled': "'taIt@ld",

    # Common abbreviations
    'ok': '@U keI',
    'vs': 'v3s@s',
    'etc': 'et set@r@',
    'ie': 'D{t Iz',
    'eg': 'fO Igz{mp@l',
    'asap': 'eI es eI pi',
    'fyi': 'fO jO Inf@meIS@n',
    'btw': 'baI D@ weI',
    'diy': 'du It jOself',
    'faq': 'ef eI kju',

    # Tech terms - web
    'http': 'eItS ti ti pi',
    'https': 'eItS ti ti pi es',
    'url': 'ju Ar el',
    'html': 'eItS ti em el',
    'css': 'si es es',
    'xml': 'eks em el',
    'json': 'dZeIs@n',
    'ajax': 'eIdZ{ks',

    # Tech terms - programming
    'api': 'eI pi aI',
    'gui': 'gu i',
    'cli': 'si el aI',
    'ide': 'aI di i',
    'sdk': 'es di keI',
    'npm': 'en pi em',
    'git': 'gIt',
    'github': 'gIt hVb',
    'sql': 'sikw@l',
    'nosql': 'n@U sikw@l',

    # Tech terms - hardware
    'wifi': 'waI faI',
    'usb': 'ju es bi',
    'cpu': 'si pi ju',
    'gpu': 'dZi pi ju',
    'ram': 'r{m',
    'ssd': 'es es di',
    'hdd': 'eItS di di',
    'hdmi': 'eItS di em aI',
    'led': 'el i di',
    'lcd': 'el si di',

    # Operating systems
    'ios': 'aI @U es',
    'macos': 'm{k @U es',
    'linux': 'lIn@ks',
    'unix': 'jun@ks',
    'ubuntu': 'ubuntu',
    'debian': 'debi@n',

    # File formats
    'pdf': 'pi di ef',
    'jpg': 'dZeI peg',
    'jpeg': 'dZeI peg',
    'png': 'pIN',
    'gif': 'dZIf',
    'mp3': 'em pi Tri',
    'mp4': 'em pi fO',
    'wav': 'wQv',
    'zip': 'zIp',
    'exe': 'eks',
    'dll': 'di el el',

    # Common tech companies/products
    'google': 'gug@l',
    'microsoft': 'maIkr@sOft',
    'apple': '{p@l',
    'amazon': '{m@zQn',
    'nvidia': 'envIdi@',
    'amd': 'eI em di',
    'intel': 'Int@l',
}


def normalize_text(text: str) -> str:
    """Normalize text for processing with context-aware numeral handling."""
    # Process numerals BEFORE lowercasing (to preserve $ and other context)
    text = NumeralProcessor.process_text(text)

    # Convert to lowercase
    text = text.lower()

    # Replace common punctuation with pauses
    text = re.sub(r'[.!?]', ' . ', text)
    text = re.sub(r'[,;:]', ' , ', text)

    # Remove other punctuation (keep hyphens in words like "twenty-four")
    text = re.sub(r'[^\w\s.,-]', ' ', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def spell_word(word: str) -> str:
    """Spell out a word letter by letter."""
    result = []
    for ch in word.upper():
        if ch in LETTER_NAMES:
            result.append(LETTER_NAMES[ch])
        elif ch in DIGITS:
            result.append(DIGITS[ch])
    return ' '.join(result)


def number_to_phonemes(num_str: str) -> str:
    """Convert a number string to phonemes."""
    result = []
    for digit in num_str:
        if digit in DIGITS:
            result.append(DIGITS[digit])
    return ' '.join(result)


def _single_word_to_phonemes(word: str) -> str:
    """
    Convert a single non-hyphenated word to phonemes.

    Lookup order:
    1. CMU Pronouncing Dictionary
    2. eSpeak-NG fallback (if available)
    3. Simple letter-to-sound rules

    After lookup, applies phoneme rewriting rules for natural pronunciation.

    Args:
        word: Word to convert (lowercase, no hyphens)

    Returns:
        SAMPA phoneme string
    """
    # Try CMU dictionary first (most accurate)
    cmu_result = cmu_lookup(word)
    if cmu_result:
        phonemes = cmu_result
    else:
        # Try eSpeak fallback (broader vocabulary)
        espeak_result = espeak_lookup(word)
        if espeak_result:
            phonemes = espeak_result
        else:
            # Fall back to letter-to-sound rules
            phonemes = apply_rules(word)

    # Apply phoneme rewriting rules for more natural pronunciation
    if phonemes:
        phonemes = apply_phoneme_rules(phonemes)

    return phonemes


def word_to_phonemes(word: str) -> str:
    """
    Convert a single word to phonemes.

    Handles hyphenated words by splitting and processing each part.

    Lookup order:
    1. Special words dictionary
    2. CMU Pronouncing Dictionary (for each word part)
    3. Simple letter-to-sound rules (fallback)

    After lookup, applies phoneme rewriting rules for natural pronunciation.

    Args:
        word: Word to convert (lowercase)

    Returns:
        SAMPA phoneme string
    """
    word_lower = word.lower().strip()
    if not word_lower:
        return ''

    # Check special words first (no rules applied - already correct)
    if word_lower in SPECIAL_WORDS:
        return SPECIAL_WORDS[word_lower]

    # Check if it's a number
    if word_lower.isdigit():
        return number_to_phonemes(word_lower)

    # Handle hyphenated words by splitting and processing each part
    if '-' in word_lower:
        parts = word_lower.split('-')
        phoneme_parts = []
        for part in parts:
            if part:
                part_phonemes = _single_word_to_phonemes(part)
                if part_phonemes:
                    phoneme_parts.append(part_phonemes)
        return ' '.join(phoneme_parts)

    # Single word processing
    return _single_word_to_phonemes(word_lower)


def text_to_phonemes(text: str) -> str:
    """
    Convert English text to SAMPA phonemes.

    Args:
        text: English text to convert

    Returns:
        SAMPA phoneme string with stress markers and pauses
    """
    text = normalize_text(text)
    words = text.split()

    result = []
    for word in words:
        if word == '.':
            result.append('.')  # Sentence pause
        elif word == ',':
            result.append(' ')  # Short pause
        else:
            phonemes = word_to_phonemes(word)
            if phonemes:
                # Add primary stress to first syllable if none present
                if "'" not in phonemes and "," not in phonemes:
                    phonemes = "'" + phonemes
                result.append(phonemes)

    return ' '.join(result)


def say(text: str) -> List[Tuple[str, str]]:
    """
    Convert text to a list of (word, phonemes) pairs.

    Useful for debugging and visualization.
    """
    text = normalize_text(text)
    words = text.split()

    result = []
    for word in words:
        if word in '.,':
            result.append((word, word))
        else:
            result.append((word, word_to_phonemes(word)))

    return result
