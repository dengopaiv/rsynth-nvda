"""
Klatt Formant Synthesizer - Python Port of RSynth opsynth.c

This is a port of the RSynth Klatt synthesizer to pure Python.
Original C code copyright (c) 2002-2004 Nick Ing-Simmons, LGPL licensed.

The Klatt synthesizer generates speech using formant synthesis with:
- Cascade formant filters for voiced sounds
- Parallel formant filters for fricatives
- Glottal pulse waveform for voicing
- Noise source for fricatives and aspiration
"""

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Callable

PI = math.pi

# Natural voice samples from Praat's klatt.cpp - LF model waveform
# These provide a more realistic glottal source than the synthetic pulse
# Based on "A four-parameter model of the glottal flow" Fant et al. 1985
NATURAL_SAMPLES = [
    -310, -400, 530, 356, 224, 89, 23, -10, -58, -16, 461, 599, 536, 701, 770,
    605, 497, 461, 560, 404, 110, 224, 131, 104, -97, 155, 278, -154, -1165,
    -598, 737, 125, -592, 41, 11, -247, -10, 65, 92, 80, -304, 71, 167, -1, 122,
    233, 161, -43, 278, 479, 485, 407, 266, 650, 134, 80, 236, 68, 260, 269, 179,
    53, 140, 275, 293, 296, 104, 257, 152, 311, 182, 263, 245, 125, 314, 140, 44,
    203, 230, -235, -286, 23, 107, 92, -91, 38, 464, 443, 176, 98, -784, -2449,
    -1891, -1045, -1600, -1462, -1384, -1261, -949, -730
]

# Voice source types
VOICE_IMPULSIVE = 1  # Simple impulse/ramp (original RSynth)
VOICE_NATURAL = 2    # LF model natural samples (from Praat)


@dataclass
class Resonator:
    """
    2nd-order IIR resonator filter with coefficient interpolation.

    Implements the difference equation:
        y[n] = a*x[n] + b*y[n-1] + c*y[n-2]

    Interpolation smoothly transitions coefficients to avoid audio artifacts.
    """
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    p1: float = 0.0  # y[n-1]
    p2: float = 0.0  # y[n-2]
    # Interpolation increments (applied each sample for smooth transitions)
    a_inc: float = 0.0
    b_inc: float = 0.0
    c_inc: float = 0.0

    def process(self, input_sample: float) -> float:
        """Process one sample through the resonator."""
        x = self.a * input_sample + self.b * self.p1 + self.c * self.p2
        self.p2 = self.p1
        self.p1 = x
        return x

    def interpolate(self):
        """Apply one step of coefficient interpolation."""
        self.a += self.a_inc
        self.b += self.b_inc
        self.c += self.c_inc

    def set_target(self, a_new: float, b_new: float, c_new: float, steps: int):
        """Set target coefficients and calculate interpolation increments."""
        if steps > 0:
            self.a_inc = (a_new - self.a) / steps
            self.b_inc = (b_new - self.b) / steps
            self.c_inc = (c_new - self.c) / steps
        else:
            self.a, self.b, self.c = a_new, b_new, c_new
            self.a_inc = self.b_inc = self.c_inc = 0.0

    def reset(self):
        """Reset filter state."""
        self.p1 = 0.0
        self.p2 = 0.0


def set_resonator_coeffs(sample_rate: int, freq: float, bandwidth: float,
                         is_cascade: bool = True) -> tuple:
    """
    Calculate resonator coefficients from frequency and bandwidth.

    Args:
        sample_rate: Sample rate in Hz
        freq: Center frequency in Hz
        bandwidth: Bandwidth in Hz
        is_cascade: True for cascade (pass-through), False for parallel (zero)

    Returns:
        (a, b, c) coefficients for the resonator
    """
    minus_pi_t = -PI / sample_rate
    two_pi_t = -2.0 * minus_pi_t

    # Check if resonator is within Nyquist limit
    if 2 * freq - bandwidth <= sample_rate:
        # Adjust if upper skirt exceeds Nyquist
        if 2 * (freq + bandwidth) > sample_rate:
            low = freq - bandwidth
            freq = (sample_rate / 2 + low) / 2
            bandwidth = freq - low

        r = math.exp(minus_pi_t * bandwidth)
        c = -(r * r)
        b = r * math.cos(two_pi_t * freq) * 2.0
        a = 1.0 - b - c
    else:
        # Beyond Nyquist - make it a no-op
        a = 1.0 if is_cascade else 0.0
        b = 0.0
        c = 0.0

    return a, b, c


