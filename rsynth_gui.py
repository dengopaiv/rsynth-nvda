"""
RSynth GUI Speech Synthesizer

A wxPython GUI application that exposes rsynth's speech synthesis parameters
as sliders, with text input, Play, Render to WAV, and Stop buttons.
"""

import sys
import os
import io
import wave
import array
import threading
import json

# Add rsynth module path (use local _rsynth copy)
rsynth_dir = os.path.dirname(os.path.abspath(__file__))
if rsynth_dir not in sys.path:
    sys.path.insert(0, rsynth_dir)

import wx

# Import from local _rsynth module
from _rsynth import (
    KlattSynth, Speaker, text_to_phonemes,
    phonemes_to_elements, FrameGenerator
)

# Try to import audio playback library
try:
    import simpleaudio as sa
    HAS_SIMPLEAUDIO = True
except ImportError:
    HAS_SIMPLEAUDIO = False
    import winsound

# Check if C extension is available
try:
    import _rsynth._klatt_c
    HAS_C_EXTENSION = True
except ImportError:
    HAS_C_EXTENSION = False


# --- Tooltips for all parameters ---
PARAM_TOOLTIPS = {
    'rate': "Speech speed multiplier. Higher = faster.",
    'pitch': "Base pitch frequency in Hz. Lower = deeper voice.",
    'gain': "Overall volume level in dB.",
    'jitter': "Random pitch variation for natural voice. 0% = robotic.",
    'shimmer': "Random amplitude variation. 0% = perfectly steady.",
    'flutter': "Slow pitch wobble for naturalness (Klatt & Klatt 1990).",
    'F1_offset': "Shift first formant (vowel quality). Positive = more open.",
    'F1_scale': "Scale first formant frequency. 100% = no change.",
    'F2_offset': "Shift second formant. Affects front/back vowel quality.",
    'F2_scale': "Scale second formant frequency. 100% = no change.",
    'F3_offset': "Shift third formant. Affects vowel color/rhoticity.",
    'F3_scale': "Scale third formant frequency. 100% = no change.",
    'F4hz': "Fourth formant frequency. Affects voice timbre.",
    'B4hz': "Fourth formant bandwidth. Wider = more damped.",
    'F5hz': "Fifth formant frequency. Affects upper voice quality.",
    'B5hz': "Fifth formant bandwidth. Wider = more damped.",
    'F6hz': "Sixth formant frequency (parallel path only).",
    'B6phz': "Sixth formant bandwidth (parallel path).",
    'B4phz': "Fourth formant parallel bandwidth (frication path).",
    'B5phz': "Fifth formant parallel bandwidth (frication path).",
    'FNPhz': "Nasal pole frequency. Affects nasal resonance.",
    'BNhz': "Nasal bandwidth. Wider = less nasal resonance.",
}

# --- Voice presets ---
VOICE_PRESETS = {
    "(Custom)": {},
    "Default Male": {
        'pitch': 120, 'gain': 57, 'jitter': 1.5, 'shimmer': 4.0, 'flutter': 20,
        'F1_scale': 100, 'F2_scale': 100, 'F3_scale': 100,
        'F1_offset': 0, 'F2_offset': 0, 'F3_offset': 0,
        'flat_intonation': False,
    },
    "Female": {
        'pitch': 200, 'gain': 57, 'jitter': 1.0, 'shimmer': 3.0, 'flutter': 25,
        'F1_scale': 110, 'F2_scale': 105, 'F3_scale': 105,
        'F1_offset': 50, 'F2_offset': 100, 'F3_offset': 50,
        'flat_intonation': False,
    },
    "Child": {
        'pitch': 280, 'gain': 57, 'jitter': 1.0, 'shimmer': 3.0, 'flutter': 15,
        'F1_scale': 115, 'F2_scale': 110, 'F3_scale': 110,
        'F1_offset': 100, 'F2_offset': 150, 'F3_offset': 100,
        'flat_intonation': False,
    },
    "Deep Male": {
        'pitch': 85, 'gain': 60, 'jitter': 2.0, 'shimmer': 5.0, 'flutter': 20,
        'F1_scale': 95, 'F2_scale': 95, 'F3_scale': 95,
        'F1_offset': -50, 'F2_offset': -50, 'F3_offset': -30,
        'flat_intonation': False,
    },
    "Robot": {
        'pitch': 120, 'gain': 57, 'jitter': 0, 'shimmer': 0, 'flutter': 0,
        'F1_scale': 100, 'F2_scale': 100, 'F3_scale': 100,
        'F1_offset': 0, 'F2_offset': 0, 'F3_offset': 0,
        'flat_intonation': True,
    },
}


