"""
Debug script to analyze phoneme generation and synthesis parameters.
Run from the rsynth directory: python debug_synth.py
"""

import sys
sys.path.insert(0, '.')

from _rsynth.text2phone import say, text_to_phonemes
from _rsynth.phonemes import phonemes_to_elements, FrameGenerator, ELEMENTS
from _rsynth.elements import Param

# Threshold for voicing detection (tiny values like 0.001 should count as voiceless)
VOICING_THRESHOLD = 0.1

def debug_text(text: str, show_all_frames: bool = False):
    """Analyze how text is converted to speech parameters."""

    print(f"\n{'='*60}")
    print(f"DEBUGGING: \"{text}\"")
    print(f"{'='*60}")

    # Step 1: Word -> Phoneme mapping
    print("\n=== STEP 1: WORD -> PHONEME MAPPING ===")
    for word, phonemes in say(text):
        print(f"  {word:20} -> {phonemes}")

    # Step 2: Full phoneme string
    phonemes = text_to_phonemes(text)
    print(f"\n=== STEP 2: FULL PHONEME STRING ===")
    print(f"  {phonemes}")

    # Step 3: Element sequence
    result = phonemes_to_elements(phonemes, f0_default=120.0)
    elements = result[0]
    f0_contour = result[1] if len(result) > 1 else None
    print(f"\n=== STEP 3: ELEMENT SEQUENCE ===")
    total_dur = sum(dur for _, dur in elements)
    print(f"  Total duration: {total_dur} frames ({total_dur * 10}ms at 10ms/frame)")
    print(f"\n  {'Idx':>4} {'Element':>10} {'Dur':>5} {'Description'}")
    print(f"  {'-'*4} {'-'*10} {'-'*5} {'-'*30}")

    # Build reverse lookup from element index to name
    idx_to_name = {}
    for name, elem in ELEMENTS.items():
        idx_to_name[id(elem)] = name

    for elem_idx, dur in elements:
        # elem_idx is actually the Element object in this implementation
        elem_name = idx_to_name.get(id(elem_idx), str(elem_idx)[:10])
        print(f"  {id(elem_idx) % 10000:>4} {elem_name:>10} {dur:>5}")

    # Step 4: Frame-by-frame parameters
    frame_gen = FrameGenerator(f0_default=120.0)

    print(f"\n=== STEP 4: FRAME PARAMETERS ===")
    print(f"  {'Frame':>5} {'F0':>6} {'av':>8} {'avc':>8} {'af':>8} {'asp':>8} {'f1':>6} {'f2':>6} {'f3':>6}")
    print(f"  {'-'*5} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*6}")

    frames = list(frame_gen.generate_frames(elements, f0_contour))

    # Show all frames or just key transitions
    if show_all_frames or len(frames) <= 30:
        for frame_num, (f0_hz, params) in enumerate(frames):
            print(f"  {frame_num:>5} {f0_hz:>6.1f} {params[Param.av]:>8.2f} {params[Param.avc]:>8.2f} "
                  f"{params[Param.af]:>8.2f} {params[Param.asp]:>8.2f} "
                  f"{params[Param.f1]:>6.0f} {params[Param.f2]:>6.0f} {params[Param.f3]:>6.0f}")
    else:
        # Show first 10, middle 10, last 10
        print("  (Showing first 10, middle 10, last 10 frames)")
        for i in range(10):
            f0_hz, params = frames[i]
            print(f"  {i:>5} {f0_hz:>6.1f} {params[Param.av]:>8.2f} {params[Param.avc]:>8.2f} "
                  f"{params[Param.af]:>8.2f} {params[Param.asp]:>8.2f} "
                  f"{params[Param.f1]:>6.0f} {params[Param.f2]:>6.0f} {params[Param.f3]:>6.0f}")
        print("  ...")
        mid = len(frames) // 2
        for i in range(mid - 5, mid + 5):
            f0_hz, params = frames[i]
            print(f"  {i:>5} {f0_hz:>6.1f} {params[Param.av]:>8.2f} {params[Param.avc]:>8.2f} "
                  f"{params[Param.af]:>8.2f} {params[Param.asp]:>8.2f} "
                  f"{params[Param.f1]:>6.0f} {params[Param.f2]:>6.0f} {params[Param.f3]:>6.0f}")
        print("  ...")
        for i in range(len(frames) - 10, len(frames)):
            f0_hz, params = frames[i]
            print(f"  {i:>5} {f0_hz:>6.1f} {params[Param.av]:>8.2f} {params[Param.avc]:>8.2f} "
                  f"{params[Param.af]:>8.2f} {params[Param.asp]:>8.2f} "
                  f"{params[Param.f1]:>6.0f} {params[Param.f2]:>6.0f} {params[Param.f3]:>6.0f}")

    # Summary
    print(f"\n=== SUMMARY ===")
    voiced_frames = sum(1 for _, params in frames if params[Param.av] > VOICING_THRESHOLD or params[Param.avc] > VOICING_THRESHOLD)
    voiceless_frames = len(frames) - voiced_frames
    print(f"  Total frames: {len(frames)}")
    print(f"  Voiced frames (av>0 or avc>0): {voiced_frames}")
    print(f"  Voiceless frames: {voiceless_frames}")

    # Check final phoneme voicing
    print(f"\n=== FINAL FRAMES (last 5) ===")
    print(f"  Checking if final sound is voiced or voiceless:")
    for i in range(max(0, len(frames) - 5), len(frames)):
        f0_hz, params = frames[i]
        voicing = "VOICED" if params[Param.av] > VOICING_THRESHOLD else ("VOICE-BAR" if params[Param.avc] > VOICING_THRESHOLD else "VOICELESS")
        print(f"  Frame {i}: av={params[Param.av]:.2f}, avc={params[Param.avc]:.2f}, af={params[Param.af]:.2f} -> {voicing}")


if __name__ == "__main__":
    # Default test
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = "hackers"

    debug_text(text)

    # Also test the specific sentence
    if text == "hackers":
        print("\n" + "="*60)
        debug_text("All the cats are hackers")
