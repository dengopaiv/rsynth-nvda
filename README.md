# RSynth-NVDA

A Python port of the RSynth Klatt formant synthesizer, targeting NVDA screen reader integration.

## Overview

This project is a pure Python implementation of the classic RSynth text-to-speech engine, originally written in C by Nick Ing-Simmons. The goal is to create a lightweight, offline TTS engine suitable for accessibility applications, particularly as an NVDA synthesizer driver.

## Features

- **Pure Python** - No external dependencies for core synthesis
- **Klatt Formant Synthesis** - Classic cascade/parallel formant synthesizer
- **CMU Dictionary** - 130,000+ English word pronunciations included
- **Letter-to-Sound Rules** - Fallback for unknown words
- **Natural Voice Features** - Jitter, shimmer, and flutter for more natural speech

## Project Structure

```
_rsynth/
  __init__.py       - Package initialization (v1.1.0)
  klatt.py          - Klatt formant synthesizer
  phonemes.py       - Phoneme-to-element conversion
  elements.py       - Speech element definitions
  text2phone.py     - Text-to-phoneme conversion
  english_rules.py  - Letter-to-sound fallback rules
  cmudict.py        - CMU dictionary interface
  cmudict.txt       - CMU pronunciation dictionary data

rsynth_gui.py       - wxPython GUI for testing
build_exe.py        - PyInstaller build script
debug_synth.py      - Debug utility for analysis
```

## Help Wanted

We're looking for contributors to help improve this project. Here are the current areas that need work:

### Audio Quality Issues
- **Clicks and pops** at phoneme boundaries - transitions between sounds cause audible artifacts
- **Harsh sibilants** - S, SH, Z, and similar fricative sounds are too harsh/noisy
- **Unnatural prosody** - Pitch contours don't sound natural, especially in questions and statements

### Phoneme Processing
- **Stress placement** - Incorrect stress markers affecting intonation patterns
- **Phoneme mapping edge cases** - Some words produce incorrect or missing phoneme sequences
- **Technical vocabulary** - CMU dictionary gaps for programming terms, abbreviations, etc.

### Synthesis Parameters
- **Formant transitions** - Smoothing between phonemes needs tuning
- **Voicing timing** - Onset and offset of voiced sounds needs adjustment
- **Amplitude envelopes** - Overall loudness contour could be improved

### NVDA Integration
- **synthDriver wrapper** - Need help creating a proper NVDA synthesizer driver
- **Real-time streaming** - Audio output needs to work with NVDA's streaming model
- **Speech commands** - Support for rate, pitch, volume controls

### General
- Code review and cleanup
- Unit tests for synthesis components
- Documentation improvements

## Getting Started

### Requirements
- Python 3.10+
- wxPython (for GUI only)
- PyInstaller (for building executable)

### Running the GUI
```bash
python rsynth_gui.py
```

### Using as a Library
```python
from _rsynth import text_to_phonemes, phonemes_to_elements, KlattSynth, Speaker

# Convert text to phonemes
phonemes = text_to_phonemes("Hello world")

# Convert to synthesis elements
elements = phonemes_to_elements(phonemes)

# Synthesize audio
synth = KlattSynth(sample_rate=16000)
speaker = Speaker()
audio = synth.synthesize(elements, speaker)
```

## License

This project is licensed under the GNU Lesser General Public License (LGPL), as it is a derivative work of the original RSynth by Nick Ing-Simmons.

## Attribution

- **Original RSynth** - Nick Ing-Simmons (1994-2004), LGPL
- **CMU Pronouncing Dictionary** - Carnegie Mellon University, unrestricted use

## Contributing

If you're interested in helping, please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

Even small improvements to phoneme mappings or parameter tuning would be greatly appreciated!

## Contact

Issues and pull requests welcome at: https://github.com/dengopaiv/rsynth-nvda
