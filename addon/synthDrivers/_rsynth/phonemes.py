"""
Phoneme-to-Element Conversion for RSynth

Converts SAMPA phoneme strings to element sequences for synthesis.
Port of phtoelm.c from RSynth.

Original code copyright (c) 1994,2001-2003 Nick Ing-Simmons, LGPL licensed.
"""

from typing import List, Tuple, Optional
from .elements import (
    ELEMENTS,
    ELEMENT_LIST,
    Element,
    InterpParam,
    get_element_index,
)


def decline_f0(current_f0: float, elapsed_frames: int, f0_default: float) -> float:
    """
    Exponential F0 decline between stress markers.

    Port of decline_f0() from phtoelm.c lines 131-141.
    Uses the "magic constant" 0.12 for natural pitch decline.

    Args:
        current_f0: Current F0 value in Hz
        elapsed_frames: Number of frames since last stress marker
        f0_default: Default/base F0 frequency

    Returns:
        New F0 value after decline (floored at 70% of default)
    """
    f = current_f0 - 0.12 * elapsed_frames
    # Don't drop below 70% of default F0
    return max(f, 0.7 * f0_default)

# SAMPA phoneme to element sequence mapping
# Format: phoneme -> [element_names]
PHONEME_MAP = {
    # Silences
    '.': ['END'],
    ' ': ['Q'],
    '_': ['Q'],
    '#': ['Q'],

    # Affricates (compounds)
    'tS': ['T', 'CH'],
    'dZ': ['D', 'DY', 'DZ', 'ZH', 'ZH'],

    # Plosives
    'p': ['P', 'PY', 'PZ'],
    'b': ['B', 'BY', 'BZ'],
    't': ['T', 'TY', 'TZ'],
    'd': ['D', 'DY', 'DZ'],
    'k': ['K', 'KY', 'KZ'],
    'g': ['G', 'GY', 'GZ'],
    '?': ['QQ'],

    # Nasals
    'm': ['M'],
    'n': ['N'],
    'N': ['NG'],

    # Trills and flaps
    '4': ['DT'],
    'rr': ['R', 'QQ', 'R'],
    'R': ['RX'],
    '`': ['RX'],

    # Fricatives
    'f': ['F'],
    'v': ['V'],
    'T': ['TH'],
    'D': ['DH'],
    's': ['S'],
    'z': ['Z'],
    'S': ['SH'],
    'Z': ['ZH'],
    'x': ['X'],
    'h': ['H'],

    # Laterals
    'l': ['L'],
    'K': ['HL'],
    '5': ['LL'],

    # Approximants
    'w': ['W'],
    'j': ['Y'],
    'r': ['R'],

    # Diphthongs
    'eI': ['AI', 'I'],
    'aI': ['IE', 'I'],
    'OI': ['OI', 'I'],
    'aU': ['AI', 'OV'],
    '@U': ['OA', 'OV'],
    'I@': ['IA', 'IB'],
    'e@': ['AIR', 'IB'],
    'U@': ['OOR', 'IB'],
    'O@': ['OI', 'IB'],
    'oU': ['o', 'OV'],

    # Close vowels
    'i': ['EE'],
    'y': ['YY'],
    '1': ['EY'],
    '}': ['JU'],
    'M': ['UW'],
    'u': ['UU'],

    # Lax vowels
    'I': ['I'],
    'Y': ['IU'],
    'U': ['OO'],

    # Close-mid vowels
    'e': ['e'],
    'e~': ['eN'],
    '2': ['EU'],
    '@\\': ['Ur'],
    '8': ['UR'],
    '7': ['UE'],
    'o': ['o'],
    'o~': ['oN'],

    # Schwa
    '@': ['A'],

    # Open-mid vowels
    'E': ['EH'],
    '9': ['oe'],
    '9~': ['oeN'],
    '3': ['ER'],
    '3\\': ['Er'],
    'V': ['U'],
    'O': ['AW'],

    '{': ['AA'],
    '6': ['AA'],

    # Open vowels
    'a': ['a'],
    'a~': ['aN'],
    '&': ['OE'],
    'A': ['AR'],
    'Q': ['O'],
}

# Sorted by length (longest first) for proper matching
PHONEME_KEYS = sorted(PHONEME_MAP.keys(), key=lambda x: -len(x))


