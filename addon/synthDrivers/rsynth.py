"""
RSynth NVDA Speech Synthesizer Driver

A Klatt formant synthesizer for NVDA based on RSynth.
Provides intelligible speech synthesis using pure Python.
"""

import os
import sys
import json
import threading
import queue
import array
from typing import Optional, List, Union, Tuple, Any, Dict, Callable

# NVDA imports
import synthDriverHandler
from synthDriverHandler import SynthDriver as BaseSynthDriver, VoiceInfo
from speech.commands import (
    IndexCommand,
    BreakCommand,
    PitchCommand,
    RateCommand,
    VolumeCommand,
)
import nvwave
from logHandler import log

# Add our module path for the _rsynth import
_addon_path = os.path.dirname(os.path.abspath(__file__))
if _addon_path not in sys.path:
    sys.path.insert(0, _addon_path)

# Import synthesis module
from _rsynth import (
    KlattSynth,
    Speaker,
    text_to_phonemes,
    phonemes_to_elements,
    FrameGenerator,
)


class SynthDriver(BaseSynthDriver):
    """RSynth Klatt Formant Synthesizer for NVDA."""

    name = "rsynth"
    description = "RSynth Klatt Synthesizer"

    # Audio configuration
    SAMPLE_RATE = 22050
    CHANNELS = 1
    BITS_PER_SAMPLE = 16
    MS_PER_FRAME = 10.0

    # Parameter ranges
    # Rate: Maps to RSynth's speed multiplier
    RATE_MIN = 0.5   # Slowest (at NVDA rate 0)
    RATE_MAX = 3.0   # Fastest (at NVDA rate 100)

    # Pitch: Maps to F0Hz
    PITCH_MIN = 70.0
    PITCH_MAX = 250.0
    PITCH_DEFAULT = 120.0

    # Volume: Maps to Gain0 (dB)
    GAIN_MIN = 30.0
    GAIN_MAX = 70.0
    GAIN_DEFAULT = 57.0

    # Voice presets for variant support
    PRESETS: Dict[str, Dict[str, Any]] = {
        'default': {
            'pitch': 95.0, 'gain': 57.0, 'flutter': 0, 'shimmer': 0, 'jitter': 0,
            'F4hz': 3900.0, 'B4hz': 400.0, 'F5hz': 4700.0, 'B5hz': 150.0,
            'F6hz': 4900.0, 'B6phz': 800.0, 'B4phz': 500.0, 'B5phz': 600.0,
            'FNPhz': 270.0, 'BNhz': 500.0,
            'F1_offset': 0.0, 'F1_scale': 100.0,
            'F2_offset': 0.0, 'F2_scale': 100.0,
            'F3_offset': 0.0, 'F3_scale': 100.0,
        },
        'male': {
            'pitch': 85.0, 'gain': 60.0, 'flutter': 5, 'shimmer': 3, 'jitter': 2,
            'F4hz': 3600.0, 'B4hz': 450.0, 'F5hz': 4400.0, 'B5hz': 180.0,
            'F6hz': 4700.0, 'B6phz': 850.0, 'B4phz': 550.0, 'B5phz': 650.0,
            'FNPhz': 250.0, 'BNhz': 450.0,
            'F1_offset': -50.0, 'F1_scale': 95.0,
            'F2_offset': -100.0, 'F2_scale': 95.0,
            'F3_offset': -150.0, 'F3_scale': 95.0,
        },
        'female': {
            'pitch': 165.0, 'gain': 55.0, 'flutter': 8, 'shimmer': 5, 'jitter': 3,
            'F4hz': 4200.0, 'B4hz': 350.0, 'F5hz': 5000.0, 'B5hz': 120.0,
            'F6hz': 5200.0, 'B6phz': 750.0, 'B4phz': 450.0, 'B5phz': 550.0,
            'FNPhz': 300.0, 'BNhz': 550.0,
            'F1_offset': 100.0, 'F1_scale': 110.0,
            'F2_offset': 150.0, 'F2_scale': 108.0,
            'F3_offset': 200.0, 'F3_scale': 105.0,
        },
        'clear': {
            'pitch': 110.0, 'gain': 62.0, 'flutter': 0, 'shimmer': 0, 'jitter': 0,
            'F4hz': 3900.0, 'B4hz': 300.0, 'F5hz': 4700.0, 'B5hz': 100.0,
            'F6hz': 4900.0, 'B6phz': 700.0, 'B4phz': 400.0, 'B5phz': 500.0,
            'FNPhz': 270.0, 'BNhz': 400.0,
            'F1_offset': 0.0, 'F1_scale': 100.0,
            'F2_offset': 0.0, 'F2_scale': 100.0,
            'F3_offset': 0.0, 'F3_scale': 100.0,
        },
    }

    supportedSettings = (
        BaseSynthDriver.VariantSetting(),
        BaseSynthDriver.RateSetting(),
        BaseSynthDriver.PitchSetting(),
        BaseSynthDriver.VolumeSetting(),
    )

    supportedCommands = frozenset({
        IndexCommand,
        BreakCommand,
        PitchCommand,
        RateCommand,
        VolumeCommand,
    })

    supportedNotifications = frozenset({
        synthDriverHandler.synthIndexReached,
        synthDriverHandler.synthDoneSpeaking,
    })

    @classmethod
    def check(cls):
        """Check if the synthesizer is available."""
        # Pure Python - always available
        return True

    def _load_preset(self) -> Dict[str, Any]:
        """Load default preset from JSON file."""
        preset_path = os.path.join(os.path.dirname(__file__), '..', 'default.json')
        if os.path.exists(preset_path):
            try:
                with open(preset_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"Failed to load preset: {e}")
        return {}

    def __init__(self):
        """Initialize the RSynth synthesizer."""
        super().__init__()

        # Load preset from JSON
        preset = self._load_preset()

        # Get pitch from preset (default 95 Hz for better clarity)
        pitch_hz = preset.get('pitch', 95.0)

        # Initialize synthesis components with preset values
        self._speaker = Speaker(
            F0Hz=pitch_hz,
            Gain0=preset.get('gain', 57.0),
            F4hz=preset.get('F4hz', 3900.0),
            B4hz=preset.get('B4hz', 400.0),
            F5hz=preset.get('F5hz', 4700.0),
            B5hz=preset.get('B5hz', 150.0),
            F6hz=preset.get('F6hz', 4900.0),
            B6phz=preset.get('B6phz', 800.0),
            B4phz=preset.get('B4phz', 500.0),
            B5phz=preset.get('B5phz', 600.0),
            FNPhz=preset.get('FNPhz', 270.0),
            BNhz=preset.get('BNhz', 500.0),
            F1_offset=preset.get('F1_offset', 0.0),
            F1_scale=preset.get('F1_scale', 100.0) / 100.0,
            F2_offset=preset.get('F2_offset', 0.0),
            F2_scale=preset.get('F2_scale', 100.0) / 100.0,
            F3_offset=preset.get('F3_offset', 0.0),
            F3_scale=preset.get('F3_scale', 100.0) / 100.0,
        )
        self._synth = KlattSynth(
            sample_rate=self.SAMPLE_RATE,
            ms_per_frame=self.MS_PER_FRAME,
            speaker=self._speaker,
        )
        self._frame_gen = FrameGenerator(
            sample_rate=self.SAMPLE_RATE,
            f0_default=pitch_hz,
        )

        # Voice quality from preset
        self._flutter = int(preset.get('flutter', 0))
        self._shimmer = int(preset.get('shimmer', 0))
        self._jitter = int(preset.get('jitter', 0))
        self._synth.flutter = self._flutter
        self._synth.shimmer = self._shimmer / 100.0
        self._synth.jitter = self._jitter / 100.0

        # Store flat_intonation setting from preset
        self._flat_intonation = preset.get('flat_intonation', False)

        # Current settings (NVDA 0-100 scale)
        self._rate = 30
        self._pitch = 10
        self._volume = 70

        # Audio player
        self._player: Optional[nvwave.WavePlayer] = None

        # Speech queue for background processing
        self._speechQueue: queue.Queue = queue.Queue()
        self._isSpeaking = False
        self._shouldStop = threading.Event()

        # Index tracking
        self._lastIndex: Optional[int] = None
        self._pendingIndex: Optional[int] = None  # For index synchronization with audio

        # Error recovery tracking
        self._consecutiveFailures: int = 0
        self._maxConsecutiveFailures: int = 5

        # Variant tracking
        self._variant: str = 'default'

        # Start background synthesis thread
        self._synthThread = threading.Thread(target=self._synthLoop, daemon=True)
        self._synthThread.start()

        log.debug("RSynth synthesizer initialized")

    def terminate(self) -> None:
        """Clean up resources."""
        self._shouldStop.set()
        self._speechQueue.put(None)  # Signal thread to exit
        if self._synthThread.is_alive():
            self._synthThread.join(timeout=2.0)
        if self._player:
            try:
                self._player.stop()
            except Exception:
                pass
            self._player = None
        log.debug("RSynth synthesizer terminated")

    # Rate property
    def _get_rate(self) -> int:
        return self._rate

    def _set_rate(self, value: int):
        """Set speech rate (0-100 scale from NVDA)."""
        self._rate = value
        # Convert 0-100 to speed multiplier
        # 0 -> RATE_MIN (0.5x), 100 -> RATE_MAX (3.0x)
        speed = self.RATE_MIN + (self.RATE_MAX - self.RATE_MIN) * (value / 100.0)
        # RSynth frame_gen.speed is inverted: higher = slower
        self._frame_gen.speed = 1.0 / speed

    # Pitch property
    def _get_pitch(self) -> int:
        return self._pitch

    def _set_pitch(self, value: int):
        """Set pitch (0-100 scale from NVDA)."""
        self._pitch = value
        # Convert 0-100 to F0Hz range
        f0 = self.PITCH_MIN + (self.PITCH_MAX - self.PITCH_MIN) * (value / 100.0)
        self._speaker.F0Hz = f0
        self._frame_gen.f0_default = f0

    # Volume property
    def _get_volume(self) -> int:
        return self._volume

    def _set_volume(self, value: int):
        """Set volume (0-100 scale from NVDA)."""
        self._volume = value
        # Convert 0-100 to gain dB
        gain = self.GAIN_MIN + (self.GAIN_MAX - self.GAIN_MIN) * (value / 100.0)
        self._speaker.Gain0 = gain

    # Flutter property (voice quality)
    def _get_flutter(self) -> int:
        return self._flutter

    def _set_flutter(self, value: int):
        """Set flutter (pitch modulation, 0-100)."""
        self._flutter = value
        self._synth.flutter = value  # Direct 0-100 scale

    # Shimmer property (voice quality)
    def _get_shimmer(self) -> int:
        return self._shimmer

    def _set_shimmer(self, value: int):
        """Set shimmer (amplitude modulation, 0-100)."""
        self._shimmer = value
        self._synth.shimmer = value / 100.0  # Convert to 0-1

    # Jitter property (voice quality)
    def _get_jitter(self) -> int:
        return self._jitter

    def _set_jitter(self, value: int):
        """Set jitter (pitch period variation, 0-100)."""
        self._jitter = value
        self._synth.jitter = value / 100.0  # Convert to 0-1

    def _synthLoop(self) -> None:
        """Background thread for synthesis processing."""
        while True:
            try:
                item = self._speechQueue.get(timeout=0.1)
                if item is None:
                    break  # Only exit on explicit shutdown

                # Skip if cancel was requested
                if self._shouldStop.is_set():
                    self._shouldStop.clear()  # Clear for next speech
                    self._speechQueue.task_done()
                    continue

                self._isSpeaking = True
                self._processSpeechItem(item)
                self._speechQueue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"RSynth synthesis error: {e}")

        self._isSpeaking = False

    def _processSpeechItem(self, item: Union[str, IndexCommand, BreakCommand, Tuple[str, float]]) -> None:
        """Process a single speech item."""
        if isinstance(item, str):
            # Pass pending index to synchronize with audio playback
            self._synthesizeText(item, pending_index=self._pendingIndex)
            self._pendingIndex = None
        elif isinstance(item, IndexCommand):
            # Store index to fire when audio plays, not immediately
            self._pendingIndex = item.index
        elif isinstance(item, BreakCommand):
            self._generateSilence(item.time, pending_index=self._pendingIndex)
            self._pendingIndex = None
        elif isinstance(item, tuple):
            # Handle queued prosody commands (pitch, rate, volume)
            cmd, multiplier = item
            if cmd == 'pitch':
                new_pitch = int(self._pitch * multiplier)
                self._set_pitch(max(0, min(100, new_pitch)))
            elif cmd == 'rate':
                new_rate = int(self._rate * multiplier)
                self._set_rate(max(0, min(100, new_rate)))
            elif cmd == 'volume':
                new_volume = int(self._volume * multiplier)
                self._set_volume(max(0, min(100, new_volume)))

    def _ensurePlayer(self) -> None:
        """Ensure the audio player is initialized."""
        if self._player is None:
            self._player = nvwave.WavePlayer(
                channels=self.CHANNELS,
                samplesPerSec=self.SAMPLE_RATE,
                bitsPerSample=self.BITS_PER_SAMPLE,
            )

    def _synthesizeText(self, text: str, pending_index: Optional[int] = None) -> None:
        """Synthesize text and stream to audio player.

        Args:
            text: The text to synthesize
            pending_index: Optional index to notify when audio finishes playing
        """
        if not text.strip():
            return

        if self._shouldStop.is_set():
            return

        self._ensurePlayer()

        try:
            # Step 1: Text to phonemes
            phonemes = text_to_phonemes(text)

            # Step 2: Phonemes to elements with F0 contour
            result = phonemes_to_elements(
                phonemes,
                speed=self._frame_gen.speed,
                f0_default=self._speaker.F0Hz,
                flat_intonation=self._flat_intonation,
            )
            elements = result[0]
            f0_contour = result[1]

            if not elements:
                return

            # Step 3: Reset synthesizer state
            self._synth.reset()
            self._frame_gen.reset()

            # Step 4: Generate audio frames and stream to player
            BUFFER_FRAMES = 10  # ~100ms of audio
            audio_buffer = array.array("h")  # signed 16-bit
            samples_per_frame = int(self.SAMPLE_RATE * self.MS_PER_FRAME / 1000)

            for f0_hz, params in self._frame_gen.generate_frames(elements, f0_contour):
                if self._shouldStop.is_set():
                    return

                # Generate frame samples
                frame_samples = self._synth.generate_frame(f0_hz, params)

                # Convert float samples to int16
                for sample in frame_samples:
                    sample_int = max(-32767, min(32767, int(sample)))
                    audio_buffer.append(sample_int)

                # Send buffer when full
                if len(audio_buffer) >= BUFFER_FRAMES * samples_per_frame:
                    self._player.feed(audio_buffer.tobytes())
                    audio_buffer = array.array("h")

            # Send remaining samples
            if audio_buffer:
                self._player.feed(audio_buffer.tobytes())

            # Mark utterance complete - blocks until audio finishes
            self._player.idle()

            # Fire index callback AFTER audio has finished playing
            if pending_index is not None:
                self._lastIndex = pending_index
                synthDriverHandler.synthIndexReached.notify(synth=self, index=pending_index)

            # Reset failure counter on success
            self._consecutiveFailures = 0

        except Exception as e:
            self._consecutiveFailures += 1
            log.error(f"RSynth synthesis error ({self._consecutiveFailures}/{self._maxConsecutiveFailures}): {e}")
            if self._consecutiveFailures >= self._maxConsecutiveFailures:
                log.critical("RSynth: Too many consecutive failures. Consider switching synthesizer.")

    def _generateSilence(self, duration_ms: int, pending_index: Optional[int] = None) -> None:
        """Generate silence for break commands.

        Args:
            duration_ms: Duration of silence in milliseconds
            pending_index: Optional index to notify when silence finishes playing
        """
        if duration_ms <= 0:
            return

        self._ensurePlayer()

        num_samples = int((self.SAMPLE_RATE * duration_ms) / 1000)
        silence = bytes(num_samples * 2)  # 2 bytes per sample (16-bit)
        self._player.feed(silence)

        # Fire index callback after silence is fed
        if pending_index is not None:
            self._lastIndex = pending_index
            synthDriverHandler.synthIndexReached.notify(synth=self, index=pending_index)

    def speak(self, speechSequence: List[Any]) -> None:
        """Process a speech sequence from NVDA.

        Args:
            speechSequence: List of text strings and speech commands
        """
        # Clear stop flag so new speech can proceed
        # (NVDA calls cancel() explicitly when it wants to interrupt)
        self._shouldStop.clear()

        text_buffer: List[str] = []

        for item in speechSequence:
            if isinstance(item, str):
                text_buffer.append(item)

            elif isinstance(item, IndexCommand):
                # Flush text buffer before index
                if text_buffer:
                    combined_text = " ".join(text_buffer)
                    self._speechQueue.put(combined_text)
                    text_buffer = []
                self._speechQueue.put(item)

            elif isinstance(item, BreakCommand):
                # Flush text buffer before break
                if text_buffer:
                    combined_text = " ".join(text_buffer)
                    self._speechQueue.put(combined_text)
                    text_buffer = []
                self._speechQueue.put(item)

            elif isinstance(item, PitchCommand):
                # Queue pitch change to apply at the right time in the audio stream
                if item.multiplier is not None:
                    # Flush text buffer before prosody change
                    if text_buffer:
                        combined_text = " ".join(text_buffer)
                        self._speechQueue.put(combined_text)
                        text_buffer = []
                    self._speechQueue.put(('pitch', item.multiplier))

            elif isinstance(item, RateCommand):
                # Queue rate change to apply at the right time in the audio stream
                if item.multiplier is not None:
                    # Flush text buffer before prosody change
                    if text_buffer:
                        combined_text = " ".join(text_buffer)
                        self._speechQueue.put(combined_text)
                        text_buffer = []
                    self._speechQueue.put(('rate', item.multiplier))

            elif isinstance(item, VolumeCommand):
                # Queue volume change to apply at the right time in the audio stream
                if item.multiplier is not None:
                    # Flush text buffer before prosody change
                    if text_buffer:
                        combined_text = " ".join(text_buffer)
                        self._speechQueue.put(combined_text)
                        text_buffer = []
                    self._speechQueue.put(('volume', item.multiplier))

        # Flush remaining text
        if text_buffer:
            combined_text = " ".join(text_buffer)
            self._speechQueue.put(combined_text)

    def cancel(self) -> None:
        """Stop speech immediately."""
        self._shouldStop.set()

        # Clear pending index
        self._pendingIndex = None

        # Clear the queue
        while not self._speechQueue.empty():
            try:
                self._speechQueue.get_nowait()
                self._speechQueue.task_done()
            except queue.Empty:
                break

        # Stop audio playback
        if self._player:
            try:
                self._player.stop()
            except Exception:
                pass

        self._isSpeaking = False
        # Don't clear _shouldStop here - let the thread see it and clear it

        # Notify NVDA
        synthDriverHandler.synthDoneSpeaking.notify(synth=self)

    def pause(self, switch: bool) -> None:
        """Pause or resume speech."""
        if self._player:
            self._player.pause(switch)

    def _get_lastIndex(self) -> Optional[int]:
        """Return the last index reached."""
        return self._lastIndex

    def _get_isSpeaking(self) -> bool:
        """Check if currently speaking."""
        return self._isSpeaking

    # Variant property for voice presets
    def _get_variant(self) -> str:
        """Return the current voice variant."""
        return self._variant

    def _set_variant(self, value: str) -> None:
        """Set the voice variant (preset)."""
        if value in self.PRESETS:
            self._variant = value
            self._applyPreset(self.PRESETS[value])
            log.debug(f"RSynth variant changed to: {value}")

    @property
    def availableVariants(self) -> Dict[str, VoiceInfo]:
        """Return available voice variants (presets)."""
        return {
            'default': VoiceInfo('default', 'Default'),
            'male': VoiceInfo('male', 'Male'),
            'female': VoiceInfo('female', 'Female'),
            'clear': VoiceInfo('clear', 'Clear'),
        }

    def _applyPreset(self, preset: Dict[str, Any]) -> None:
        """Apply a voice preset to the synthesizer.

        Args:
            preset: Dictionary of synthesis parameters
        """
        # Update speaker parameters
        if 'pitch' in preset:
            self._speaker.F0Hz = preset['pitch']
            self._frame_gen.f0_default = preset['pitch']
        if 'gain' in preset:
            self._speaker.Gain0 = preset['gain']

        # Formant parameters
        if 'F4hz' in preset:
            self._speaker.F4hz = preset['F4hz']
        if 'B4hz' in preset:
            self._speaker.B4hz = preset['B4hz']
        if 'F5hz' in preset:
            self._speaker.F5hz = preset['F5hz']
        if 'B5hz' in preset:
            self._speaker.B5hz = preset['B5hz']
        if 'F6hz' in preset:
            self._speaker.F6hz = preset['F6hz']
        if 'B6phz' in preset:
            self._speaker.B6phz = preset['B6phz']
        if 'B4phz' in preset:
            self._speaker.B4phz = preset['B4phz']
        if 'B5phz' in preset:
            self._speaker.B5phz = preset['B5phz']
        if 'FNPhz' in preset:
            self._speaker.FNPhz = preset['FNPhz']
        if 'BNhz' in preset:
            self._speaker.BNhz = preset['BNhz']

        # Formant scaling
        if 'F1_offset' in preset:
            self._speaker.F1_offset = preset['F1_offset']
        if 'F1_scale' in preset:
            self._speaker.F1_scale = preset['F1_scale'] / 100.0
        if 'F2_offset' in preset:
            self._speaker.F2_offset = preset['F2_offset']
        if 'F2_scale' in preset:
            self._speaker.F2_scale = preset['F2_scale'] / 100.0
        if 'F3_offset' in preset:
            self._speaker.F3_offset = preset['F3_offset']
        if 'F3_scale' in preset:
            self._speaker.F3_scale = preset['F3_scale'] / 100.0

        # Voice quality parameters
        if 'flutter' in preset:
            self._flutter = int(preset['flutter'])
            self._synth.flutter = self._flutter
        if 'shimmer' in preset:
            self._shimmer = int(preset['shimmer'])
            self._synth.shimmer = self._shimmer / 100.0
        if 'jitter' in preset:
            self._jitter = int(preset['jitter'])
            self._synth.jitter = self._jitter / 100.0

    @property
    def availableVoices(self) -> Dict[str, VoiceInfo]:
        """Return available voices. RSynth has one voice."""
        return {self.name: VoiceInfo(self.name, self.description)}