class RSynthEngine:
    """Wrapper for rsynth synthesis with parameter control."""

    def __init__(self):
        self.sample_rate = 22050
        self.ms_per_frame = 10.0

        # Default parameters
        self.defaults = {
            # Basic controls
            'rate': 1.0,
            'pitch': 120.0,
            'gain': 57.0,
            # Voice quality
            'jitter': 1.5,
            'shimmer': 4.0,
            'flutter': 20,
            'flat_intonation': False,
            # Formants
            'F4hz': 3900.0,
            'B4hz': 400.0,
            'F5hz': 4700.0,
            'B5hz': 150.0,
            'F6hz': 4900.0,
            # Note: No B6hz - F6 only has parallel resonator in Klatt model
            # Nasal
            'FNPhz': 270.0,
            'BNhz': 500.0,
            # Parallel formant bandwidths (frication path)
            'B4phz': 500.0,
            'B5phz': 600.0,
            'B6phz': 800.0,
            # F1/F2/F3 offset and scale (applied to phoneme values)
            'F1_offset': 0.0,
            'F1_scale': 100.0,  # Percentage
            'F2_offset': 0.0,
            'F2_scale': 100.0,
            'F3_offset': 0.0,
            'F3_scale': 100.0,
        }

        # Current parameters
        self.params = self.defaults.copy()

        # Synthesis objects
        self._init_synth()

    def _init_synth(self):
        """Initialize synthesis objects with current parameters."""
        self.speaker = Speaker(
            F0Hz=self.params['pitch'],
            Gain0=self.params['gain'],
            F4hz=self.params['F4hz'],
            B4hz=self.params['B4hz'],
            F5hz=self.params['F5hz'],
            B5hz=self.params['B5hz'],
            F6hz=self.params['F6hz'],
            FNPhz=self.params['FNPhz'],
            BNhz=self.params['BNhz'],
            B4phz=self.params['B4phz'],
            B5phz=self.params['B5phz'],
            B6phz=self.params['B6phz'],
            F1_offset=self.params['F1_offset'],
            F1_scale=self.params['F1_scale'] / 100.0,
            F2_offset=self.params['F2_offset'],
            F2_scale=self.params['F2_scale'] / 100.0,
            F3_offset=self.params['F3_offset'],
            F3_scale=self.params['F3_scale'] / 100.0,
        )

        self.synth = KlattSynth(
            sample_rate=self.sample_rate,
            ms_per_frame=self.ms_per_frame,
            speaker=self.speaker
        )

        self.frame_gen = FrameGenerator(
            sample_rate=self.sample_rate,
            f0_default=self.params['pitch']
        )

    def update_params(self, **kwargs):
        """Update synthesis parameters."""
        self.params.update(kwargs)

        # Update speaker
        self.speaker.F0Hz = self.params['pitch']
        self.speaker.Gain0 = self.params['gain']
        self.speaker.F4hz = self.params['F4hz']
        self.speaker.B4hz = self.params['B4hz']
        self.speaker.F5hz = self.params['F5hz']
        self.speaker.B5hz = self.params['B5hz']
        self.speaker.F6hz = self.params['F6hz']
        self.speaker.FNPhz = self.params['FNPhz']
        self.speaker.BNhz = self.params['BNhz']
        self.speaker.B4phz = self.params['B4phz']
        self.speaker.B5phz = self.params['B5phz']
        self.speaker.B6phz = self.params['B6phz']

        # Update F1/F2/F3 offset and scale
        self.speaker.F1_offset = self.params['F1_offset']
        self.speaker.F1_scale = self.params['F1_scale'] / 100.0  # Convert from % to multiplier
        self.speaker.F2_offset = self.params['F2_offset']
        self.speaker.F2_scale = self.params['F2_scale'] / 100.0
        self.speaker.F3_offset = self.params['F3_offset']
        self.speaker.F3_scale = self.params['F3_scale'] / 100.0

        # Update synth voice quality
        self.synth.jitter = self.params['jitter'] / 100.0
        self.synth.shimmer = self.params['shimmer'] / 100.0
        self.synth.flutter = int(self.params['flutter'])

        # Update frame generator (invert rate so higher value = faster speech)
        self.frame_gen.speed = 1.0 / self.params['rate']
        self.frame_gen.f0_default = self.params['pitch']

    def reset_to_defaults(self):
        """Reset all parameters to defaults."""
        self.params = self.defaults.copy()
        self._init_synth()
        self.update_params()

    def synthesize(self, text, progress_callback=None):
        """
        Synthesize text to audio samples.

        Args:
            text: Text to synthesize
            progress_callback: Optional callable(current, total) for progress

        Returns:
            bytes: Audio data as int16 samples
        """
        if not text.strip():
            return bytes()

        # Ensure parameters are applied
        self.update_params()

        # Convert text to phonemes
        phonemes = text_to_phonemes(text)

        # Convert to elements with F0 contour (invert rate so higher = faster)
        result = phonemes_to_elements(
            phonemes,
            speed=1.0 / self.params['rate'],
            f0_default=self.params['pitch'],
            flat_intonation=self.params['flat_intonation']
        )
        elements = result[0]
        f0_contour = result[1]
        # result[2] is word boundaries (optional, not used here)

        # Generate audio
        self.synth.reset()
        self.frame_gen.reset()

        audio = array.array('h')  # signed 16-bit

        # Pre-collect frames for progress reporting
        frames = list(self.frame_gen.generate_frames(elements, f0_contour))
        total_frames = len(frames)

        for i, (f0_hz, params) in enumerate(frames):
            frame_samples = self.synth.generate_frame(f0_hz, params)
            for sample in frame_samples:
                # Clip to int16 range
                sample = max(-32767, min(32767, int(sample)))
                audio.append(sample)
            if progress_callback and (i % 10 == 0 or i == total_frames - 1):
                progress_callback(i + 1, total_frames)

        # Apply short fade-in/fade-out to prevent residual clicks
        fade_len = int(0.003 * self.sample_rate)  # 3ms
        n = len(audio)
        for i in range(min(fade_len, n)):
            audio[i] = int(audio[i] * i / fade_len)
        for i in range(min(fade_len, n)):
            audio[n - 1 - i] = int(audio[n - 1 - i] * i / fade_len)

        return audio.tobytes()

    def save_wav(self, audio_bytes, filename):
        """Save audio bytes to a WAV file."""
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_bytes)