def phonemes_to_elements(phoneme_string: str, speed: float = 1.0,
                         f0_default: float = 120.0,
                         track_word_boundaries: bool = False,
                         flat_intonation: bool = False) -> Tuple[List[Tuple[int, int]], List[float], Optional[List[int]]]:
    """
    Convert a phoneme string to elements and F0 contour.

    This is a port of phone_to_elm() from phtoelm.c, implementing
    stress-driven F0 contour generation.

    Args:
        phoneme_string: SAMPA phoneme string (e.g., "h@'l@U")
        speed: Duration multiplier
        f0_default: Default fundamental frequency in Hz
        track_word_boundaries: If True, also return word boundary frame indices
        flat_intonation: If True, use constant F0 (robotic monotone)

    Returns:
        Tuple of:
        - List of (element_index, duration) tuples
        - F0 contour as list of floats: [f0_1, dur_1, f0_2, dur_2, ...]
          where dur values represent frame counts for transitions
        - Word boundaries (if track_word_boundaries): List of frame indices where words begin
    """
    result = []
    f0_events = []
    word_boundaries = [0] if track_word_boundaries else None  # First word starts at frame 0
    stress = 0
    i = 0
    t = 0  # Current time in frames
    last_stress_t = 0  # Time of last stress marker
    seen_vowel = False
    at_word_start = True  # Track if we're at start of a new word

    # Start F0: flat mode uses constant pitch, normal mode uses 110% rise
    if flat_intonation:
        current_f0 = f0_default  # Constant pitch for robotic voice
    else:
        current_f0 = f0_default * 1.1  # Natural sentence-initial rise
    f0_events.append(current_f0)

    while i < len(phoneme_string):
        # Check for stress markers
        ch = phoneme_string[i]

        if ch == "'":  # Primary stress
            stress += 1
            # Fall through to handle all stress levels
        if ch == "'":
            stress = 3
        elif ch == ',':  # Secondary stress
            stress = 2
        elif ch == '+':  # Tertiary stress
            stress = 1

        if ch in "'',+":
            # Stress marker found - generate F0 events (skip in flat mode)
            if not flat_intonation:
                # Port of phtoelm.c lines 183-198
                if stress > 3:
                    stress = 3
                seen_vowel = False

                # Calculate F0 decline since last stress marker
                elapsed = t - last_stress_t
                if elapsed > 0:
                    # Add duration for decline phase
                    f0_events.append(elapsed)
                    # Decline the F0
                    current_f0 = decline_f0(current_f0, elapsed, f0_default)
                    f0_events.append(current_f0)

                last_stress_t = t

                # Instant pitch pulse - push F0 up based on stress level
                # The "0" duration means instant transition
                f0_events.append(0)
                pulse_f0 = current_f0 + f0_default * stress * 0.02
                current_f0 = pulse_f0
                f0_events.append(pulse_f0)

            i += 1
            continue

        elif ch == '-':  # Hyphen (ignore)
            i += 1
            continue
        elif ch == ':':  # Length mark
            i += 1
            continue

        # Try to match a phoneme (longest match first)
        matched = False
        for phoneme in PHONEME_KEYS:
            if phoneme_string[i:].startswith(phoneme):
                element_names = PHONEME_MAP[phoneme]

                # Track word boundaries - space phoneme indicates word break
                if track_word_boundaries and phoneme == ' ':
                    at_word_start = True

                for elem_name in element_names:
                    elem = ELEMENTS.get(elem_name)
                    if elem:
                        # Get element index
                        elem_idx = list(ELEMENTS.keys()).index(elem_name)

                        # Calculate duration based on stress
                        # Stressed vowels are longer (StressDur macro from C code)
                        if stress > 0 and elem.ud != elem.du:
                            dur = int((elem.ud + (elem.du - elem.ud) * stress / 3) * speed)
                        else:
                            dur = int(elem.du * speed)

                        result.append((elem_idx, dur))

                        # Record word boundary before incrementing time
                        if track_word_boundaries and at_word_start and phoneme != ' ' and phoneme != '.':
                            if t not in word_boundaries:
                                word_boundaries.append(t)
                            at_word_start = False

                        t += dur  # Track time

                        # Check if this is a vowel (has vwl feature)
                        # Vowels have different ud and du values
                        if elem.ud != elem.du:
                            seen_vowel = True
                        elif seen_vowel:
                            # Reset stress after first consonant following vowel
                            stress = 0

                # Reset stress after phoneme group
                stress = 0
                i += len(phoneme)
                matched = True
                break

        if not matched:
            # Unknown character, skip it
            i += 1

    # Add a trailing pause so the tail decays cleanly even without punctuation.
    if result:
        last_elem = ELEMENT_LIST[result[-1][0]]
        if last_elem.name not in ("Q", "END"):
            tail_idx = get_element_index("Q")
            if tail_idx < 0:
                tail_idx = get_element_index("END")
            if tail_idx >= 0:
                tail_elem = ELEMENT_LIST[tail_idx]
                tail_dur = int(tail_elem.du * speed)
                if tail_dur <= 0:
                    tail_dur = max(1, tail_elem.du)
                result.append((tail_idx, tail_dur))
                t += tail_dur

    # Add final F0 decline to end of utterance (skip in flat mode)
    if not flat_intonation:
        elapsed = t - last_stress_t
        if elapsed > 0:
            f0_events.append(elapsed)
            final_f0 = decline_f0(current_f0, elapsed, f0_default)
            f0_events.append(final_f0)

    if track_word_boundaries:
        return result, f0_events, word_boundaries
    return result, f0_events, None