def set_antiresonator_coeffs(sample_rate: int, freq: float, bandwidth: float) -> tuple:
    """
    Calculate anti-resonator (zero) coefficients.

    Anti-resonators create notches in the frequency response.
    """
    # First compute ordinary resonator coefficients
    a, b, c = set_resonator_coeffs(sample_rate, freq, bandwidth, is_cascade=True)

    # Convert to antiresonator: a' = 1/a, b' = -b/a, c' = -c/a
    if a != 0:
        a_inv = 1.0 / a
        return a_inv, -b * a_inv, -c * a_inv
    return 1.0, 0.0, 0.0


def db_to_linear(dB: float) -> float:
    """Convert decibels to linear amplitude."""
    if dB > 0:
        return 32768 * math.pow(10.0, (dB - 87) / 20 - 3)
    return 0.0


@dataclass
class Speaker:
    """Voice/speaker characteristics."""
    F0Hz: float = 120.0      # Fundamental frequency
    Gain0: float = 57.0      # Overall gain in dB
    F4hz: float = 3900.0     # Fourth formant freq
    B4hz: float = 400.0      # Fourth formant bandwidth
    F5hz: float = 4700.0     # Fifth formant freq
    B5hz: float = 150.0      # Fifth formant bandwidth
    F6hz: float = 4900.0     # Sixth formant freq
    B6hz: float = 150.0      # Sixth formant bandwidth
    FNPhz: float = 270.0     # Nasal pole frequency
    BNhz: float = 500.0      # Nasal bandwidth
    B4phz: float = 500.0     # Parallel 4th formant bw
    B5phz: float = 600.0     # Parallel 5th formant bw
    B6phz: float = 800.0     # Parallel 6th formant bw
    # F1/F2/F3 offset and scale (applied to phoneme values)
    F1_offset: float = 0.0   # F1 frequency offset in Hz
    F1_scale: float = 1.0    # F1 frequency multiplier
    F2_offset: float = 0.0   # F2 frequency offset in Hz
    F2_scale: float = 1.0    # F2 frequency multiplier
    F3_offset: float = 0.0   # F3 frequency offset in Hz
    F3_scale: float = 1.0    # F3 frequency multiplier


# Parameter indices (matching rsynth.h enum)
class Param:
    fn = 0   # Nasal zero freq
    f1 = 1   # First formant freq
    f2 = 2   # Second formant freq
    f3 = 3   # Third formant freq
    b1 = 4   # First formant bandwidth
    b2 = 5   # Second formant bandwidth
    b3 = 6   # Third formant bandwidth
    pn = 7   # Proportion nasal
    a2 = 8   # Amp of F2 frication
    a3 = 9   # Amp of F3 frication
    a4 = 10  # Amp of F4 frication
    a5 = 11  # Amp of F5 frication
    a6 = 12  # Amp of F6 frication
    ab = 13  # Amp of bypass frication
    av = 14  # Amp of voicing
    avc = 15 # Amp of voice-bar
    asp = 16 # Amp of aspiration
    af = 17  # Amp of frication
    COUNT = 18

PARAM_NAMES = ['fn', 'f1', 'f2', 'f3', 'b1', 'b2', 'b3', 'pn',
               'a2', 'a3', 'a4', 'a5', 'a6', 'ab', 'av', 'avc', 'asp', 'af']