class SliderPanel(wx.Panel):
    """A labeled slider with value display."""

    def __init__(self, parent, label, min_val, max_val, default_val,
                 multiplier=1.0, unit="", decimal_places=1,
                 param_name="", tooltip=""):
        super().__init__(parent)

        self.multiplier = multiplier
        self.unit = unit
        self.decimal_places = decimal_places

        # Convert to integer range for slider
        self.scale = 10 ** decimal_places
        self.min_int = int(min_val * self.scale)
        self.max_int = int(max_val * self.scale)
        self.default_int = int(default_val * self.scale)

        sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Label
        label_text = wx.StaticText(self, label=label, size=(100, -1))
        sizer.Add(label_text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)

        # Slider
        self.slider = wx.Slider(
            self, value=self.default_int,
            minValue=self.min_int, maxValue=self.max_int,
            style=wx.SL_HORIZONTAL
        )
        sizer.Add(self.slider, 1, wx.EXPAND | wx.RIGHT, 5)

        # Accessible name for screen readers
        accessible_label = label.rstrip(':')
        self.slider.SetName(f"{accessible_label}, {min_val} to {max_val}{unit}")

        # Tooltip
        if tooltip:
            self.SetToolTip(tooltip)
            self.slider.SetToolTip(tooltip)

        # Value display
        self.value_text = wx.StaticText(self, label="", size=(80, -1))
        sizer.Add(self.value_text, 0, wx.ALIGN_CENTER_VERTICAL)

        self.SetSizer(sizer)
        self._update_value_display()

        # Bind events
        self.slider.Bind(wx.EVT_SLIDER, self._on_slider)
        self.slider.Bind(wx.EVT_KEY_DOWN, self._on_key)

    def _on_slider(self, event):
        self._update_value_display()
        event.Skip()

    def _on_key(self, event):
        """Handle key press - D resets to default."""
        if event.GetKeyCode() == ord('D') or event.GetKeyCode() == ord('d'):
            self.reset()
        else:
            event.Skip()

    def _update_value_display(self):
        val = self.get_value()
        if self.decimal_places == 0:
            text = f"{int(val)}{self.unit}"
        else:
            text = f"{val:.{self.decimal_places}f}{self.unit}"
        self.value_text.SetLabel(text)

    def get_value(self):
        """Get the current slider value."""
        return self.slider.GetValue() / self.scale * self.multiplier

    def set_value(self, value):
        """Set the slider value."""
        int_val = int(value / self.multiplier * self.scale)
        int_val = max(self.min_int, min(self.max_int, int_val))
        self.slider.SetValue(int_val)
        self._update_value_display()

    def reset(self):
        """Reset to default value."""
        self.slider.SetValue(self.default_int)
        self._update_value_display()