def linear_interpolate(a: float, b: float, t: int, d: int) -> float:
    """Linear interpolation from a to b over duration d at time t."""
    if t <= 0:
        return a
    elif t >= d:
        return b
    else:
        f = t / d
        return a + (b - a) * f


def interpolate_param(start_val: float, start_t: int,
                      end_val: float, end_t: int,
                      mid_val: float, t: int, dur: int) -> float:
    """
    Interpolate a parameter value at time t within an element.

    The parameter transitions from start_val to mid_val over start_t frames,
    stays at mid_val, then transitions to end_val over end_t frames.
    """
    steady = dur - (start_t + end_t)

    if steady >= 0:
        # Value reaches steady state
        if t < start_t:
            return linear_interpolate(start_val, mid_val, t, start_t)
        else:
            t -= start_t
            if t <= steady:
                return mid_val
            else:
                return linear_interpolate(mid_val, end_val, int(t - steady), end_t)
    else:
        # No steady state - blend start and end transitions
        f = 1.0 - (t / dur)
        sp = linear_interpolate(start_val, mid_val, t, start_t)
        ep = linear_interpolate(end_val, mid_val, dur - t, end_t)
        return f * sp + (1.0 - f) * ep


class FrameGenerator:
    """
    Generate synthesis frames from element sequences.

    Handles parameter interpolation between elements according to
    the Holmes model.
    """

    def __init__(self, sample_rate: int = 16000, ms_per_frame: float = 10.0,
                 f0_default: float = 120.0, speed: float = 1.0, smooth: float = 0.5):
        self.sample_rate = sample_rate
        self.ms_per_frame = ms_per_frame
        self.f0_default = f0_default
        self.speed = speed
        self.smooth = smooth

        # Smoothing filter state
        self._filter_state = [0.0] * 18

    def reset(self):
        """Reset filter state."""
        self._filter_state = [0.0] * 18

    def _smooth_param(self, idx: int, value: float) -> float:
        """Apply smoothing filter to parameter, scaled by speed."""
        # Adjust smooth to maintain proportional smoothing regardless of speed
        # At slow speed (speed > 1), use higher coefficient for same proportional effect
        effective_smooth = self.smooth ** (1.0 / self.speed)
        self._filter_state[idx] = (effective_smooth * value +
                                    (1.0 - effective_smooth) * self._filter_state[idx])
        return self._filter_state[idx]

    def generate_frames(self, elements: List[Tuple[int, int]],
                        f0_contour: Optional[List[float]] = None):
        """
        Generate synthesis parameter frames from element sequence.

        Args:
            elements: List of (element_index, duration) pairs
            f0_contour: F0 contour from phonemes_to_elements(), format:
                        [f0_start, dur_1, f0_1, dur_2, f0_2, ...]
                        Duration of 0 means instant transition (pitch pulse)

        Yields:
            (f0_hz, params) tuples for each frame
        """
        if not elements:
            return

        elem_list = list(ELEMENTS.values())

        # Initialize filter state from first element
        if elements:
            first_elem = elem_list[elements[0][0]]
            for j in range(18):
                self._filter_state[j] = first_elem.params[j].stdy

        # Default F0 contour if none provided
        if f0_contour is None or len(f0_contour) < 1:
            total_dur = sum(dur for _, dur in elements)
            f0_start = self.f0_default * 1.1
            f0_end = self.f0_default * 0.7
            f0_contour = [f0_start, total_dur, f0_end]

        # F0 contour state
        # Format: [f0_start, dur_1, f0_1, dur_2, f0_2, ...]
        f0_idx = 0
        f0_t = 0
        f0_current = f0_contour[0]  # Starting F0

        # Get first transition target
        if len(f0_contour) >= 3:
            f0_dur = int(f0_contour[1]) if f0_contour[1] > 0 else 1
            f0_target = f0_contour[2]
        else:
            f0_dur = 100
            f0_target = f0_current

        last_elem = elem_list[0]  # END element

        for i, (elem_idx, dur) in enumerate(elements):
            if dur <= 0:
                continue

            curr_elem = elem_list[elem_idx]
            next_elem = elem_list[elements[i + 1][0]] if i + 1 < len(elements) else elem_list[0]

            # Calculate transition slopes
            start_slopes = []
            end_slopes = []

            for j in range(18):
                # Start transition (from last to current)
                if curr_elem.params[j].rk > last_elem.params[j].rk:
                    # Current dominates
                    t = int(curr_elem.params[j].id * self.speed)
                    afrac = curr_elem.params[j].prop * 0.01
                    v = curr_elem.params[j].stdy * (1.0 - afrac) + afrac * last_elem.params[j].stdy
                else:
                    # Last dominates
                    t = int(last_elem.params[j].ed * self.speed)
                    afrac = last_elem.params[j].prop * 0.01
                    v = last_elem.params[j].stdy * (1.0 - afrac) + afrac * curr_elem.params[j].stdy
                start_slopes.append((v, t))

                # End transition (from current to next)
                if next_elem.params[j].rk > curr_elem.params[j].rk:
                    # Next dominates
                    t = int(next_elem.params[j].ed * self.speed)
                    afrac = next_elem.params[j].prop * 0.01
                    v = next_elem.params[j].stdy * (1.0 - afrac) + afrac * curr_elem.params[j].stdy
                else:
                    # Current dominates
                    t = int(curr_elem.params[j].id * self.speed)
                    afrac = curr_elem.params[j].prop * 0.01
                    v = curr_elem.params[j].stdy * (1.0 - afrac) + afrac * next_elem.params[j].stdy
                end_slopes.append((v, t))

            # Generate frames for this element
            for t in range(dur):
                params = []
                for j in range(18):
                    val = interpolate_param(
                        start_slopes[j][0], start_slopes[j][1],
                        end_slopes[j][0], end_slopes[j][1],
                        curr_elem.params[j].stdy,
                        t, dur
                    )
                    # Use faster smoothing for voicing to prevent bleed but avoid clicks
                    # av=14, avc=15 need quick transitions (~3 frames) not instant
                    if j in (14, 15):
                        # Fast smoothing: 0.85 decays in 3 frames vs 0.5 in 7 frames
                        # Scale with speed for consistent proportional smoothing
                        #
                        # Clamp voicing targets to zero without smoothing so tiny residuals
                        # don't keep the synthesizer in the "voiced" path and leak glottal
                        # energy into voiceless consonants.
                        if val <= 0.0:
                            self._filter_state[j] = 0.0
                        else:
                            effective_fast_smooth = 0.85 ** (1.0 / self.speed)
                            self._filter_state[j] = (
                                effective_fast_smooth * val
                                + (1.0 - effective_fast_smooth) * self._filter_state[j]
                            )
                        params.append(self._filter_state[j])
                    else:
                        params.append(self._smooth_param(j, val))

                # Interpolate F0 using stress-driven contour
                if f0_dur > 0:
                    f0_hz = linear_interpolate(f0_current, f0_target, f0_t, f0_dur)
                else:
                    # Instant transition (pitch pulse)
                    f0_hz = f0_target
                f0_t += 1

                # Advance to next F0 segment when current one completes
                while f0_t >= f0_dur and f0_idx + 2 < len(f0_contour) - 2:
                    f0_t = 0
                    f0_idx += 2
                    f0_current = f0_target
                    f0_dur = int(f0_contour[f0_idx + 1]) if f0_contour[f0_idx + 1] > 0 else 1
                    if f0_idx + 2 < len(f0_contour):
                        f0_target = f0_contour[f0_idx + 2]
                    # Handle instant transitions (duration 0)
                    if f0_dur == 0 or f0_dur == 1:
                        f0_current = f0_target

                yield (f0_hz, params)

            last_elem = curr_elem