class KlattSynth:
    """
    Klatt formant synthesizer.

    Generates speech by passing a glottal source through a cascade of
    formant resonators, with parallel resonators for frication noise.
    """

    def __init__(self, sample_rate: int = 16000, ms_per_frame: float = 10.0,
                 speaker: Optional[Speaker] = None):
        """
        Initialize the synthesizer.

        Args:
            sample_rate: Output sample rate in Hz
            ms_per_frame: Milliseconds per synthesis frame
            speaker: Speaker characteristics (uses defaults if None)
        """
        self.sample_rate = sample_rate
        self.samples_per_frame = int((sample_rate * ms_per_frame) / 1000)
        self.speaker = speaker or Speaker()

        # Current frame parameters
        self.params = [0.0] * Param.COUNT

        # Voicing state
        self.nper = 0       # Current position in voicing period (*4)
        self.T0 = 4         # Fundamental period in samples * 4
        self.nopen = 0      # Number of samples in open phase
        self.F0Hz = self.speaker.F0Hz

        # Amplitude values (converted from dB)
        self.amp_av = 0.0      # Voice amplitude
        self.amp_bypass = 0.0  # Bypass frication amplitude
        self.amp_asp = 0.0     # Aspiration amplitude
        self.amp_af = 0.0      # Frication amplitude
        self.amp_avc = 0.0     # Voice-bar amplitude
        self.amp_turb = 0.0    # Turbulence amplitude

        # Attack ramp for voiceless sounds (prevents "h" burst)
        self._noise_ramp_samples = 0  # Counter for ramp-up
        self._noise_ramp_length = 80  # ~5ms at 16kHz (smooth attack)
        self._voiceless_started = False  # Track if we've started voiceless (for cold start)

        # Random number generator state
        self.seed = 5

        # Sample counter
        self.ns = 0

        # Cascade resonators
        self.rgl = Resonator()   # Glottal low-pass
        self.rnz = Resonator()   # Nasal zero (anti-resonator)
        self.rnpc = Resonator()  # Nasal pole
        self.r5c = Resonator()   # F5 cascade
        self.rsc = Resonator()   # Special cascade (3500 Hz)
        self.r4c = Resonator()   # F4 cascade
        self.r3c = Resonator()   # F3 cascade
        self.r2c = Resonator()   # F2 cascade
        self.r1c = Resonator()   # F1 cascade

        # Parallel resonators
        self.r6p = Resonator()   # F6 parallel
        self.r5p = Resonator()   # F5 parallel
        self.r4p = Resonator()   # F4 parallel
        self.r3p = Resonator()   # F3 parallel
        self.r2p = Resonator()   # F2 parallel

        # Output resonator (low-pass)
        self.rout = Resonator()

        # DC blocking filter state (removes low-frequency hum from resonator accumulation)
        self.dc_x1 = 0.0  # Previous input
        self.dc_y1 = 0.0  # Previous output

        # Smoothing filter coefficient
        self.smooth = 0.5

        # Speed multiplier
        self.speed = 1.0

        # Voice naturalness parameters
        # Jitter: random variation in pitch period (1-2% typical for natural voice)
        self.jitter = 0.015  # 1.5% pitch jitter
        # Shimmer: random variation in amplitude (3-5% typical for natural voice)
        self.shimmer = 0.04  # 4% amplitude shimmer

        # Flutter: 3-sine-wave F0 modulation from Klatt & Klatt 1990
        # More natural than simple jitter - creates quasi-random pitch variation
        # Value 0-100, default 20 (matches Praat/eSpeak)
        self.flutter = 20
        self._flutter_t = 0  # Time counter for flutter sines

        # Voice source type: VOICE_IMPULSIVE (default) or VOICE_NATURAL
        # Natural uses LF model samples for more realistic glottal source
        self.voice_source = VOICE_IMPULSIVE
        self._sample_pos = 0.0  # Position in natural samples table

        # Track voicing state for transition detection (resonator reset)
        self._was_voiced = False

    def _set_cascade_resonators(self, interpolate: bool = False):
        """Set up cascade path resonators based on current parameters.

        Args:
            interpolate: If True, use smooth interpolation for F1-F3 resonators
                        to avoid audio artifacts from abrupt coefficient changes.
        """
        sr = self.sample_rate
        ep = self.params
        spk = self.speaker
        steps = self.samples_per_frame if interpolate else 0

        # Nasal pole and zero (fixed, no interpolation needed)
        a, b, c = set_resonator_coeffs(sr, spk.FNPhz, spk.BNhz, True)
        self.rnpc.a, self.rnpc.b, self.rnpc.c = a, b, c

        a, b, c = set_antiresonator_coeffs(sr, ep[Param.fn], spk.BNhz)
        self.rnz.a, self.rnz.b, self.rnz.c = a, b, c

        # Special resonator at 3500 Hz (fixed)
        a, b, c = set_resonator_coeffs(sr, 3500, 1800, True)
        self.rsc.a, self.rsc.b, self.rsc.c = a, b, c

        # F5, F4 (from speaker settings, don't change per frame)
        a, b, c = set_resonator_coeffs(sr, spk.F5hz, spk.B5hz, True)
        self.r5c.a, self.r5c.b, self.r5c.c = a, b, c

        a, b, c = set_resonator_coeffs(sr, spk.F4hz, spk.B4hz, True)
        self.r4c.a, self.r4c.b, self.r4c.c = a, b, c

        # F3, F2, F1 with speaker offset and scale applied
        # These change per-phoneme, so use interpolation to smooth transitions

        # F3: apply offset and scale, clamp to safe range (1500-3500 Hz)
        f3_adj = ep[Param.f3] * spk.F3_scale + spk.F3_offset
        f3_adj = max(1500, min(3500, f3_adj))
        a, b, c = set_resonator_coeffs(sr, f3_adj, ep[Param.b3], True)
        if interpolate:
            self.r3c.set_target(a, b, c, steps)
        else:
            self.r3c.a, self.r3c.b, self.r3c.c = a, b, c

        # F2: apply offset and scale, clamp to safe range (700-2500 Hz)
        f2_adj = ep[Param.f2] * spk.F2_scale + spk.F2_offset
        f2_adj = max(700, min(2500, f2_adj))
        a, b, c = set_resonator_coeffs(sr, f2_adj, ep[Param.b2], True)
        if interpolate:
            self.r2c.set_target(a, b, c, steps)
        else:
            self.r2c.a, self.r2c.b, self.r2c.c = a, b, c

        # F1: apply offset and scale, clamp to safe range (200-1000 Hz)
        f1_adj = ep[Param.f1] * spk.F1_scale + spk.F1_offset
        f1_adj = max(200, min(1000, f1_adj))
        a, b, c = set_resonator_coeffs(sr, f1_adj, ep[Param.b1], True)
        if interpolate:
            self.r1c.set_target(a, b, c, steps)
        else:
            self.r1c.a, self.r1c.b, self.r1c.c = a, b, c

    def _pitch_sync(self):
        """Update pitch-synchronous parameters with jitter for naturalness."""
        F0Hz = self.F0Hz
        ep = self.params

        if ep[Param.av] > 0 or ep[Param.avc] > 0:
            # Calculate base pitch period
            base_T0 = int((4 * self.sample_rate) / F0Hz)

            # Add jitter (random variation in pitch period)
            # This makes the voice sound more natural/less robotic
            if self.jitter > 0:
                jitter_amount = base_T0 * self.jitter * (random.random() * 2 - 1)
                self.T0 = max(4, int(base_T0 + jitter_amount))
            else:
                self.T0 = base_T0

            self.amp_av = db_to_linear(ep[Param.av])
            self.amp_avc = db_to_linear(ep[Param.avc])
            self.amp_turb = self.amp_avc * 0.05  # Reduced from 0.1 to prevent friction-like artifacts at slow speed
            self.nopen = self.T0 // 3
        else:
            self.T0 = 4
            self.nopen = self.T0
            self.amp_av = 0.0
            self.amp_avc = 0.0
            # Resonator reset is now handled in generate_frame() at frame boundaries
            # to avoid resetting every 4 samples (T0=4 when voiceless)

        if self.T0 != 4 or self.ns == 0:
            # Update glottal low-pass filter
            a, b, c = set_resonator_coeffs(self.sample_rate, 0, 2 * F0Hz, True)
            self.rgl.a, self.rgl.b, self.rgl.c = a, b, c
            # Note: cascade resonators are now set in generate_frame() with interpolation

    def _gen_noise(self) -> float:
        """Generate Gaussian-distributed noise."""
        noise = 0.0
        for _ in range(16):
            # Linear congruential generator
            self.seed = (self.seed * 1664525 + 1) & 0xFFFFFFFF
            # Convert to signed 14-bit value
            nrand = ((self.seed << 1) >> 18) - 8192
            noise += nrand
        return noise / 2

    def _gen_voice(self, noise: float) -> float:
        """Generate voice waveform at 4x sample rate."""
        voice = 0.0
        amp = 4096.0

        for _ in range(4):
            if self.nper >= self.T0:
                self.nper = 0
                self._pitch_sync()

            if self.voice_source == VOICE_NATURAL:
                # Use LF model natural samples for more realistic voice
                # Interpolate through the sample table based on position in period
                num_samples = len(NATURAL_SAMPLES)
                alpha = self.nper / self.T0 if self.T0 > 0 else 0
                pos = alpha * num_samples
                idx = int(pos)
                frac = pos - idx

                if idx < num_samples - 1:
                    # Linear interpolation between samples
                    voice = NATURAL_SAMPLES[idx] * (1 - frac) + NATURAL_SAMPLES[idx + 1] * frac
                elif idx < num_samples:
                    voice = NATURAL_SAMPLES[idx]
                else:
                    voice = 0

                # Scale to match impulsive source amplitude
                voice *= (amp / 2500.0)
            else:
                # Default: impulsive source (original RSynth)
                # Voice source shape: linear ramp for 1/3, parabola for 2/3
                alpha = self.nper / self.T0 if self.T0 > 0 else 0

                if alpha <= 1.0 / 3:
                    voice = 3 * amp * alpha
                else:
                    voice = amp * ((9 * alpha - 12) * alpha + 3)

            self.nper += 1

        return voice

    def _antiresonator(self, r: Resonator, input_sample: float) -> float:
        """Process through anti-resonator (saves input, not output)."""
        x = r.a * input_sample + r.b * r.p1 + r.c * r.p2
        r.p2 = r.p1
        r.p1 = input_sample
        return x

    def _dc_block(self, sample: float) -> float:
        """
        Remove DC offset using a single-pole high-pass filter.

        This prevents low-frequency hum from accumulating in the resonators.
        Cutoff is approximately 3-5Hz at typical sample rates (matches DECtalk).

        y[n] = x[n] - x[n-1] + R * y[n-1], where R ≈ 0.99
        """
        DC_R = 0.99
        y = sample - self.dc_x1 + DC_R * self.dc_y1
        self.dc_x1 = sample
        self.dc_y1 = y
        return y

    def _setup_frame(self):
        """Set up resonators for current frame parameters."""
        sr = self.sample_rate
        ep = self.params
        spk = self.speaker
        Gain0 = spk.Gain0 - 3

        # Parallel resonators with gain (apply same F2/F3 offset/scale as cascade)
        f2_adj = ep[Param.f2] * spk.F2_scale + spk.F2_offset
        f2_adj = max(700, min(2500, f2_adj))
        a, b, c = set_resonator_coeffs(sr, f2_adj, ep[Param.b2], False)
        self.r2p.a, self.r2p.b, self.r2p.c = a * db_to_linear(ep[Param.a2]), b, c

        f3_adj = ep[Param.f3] * spk.F3_scale + spk.F3_offset
        f3_adj = max(1500, min(3500, f3_adj))
        a, b, c = set_resonator_coeffs(sr, f3_adj, ep[Param.b3], False)
        self.r3p.a, self.r3p.b, self.r3p.c = a * db_to_linear(ep[Param.a3]), b, c

        a, b, c = set_resonator_coeffs(sr, spk.F4hz, spk.B4phz, False)
        self.r4p.a, self.r4p.b, self.r4p.c = a * db_to_linear(ep[Param.a4]), b, c

        a, b, c = set_resonator_coeffs(sr, spk.F5hz, spk.B5phz, False)
        self.r5p.a, self.r5p.b, self.r5p.c = a * db_to_linear(ep[Param.a5]), b, c

        a, b, c = set_resonator_coeffs(sr, spk.F6hz, spk.B6phz, False)
        self.r6p.a, self.r6p.b, self.r6p.c = a * db_to_linear(ep[Param.a6]), b, c

        # Amplitudes
        self.amp_bypass = db_to_linear(ep[Param.ab])
        self.amp_asp = db_to_linear(ep[Param.asp])
        self.amp_af = db_to_linear(ep[Param.af])

        # Output low-pass filter
        if Gain0 <= 0:
            Gain0 = 57
        a, b, c = set_resonator_coeffs(sr, 0, sr / 2, True)
        self.rout.a, self.rout.b, self.rout.c = a * db_to_linear(Gain0), b, c

    def _filter_sample(self, voice: float, noise: float) -> float:
        """Apply cascade and parallel filters to produce output sample."""
        # Cascade path: voice through nasal and formant resonators
        voice = self.rnpc.process(voice)
        voice = self._antiresonator(self.rnz, voice)
        voice = self.r1c.process(voice)
        voice = self.r2c.process(voice)
        voice = self.r3c.process(voice)
        voice = self.r4c.process(voice)
        voice = self.rsc.process(voice)

        if self.sample_rate > 8000:
            voice = self.r5c.process(voice)

        # Parallel path: frication noise through parallel resonators
        # Each parallel resonator processes noise independently and sums
        parallel = (
            self.r2p.process(noise) +
            self.r3p.process(noise) +
            self.r4p.process(noise) +
            self.r5p.process(noise) +
            self.r6p.process(noise) +
            self.amp_bypass * noise
        )

        # Combine cascade (voiced) and parallel (frication) paths
        voice = voice + parallel

        # Final low-pass and gain
        voice = self.rout.process(voice)

        # Remove DC offset to prevent low-frequency hum
        voice = self._dc_block(voice)

        return voice

    def generate_frame(self, F0Hz: float, params: List[float]) -> List[float]:
        """
        Generate one frame of audio samples.

        Args:
            F0Hz: Fundamental frequency for this frame
            params: List of 18 synthesis parameters

        Returns:
            List of audio samples for this frame
        """
        self.params = params

        # Check for voicing transition; reset filters only when entering true silence
        is_voiced = params[Param.av] > 0 or params[Param.avc] > 0
        is_silence = (
            params[Param.af] <= 0
            and params[Param.asp] <= 0
            and params[Param.ab] <= 0
            and params[Param.a2] <= 0
            and params[Param.a3] <= 0
            and params[Param.a4] <= 0
            and params[Param.a5] <= 0
            and params[Param.a6] <= 0
        )
        if not is_voiced:
            # Only reset on voiced→silence (or cold-start silence); let filters decay through frication like C
            if is_silence and (self._was_voiced or not self._voiceless_started):
                for r in [self.rnpc, self.rnz, self.r1c, self.r2c, self.r3c,
                          self.r4c, self.r5c, self.rsc, self.rgl,
                          self.r2p, self.r3p, self.r4p, self.r5p, self.r6p, self.rout]:
                    r.reset()
                self._noise_ramp_samples = 0  # Restart ramp when we re-enter noise after silence
            self._voiceless_started = True
            self.amp_av = 0.0
            self.amp_avc = 0.0
            self.amp_turb = 0.0
        else:
            self._voiceless_started = False
        self._was_voiced = is_voiced

        # Apply flutter to F0 for natural pitch variation
        self.F0Hz = self._apply_flutter(F0Hz)
        self._setup_frame()

        # Set up cascade resonators with smooth interpolation
        # This prevents abrupt coefficient changes that cause audio artifacts
        self._set_cascade_resonators(interpolate=True)

        samples = [0.0] * self.samples_per_frame

        for i in range(self.samples_per_frame):
            noise = self._gen_noise()

            # Skip voice pulse generation during voiceless sounds
            # This prevents LFO-like pulse leakage into voiceless phonemes
            # Use params directly (amp_av is set inside _gen_voice/_pitch_sync)
            if self.params[Param.av] > 0 or self.params[Param.avc] > 0:
                voice = self._gen_voice(noise)
                lpvoice = self.rgl.process(voice)
            else:
                voice = 0.0
                lpvoice = 0.0

            # Add breathiness during glottal open phase
            if self.nper < self.nopen:
                voice += self.amp_turb * noise

            # Reduce noise in second half of glottal open phase
            if self.nper < self.nopen:
                noise *= 0.5

            # Apply voicing amplitude with shimmer for naturalness
            voice *= self.amp_av
            if self.shimmer > 0 and self.amp_av > 0:
                # Shimmer: random amplitude variation makes voice less robotic
                shimmer_factor = 1.0 + self.shimmer * (random.random() * 2 - 1)
                voice *= shimmer_factor

            # Calculate noise ramp factor (0 to 1) for smooth attack
            if self._noise_ramp_samples < self._noise_ramp_length:
                noise_ramp = self._noise_ramp_samples / self._noise_ramp_length
                self._noise_ramp_samples += 1
            else:
                noise_ramp = 1.0

            # Add aspiration noise (with ramp to prevent "h" burst)
            voice += self.amp_asp * noise_ramp * noise

            # Add voice-bar (low-passed voice)
            voice += self.amp_avc * lpvoice

            # Frication noise (with ramp to prevent "h" burst)
            noise *= self.amp_af * noise_ramp

            # Apply filters
            sample = self._filter_sample(voice, noise)

            # Clip to prevent overflow
            sample = max(-32767, min(32767, sample))
            samples[i] = sample

            # Apply smooth coefficient interpolation for F1, F2, F3
            # This creates natural formant transitions between phonemes
            self.r1c.interpolate()
            self.r2c.interpolate()
            self.r3c.interpolate()

            self.ns += 1

        return samples

    def _apply_flutter(self, f0_hz: float) -> float:
        """
        Apply 3-sine-wave flutter for natural pitch variation.

        Based on Klatt & Klatt 1990 "Analysis, synthesis and perception of
        voice quality variations among female and male talkers" JASA 87(2).

        Flutter creates quasi-random pitch variation that sounds more natural
        than simple random jitter. Uses three slowly varying sine waves at
        frequencies chosen to avoid simple harmonic relationships.

        Args:
            f0_hz: Base fundamental frequency in Hz

        Returns:
            Modulated F0 with flutter applied

        Notes:
            Flutter is only used when voicing is active (av/avc > 0) because
            voiceless frames skip _gen_voice() entirely and zero the voicing
            amps earlier in synth_frame(). That means any phase mismatch here
            cannot by itself inject voiced energy into fricatives; leakage in
            voiceless consonants stems from how resonators and voicing amps are
            gated/reset rather than from the flutter LFO timing.
        """
        if self.flutter <= 0:
            return f0_hz

        # Port of flutter() from Praat's klatt.cpp lines 165-179
        fla = self.flutter / 50.0          # Flutter amount scaled
        flb = f0_hz / 100.0                # Base F0 scaled
        # Flutter in the original C code increments "time_count" once per frame
        # and uses 2 * PI for the sine waves (nsynth.c lines 320-336).
        # Use the same stepping to keep modulation speed consistent with RSynth.
        flc = math.sin(2 * PI * 12.7 * self._flutter_t)  # Fast sine
        fld = math.sin(2 * PI * 7.1 * self._flutter_t)   # Medium sine
        fle = math.sin(2 * PI * 4.7 * self._flutter_t)   # Slow sine

        # Combine the three sines for quasi-random variation
        delta_f0 = fla * flb * (flc + fld + fle) * 10

        # Increment time counter once per frame and wrap like the original C
        # implementation. The wrap isn't needed to prevent Python overflow, but
        # it keeps the phase math identical to RSynth and avoids huge arguments
        # to sin() that could accumulate floating-point error over long runs.
        self._flutter_t += 1
        if self._flutter_t > 1000:
            self._flutter_t = 0

        return f0_hz + delta_f0

    def reset(self):
        """Reset synthesizer state."""
        self.nper = 0
        self.ns = 0
        self.seed = 5
        self._flutter_t = 0
        self._sample_pos = 0.0
        self._was_voiced = False
        self._noise_ramp_samples = 0
        self._voiceless_started = False

        # Reset DC blocker state
        self.dc_x1 = 0.0
        self.dc_y1 = 0.0

        # Reset all resonators
        for r in [self.rgl, self.rnz, self.rnpc, self.r5c, self.rsc,
                  self.r4c, self.r3c, self.r2c, self.r1c,
                  self.r6p, self.r5p, self.r4p, self.r3p, self.r2p, self.rout]:
            r.reset()