class RSynthFrame(wx.Frame):
    """Main application window."""

    def __init__(self):
        super().__init__(
            None,
            title="RSynth Speech Synthesizer",
            size=(600, 750)
        )

        self.engine = RSynthEngine()
        self.play_obj = None
        self.is_playing = False
        self.synth_thread = None
        self.preset_dir = ""  # Remember last preset folder
        self._play_lock = threading.Lock()
        self._wav_buffer = None

        self._create_menu_bar()
        self._create_ui()
        self._bind_events()

        # Center on screen
        self.Centre()

        # Show C extension status
        if HAS_C_EXTENSION:
            self.SetStatusText("Ready (C acceleration active)")
        else:
            self.SetStatusText("Ready (Python fallback)")

    def _create_menu_bar(self):
        """Create the menu bar with File and Help menus."""
        menu_bar = wx.MenuBar()

        # File menu
        file_menu = wx.Menu()
        self.menu_save_preset = file_menu.Append(wx.ID_SAVE, "&Save Preset\tCtrl+S")
        self.menu_load_preset = file_menu.Append(wx.ID_OPEN, "&Open Preset\tCtrl+O")
        file_menu.AppendSeparator()
        self.menu_exit = file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        menu_bar.Append(file_menu, "&File")

        # Help menu
        help_menu = wx.Menu()
        self.menu_about = help_menu.Append(wx.ID_ABOUT, "&About")
        menu_bar.Append(help_menu, "&Help")

        self.SetMenuBar(menu_bar)

    def _create_ui(self):
        """Create the user interface."""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Text input
        text_box = wx.StaticBox(panel, label="Text to Synthesize")
        text_sizer = wx.StaticBoxSizer(text_box, wx.VERTICAL)

        self.text_ctrl = wx.TextCtrl(
            panel,
            value="Hello world. This is a test of the RSynth speech synthesizer.",
            style=wx.TE_MULTILINE,
            size=(-1, 80)
        )
        self.text_ctrl.SetName("Text to synthesize")
        text_sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(text_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.play_btn = wx.Button(panel, label="&Play")
        self.render_btn = wx.Button(panel, label="&Render to WAV")
        self.stop_btn = wx.Button(panel, label="&Stop")
        self.stop_btn.Enable(False)

        btn_sizer.Add(self.play_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(self.render_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(self.stop_btn, 0)

        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)

        # Progress gauge
        self.progress_gauge = wx.Gauge(panel, range=100, size=(-1, 16),
                                       style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        self.progress_gauge.SetName("Synthesis progress")
        self.progress_gauge.Hide()
        main_sizer.Add(self.progress_gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Scrolled window for sliders
        scroll = wx.ScrolledWindow(panel, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 20)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        # Voice preset selector
        preset_choice_sizer = wx.BoxSizer(wx.HORIZONTAL)
        preset_label = wx.StaticText(scroll, label="Voice Preset:")
        preset_choice_sizer.Add(preset_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.preset_combo = wx.ComboBox(
            scroll, choices=list(VOICE_PRESETS.keys()),
            style=wx.CB_READONLY
        )
        self.preset_combo.SetSelection(0)
        self.preset_combo.SetName("Voice preset")
        self.preset_combo.SetToolTip("Select a built-in voice preset to apply.")
        preset_choice_sizer.Add(self.preset_combo, 1, wx.EXPAND)
        scroll_sizer.Add(preset_choice_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Basic Controls
        basic_box = wx.StaticBox(scroll, label="Basic Controls")
        basic_sizer = wx.StaticBoxSizer(basic_box, wx.VERTICAL)

        self.sliders = {}

        self.sliders['rate'] = SliderPanel(
            scroll, "Rate:", 0.5, 2.0, 1.0,
            unit="x", decimal_places=2,
            param_name='rate', tooltip=PARAM_TOOLTIPS['rate']
        )
        basic_sizer.Add(self.sliders['rate'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['pitch'] = SliderPanel(
            scroll, "Pitch:", 50, 300, 120,
            unit=" Hz", decimal_places=0,
            param_name='pitch', tooltip=PARAM_TOOLTIPS['pitch']
        )
        basic_sizer.Add(self.sliders['pitch'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['gain'] = SliderPanel(
            scroll, "Gain:", 0, 70, 57,
            unit=" dB", decimal_places=0,
            param_name='gain', tooltip=PARAM_TOOLTIPS['gain']
        )
        basic_sizer.Add(self.sliders['gain'], 0, wx.EXPAND | wx.ALL, 2)

        scroll_sizer.Add(basic_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Voice Quality
        voice_box = wx.StaticBox(scroll, label="Voice Quality")
        voice_sizer = wx.StaticBoxSizer(voice_box, wx.VERTICAL)

        self.sliders['jitter'] = SliderPanel(
            scroll, "Jitter:", 0, 10, 1.5,
            unit="%", decimal_places=1,
            param_name='jitter', tooltip=PARAM_TOOLTIPS['jitter']
        )
        voice_sizer.Add(self.sliders['jitter'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['shimmer'] = SliderPanel(
            scroll, "Shimmer:", 0, 20, 4.0,
            unit="%", decimal_places=1,
            param_name='shimmer', tooltip=PARAM_TOOLTIPS['shimmer']
        )
        voice_sizer.Add(self.sliders['shimmer'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['flutter'] = SliderPanel(
            scroll, "Flutter:", 0, 100, 20,
            unit="", decimal_places=0,
            param_name='flutter', tooltip=PARAM_TOOLTIPS['flutter']
        )
        voice_sizer.Add(self.sliders['flutter'], 0, wx.EXPAND | wx.ALL, 2)

        # Flat intonation checkbox for robotic monotone voice
        self.flat_intonation_cb = wx.CheckBox(scroll, label="Flat &Intonation (robotic)")
        self.flat_intonation_cb.SetToolTip("Remove pitch variation for a monotone robotic voice.")
        voice_sizer.Add(self.flat_intonation_cb, 0, wx.EXPAND | wx.ALL, 5)

        scroll_sizer.Add(voice_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Formant Parameters
        formant_box = wx.StaticBox(scroll, label="Formant Parameters")
        formant_sizer = wx.StaticBoxSizer(formant_box, wx.VERTICAL)

        # F1/F2/F3 offset and scale controls (applied to phoneme values)
        self.sliders['F1_offset'] = SliderPanel(
            scroll, "F1 Offset:", -500, 500, 0,
            unit=" Hz", decimal_places=0,
            param_name='F1_offset', tooltip=PARAM_TOOLTIPS['F1_offset']
        )
        formant_sizer.Add(self.sliders['F1_offset'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F1_scale'] = SliderPanel(
            scroll, "F1 Scale:", 50, 150, 100,
            unit="%", decimal_places=0,
            param_name='F1_scale', tooltip=PARAM_TOOLTIPS['F1_scale']
        )
        formant_sizer.Add(self.sliders['F1_scale'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F2_offset'] = SliderPanel(
            scroll, "F2 Offset:", -500, 500, 0,
            unit=" Hz", decimal_places=0,
            param_name='F2_offset', tooltip=PARAM_TOOLTIPS['F2_offset']
        )
        formant_sizer.Add(self.sliders['F2_offset'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F2_scale'] = SliderPanel(
            scroll, "F2 Scale:", 50, 150, 100,
            unit="%", decimal_places=0,
            param_name='F2_scale', tooltip=PARAM_TOOLTIPS['F2_scale']
        )
        formant_sizer.Add(self.sliders['F2_scale'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F3_offset'] = SliderPanel(
            scroll, "F3 Offset:", -500, 500, 0,
            unit=" Hz", decimal_places=0,
            param_name='F3_offset', tooltip=PARAM_TOOLTIPS['F3_offset']
        )
        formant_sizer.Add(self.sliders['F3_offset'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F3_scale'] = SliderPanel(
            scroll, "F3 Scale:", 50, 150, 100,
            unit="%", decimal_places=0,
            param_name='F3_scale', tooltip=PARAM_TOOLTIPS['F3_scale']
        )
        formant_sizer.Add(self.sliders['F3_scale'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F4hz'] = SliderPanel(
            scroll, "F4 Freq:", 2500, 5000, 3900,
            unit=" Hz", decimal_places=0,
            param_name='F4hz', tooltip=PARAM_TOOLTIPS['F4hz']
        )
        formant_sizer.Add(self.sliders['F4hz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['B4hz'] = SliderPanel(
            scroll, "F4 BW:", 100, 1000, 400,
            unit=" Hz", decimal_places=0,
            param_name='B4hz', tooltip=PARAM_TOOLTIPS['B4hz']
        )
        formant_sizer.Add(self.sliders['B4hz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F5hz'] = SliderPanel(
            scroll, "F5 Freq:", 3000, 6000, 4700,
            unit=" Hz", decimal_places=0,
            param_name='F5hz', tooltip=PARAM_TOOLTIPS['F5hz']
        )
        formant_sizer.Add(self.sliders['F5hz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['B5hz'] = SliderPanel(
            scroll, "F5 BW:", 50, 600, 150,
            unit=" Hz", decimal_places=0,
            param_name='B5hz', tooltip=PARAM_TOOLTIPS['B5hz']
        )
        formant_sizer.Add(self.sliders['B5hz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['F6hz'] = SliderPanel(
            scroll, "F6 Freq:", 4000, 7000, 4900,
            unit=" Hz", decimal_places=0,
            param_name='F6hz', tooltip=PARAM_TOOLTIPS['F6hz']
        )
        formant_sizer.Add(self.sliders['F6hz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['B6phz'] = SliderPanel(
            scroll, "F6 BW:", 100, 1500, 800,
            unit=" Hz", decimal_places=0,
            param_name='B6phz', tooltip=PARAM_TOOLTIPS['B6phz']
        )
        formant_sizer.Add(self.sliders['B6phz'], 0, wx.EXPAND | wx.ALL, 2)

        # Parallel formant bandwidths for F4/F5 (frication path)
        self.sliders['B4phz'] = SliderPanel(
            scroll, "F4 Par BW:", 100, 1000, 500,
            unit=" Hz", decimal_places=0,
            param_name='B4phz', tooltip=PARAM_TOOLTIPS['B4phz']
        )
        formant_sizer.Add(self.sliders['B4phz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['B5phz'] = SliderPanel(
            scroll, "F5 Par BW:", 100, 1200, 600,
            unit=" Hz", decimal_places=0,
            param_name='B5phz', tooltip=PARAM_TOOLTIPS['B5phz']
        )
        formant_sizer.Add(self.sliders['B5phz'], 0, wx.EXPAND | wx.ALL, 2)

        scroll_sizer.Add(formant_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Nasal Parameters
        nasal_box = wx.StaticBox(scroll, label="Nasal Parameters")
        nasal_sizer = wx.StaticBoxSizer(nasal_box, wx.VERTICAL)

        self.sliders['FNPhz'] = SliderPanel(
            scroll, "Nasal Freq:", 200, 600, 270,
            unit=" Hz", decimal_places=0,
            param_name='FNPhz', tooltip=PARAM_TOOLTIPS['FNPhz']
        )
        nasal_sizer.Add(self.sliders['FNPhz'], 0, wx.EXPAND | wx.ALL, 2)

        self.sliders['BNhz'] = SliderPanel(
            scroll, "Nasal BW:", 100, 1000, 500,
            unit=" Hz", decimal_places=0,
            param_name='BNhz', tooltip=PARAM_TOOLTIPS['BNhz']
        )
        nasal_sizer.Add(self.sliders['BNhz'], 0, wx.EXPAND | wx.ALL, 2)

        scroll_sizer.Add(nasal_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Reset button
        self.reset_btn = wx.Button(scroll, label="Reset to &Defaults")
        scroll_sizer.Add(self.reset_btn, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)

        scroll.SetSizer(scroll_sizer)
        main_sizer.Add(scroll, 1, wx.EXPAND)

        # Status bar
        self.CreateStatusBar()

        panel.SetSizer(main_sizer)

    def _bind_events(self):
        """Bind event handlers."""
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_play)
        self.render_btn.Bind(wx.EVT_BUTTON, self.on_render)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.reset_btn.Bind(wx.EVT_BUTTON, self.on_reset)
        self.preset_combo.Bind(wx.EVT_COMBOBOX, self.on_voice_preset)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        # Menu events
        self.Bind(wx.EVT_MENU, self.on_save_preset, self.menu_save_preset)
        self.Bind(wx.EVT_MENU, self.on_load_preset, self.menu_load_preset)
        self.Bind(wx.EVT_MENU, self.on_close, self.menu_exit)
        self.Bind(wx.EVT_MENU, self.on_about, self.menu_about)

        # Keyboard shortcuts (Alt+P and Alt+R handled by button mnemonics)
        play_id = wx.NewIdRef()
        render_id = wx.NewIdRef()
        reset_id = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self.on_play, id=play_id)
        self.Bind(wx.EVT_MENU, self.on_render, id=render_id)
        self.Bind(wx.EVT_MENU, self.on_reset, id=reset_id)
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_ALT, ord('P'), play_id),
            (wx.ACCEL_ALT, ord('R'), render_id),
            (wx.ACCEL_ALT, ord('D'), reset_id),
        ])
        self.SetAcceleratorTable(accel_tbl)

    def _get_params_from_sliders(self):
        """Get current parameter values from all sliders and checkboxes."""
        params = {name: slider.get_value() for name, slider in self.sliders.items()}
        params['flat_intonation'] = self.flat_intonation_cb.GetValue()
        return params

    def _synthesize(self, text, progress_callback=None):
        """Synthesize text with current parameters."""
        params = self._get_params_from_sliders()
        self.engine.update_params(**params)
        return self.engine.synthesize(text, progress_callback=progress_callback)

    def _update_progress(self, current, total):
        """Update progress gauge from synthesis thread."""
        pct = int(current * 100 / total) if total > 0 else 0
        wx.CallAfter(self.progress_gauge.SetValue, pct)

    def _build_wav_buffer(self, audio_bytes):
        """Build an in-memory WAV buffer from raw audio bytes."""
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.engine.sample_rate)
            wf.writeframes(audio_bytes)
        return buf.getvalue()

    def on_play(self, event):
        """Handle Play button click."""
        text = self.text_ctrl.GetValue()
        if not text.strip():
            self.SetStatusText("No text to synthesize")
            return

        self.play_btn.Enable(False)
        self.render_btn.Enable(False)
        self.stop_btn.Enable(True)
        self.progress_gauge.SetValue(0)
        self.progress_gauge.Show()
        self.GetSizer()  # force layout
        self.Layout()
        self.SetStatusText("Synthesizing...")

        # Run synthesis in background thread
        def synth_and_play():
            try:
                audio_bytes = self._synthesize(text, progress_callback=self._update_progress)

                if not audio_bytes:
                    wx.CallAfter(self._on_play_done, "No audio generated")
                    return

                # Play audio
                with self._play_lock:
                    if HAS_SIMPLEAUDIO:
                        self.play_obj = sa.play_buffer(
                            audio_bytes,
                            num_channels=1,
                            bytes_per_sample=2,
                            sample_rate=self.engine.sample_rate
                        )
                        self.is_playing = True
                    else:
                        self._wav_buffer = self._build_wav_buffer(audio_bytes)
                        self.is_playing = True

                wx.CallAfter(self.SetStatusText, "Playing...")

                if HAS_SIMPLEAUDIO:
                    self.play_obj.wait_done()
                    with self._play_lock:
                        self.is_playing = False
                else:
                    winsound.PlaySound(self._wav_buffer, winsound.SND_MEMORY)
                    with self._play_lock:
                        self.is_playing = False

                wx.CallAfter(self._on_play_done, "Playback finished")

            except Exception as e:
                wx.CallAfter(self._on_play_done, f"Error: {str(e)}")

        self.synth_thread = threading.Thread(target=synth_and_play, daemon=True)
        self.synth_thread.start()

    def _on_play_done(self, message):
        """Called when playback is complete."""
        self.play_btn.Enable(True)
        self.render_btn.Enable(True)
        self.stop_btn.Enable(False)
        self.progress_gauge.Hide()
        self.Layout()
        self.SetStatusText(message)

    def on_render(self, event):
        """Handle Render to WAV button click."""
        text = self.text_ctrl.GetValue()
        if not text.strip():
            self.SetStatusText("No text to synthesize")
            return

        # Ask for save location
        with wx.FileDialog(
            self,
            "Save WAV file",
            wildcard="WAV files (*.wav)|*.wav",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return

            filename = dialog.GetPath()

        self.SetStatusText("Rendering...")
        self.play_btn.Enable(False)
        self.render_btn.Enable(False)
        self.progress_gauge.SetValue(0)
        self.progress_gauge.Show()
        self.Layout()

        def render_thread():
            try:
                audio_bytes = self._synthesize(text, progress_callback=self._update_progress)

                if not audio_bytes:
                    wx.CallAfter(self._on_render_done, "No audio generated", None)
                    return

                self.engine.save_wav(audio_bytes, filename)
                duration = len(audio_bytes) / 2 / self.engine.sample_rate
                wx.CallAfter(
                    self._on_render_done,
                    f"Saved {duration:.2f}s to {os.path.basename(filename)}",
                    filename
                )

            except Exception as e:
                wx.CallAfter(self._on_render_done, f"Error: {str(e)}", None)

        threading.Thread(target=render_thread, daemon=True).start()

    def _on_render_done(self, message, filename):
        """Called when rendering is complete."""
        self.play_btn.Enable(True)
        self.render_btn.Enable(True)
        self.progress_gauge.Hide()
        self.Layout()
        self.SetStatusText(message)

    def on_stop(self, event):
        """Handle Stop button click."""
        with self._play_lock:
            if HAS_SIMPLEAUDIO and self.play_obj and self.is_playing:
                self.play_obj.stop()
                self.is_playing = False
            elif not HAS_SIMPLEAUDIO and self.is_playing:
                winsound.PlaySound(None, winsound.SND_PURGE)
                self.is_playing = False
                self._wav_buffer = None
        self._on_play_done("Stopped")

    def on_reset(self, event):
        """Handle Reset button click."""
        self.engine.reset_to_defaults()
        for name, slider in self.sliders.items():
            slider.set_value(self.engine.defaults[name])
        self.flat_intonation_cb.SetValue(False)
        self.preset_combo.SetSelection(0)
        self.SetStatusText("Parameters reset to defaults")

    def on_voice_preset(self, event):
        """Handle voice preset selection."""
        name = self.preset_combo.GetValue()
        preset = VOICE_PRESETS.get(name, {})
        if not preset:
            return

        for param, value in preset.items():
            if param in self.sliders:
                self.sliders[param].set_value(value)
            elif param == 'flat_intonation':
                self.flat_intonation_cb.SetValue(bool(value))

        self.SetStatusText(f"Applied preset: {name}")

    def on_save_preset(self, event):
        """Handle Save Preset menu/button click."""
        # Get current parameters
        params = self._get_params_from_sliders()

        # Ask for save location
        with wx.FileDialog(
            self,
            "Save Preset",
            defaultDir=self.preset_dir,
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return

            filename = dialog.GetPath()

        try:
            with open(filename, 'w') as f:
                json.dump(params, f, indent=2)
            self.preset_dir = os.path.dirname(filename)
            self.SetStatusText(f"Preset saved to {os.path.basename(filename)}")
        except Exception as e:
            wx.MessageBox(f"Error saving preset: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)

    def on_load_preset(self, event):
        """Handle Load Preset menu/button click."""
        # Ask for file location
        with wx.FileDialog(
            self,
            "Load Preset",
            defaultDir=self.preset_dir,
            wildcard="JSON files (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return

            filename = dialog.GetPath()

        try:
            with open(filename, 'r') as f:
                params = json.load(f)

            # Apply loaded values to sliders
            for name, value in params.items():
                if name in self.sliders:
                    self.sliders[name].set_value(value)
                elif name == 'flat_intonation':
                    self.flat_intonation_cb.SetValue(bool(value))

            # Update engine
            self.engine.update_params(**params)
            self.preset_combo.SetSelection(0)  # Set to (Custom)
            self.preset_dir = os.path.dirname(filename)
            self.SetStatusText(f"Preset loaded from {os.path.basename(filename)}")
        except Exception as e:
            wx.MessageBox(f"Error loading preset: {str(e)}", "Error", wx.OK | wx.ICON_ERROR)

    def on_about(self, event):
        """Show About dialog."""
        info = wx.adv.AboutDialogInfo()
        info.SetName("RSynth Speech Synthesizer")
        info.SetDescription(
            "A Klatt formant speech synthesizer.\n\n"
            "Keyboard Shortcuts:\n"
            "  Alt+P  -  Play\n"
            "  Alt+R  -  Render to WAV\n"
            "  Alt+S  -  Stop\n"
            "  Alt+D  -  Reset to Defaults\n"
            "  Alt+I  -  Toggle Flat Intonation\n"
            "  Ctrl+S -  Save Preset\n"
            "  Ctrl+O -  Open Preset\n"
            "  D key  -  Reset focused slider to default"
        )
        info.SetCopyright("Based on Nick Ing-Simmons' RSynth")
        wx.adv.AboutBox(info)

    def on_close(self, event):
        """Handle window close."""
        with self._play_lock:
            if HAS_SIMPLEAUDIO and self.play_obj and self.is_playing:
                self.play_obj.stop()
            elif not HAS_SIMPLEAUDIO and self.is_playing:
                winsound.PlaySound(None, winsound.SND_PURGE)
                self._wav_buffer = None
        self.Destroy()


class RSynthApp(wx.App):
    """Main application class."""

    def OnInit(self):
        frame = RSynthFrame()
        frame.Show()
        return True


def main():
    """Main entry point."""
    app = RSynthApp()
    app.MainLoop()


if __name__ == '__main__':
    main()
