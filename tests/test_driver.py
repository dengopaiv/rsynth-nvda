"""Drive nvda-addon/addon/synthDrivers/rsynth.py without NVDA.

    python tests/test_driver.py

The NVDA modules the driver imports are replaced by small stand-ins that
record what the driver does: the audio it feeds, the index marks it
reports, when it says it is done. The driver and rsynth.dll are the real
ones (package.py copies the DLL beside the driver).

This proves the driver's own logic -- queueing, index marks, cancel,
settings, spelling -- and that the ctypes declarations match the DLL.
It does not prove the driver inside NVDA: NVDA's real player, its speech
manager and its settings dialogs are only reachable from NVDA itself.
See docs/05-nvda-driver.md for the in-NVDA test.
"""

import builtins
import importlib.util
import os
import sys
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(ROOT, "nvda-addon", "addon", "synthDrivers", "rsynth.py")

# --- stand-ins for NVDA ---------------------------------------------------

builtins._ = lambda s: s
events = []          # (kind, value) in the order they happened
events_lock = threading.Lock()


def record(kind, value=None):
	with events_lock:
		events.append((kind, value))


def module(name, **attrs):
	m = types.ModuleType(name)
	m.__dict__.update(attrs)
	sys.modules[name] = m
	return m


class WavePlayer:
	instances = []

	def __init__(self, channels, samplesPerSec, bitsPerSample, outputDevice=""):
		assert channels == 1 and bitsPerSample == 16
		self.samplesPerSec = samplesPerSec
		self.pending = []        # onDone callbacks not yet "played"
		self.fed = 0
		self.closed = False
		WavePlayer.instances.append(self)

	def feed(self, data, size=None, onDone=None):
		n = len(data) if size is None else size
		self.fed += n
		record("audio", n)
		# Pretend playback is a little behind, as the real player is.
		time.sleep(0.0005)
		if onDone:
			# Where in the audio the callback was attached; it fires later,
			# when the stand-in "finishes playing" at idle().
			record("mark")
			self.pending.append(onDone)

	def idle(self):
		for cb in self.pending:
			cb()
		self.pending.clear()
		record("idle")

	def stop(self):
		self.pending.clear()
		record("stop")

	def pause(self, switch):
		record("pause", switch)

	def close(self):
		self.closed = True


class Notifier:
	def __init__(self, kind):
		self.kind = kind

	def notify(self, synth=None, index=None):
		record(self.kind, index)


class _Prosody:
	def __init__(self, offset=0, multiplier=1):
		self.offset, self.multiplier = offset, multiplier

	@property
	def newValue(self):
		return int(50 * self.multiplier) + self.offset


class SynthDriverBase:
	# NVDA's AutoPropertyObject turns synth.rate = x into _set_rate(x); the
	# stand-in does not, so the tests call the accessors directly.
	@classmethod
	def VoiceSetting(cls):
		return "voice"

	VariantSetting = RateSetting = PitchSetting = VolumeSetting = VoiceSetting

	def __init__(self):
		pass

	def terminate(self):
		record("saved")


class VoiceInfo:
	def __init__(self, id, displayName, language=None):
		self.id, self.displayName, self.language = id, displayName, language


class Log:
	def info(self, msg, *a, **k):
		print("log:", msg)

	def error(self, msg, *a, **k):
		record("error", msg)
		import traceback

		traceback.print_exc()

	debug = debugWarning = info


module("addonHandler", initTranslation=lambda: None)
module("config", conf={"audio": {"outputDevice": "default"}})
module("nvwave", WavePlayer=WavePlayer)
module("logHandler", log=Log())
module("autoSettingsUtils")
module(
	"autoSettingsUtils.driverSetting",
	BooleanDriverSetting=lambda id, name, defaultVal=False: ("bool", id),
)
module("speech")
module(
	"speech.commands",
	IndexCommand=type("IndexCommand", (), {"__init__": lambda s, i: setattr(s, "index", i)}),
	CharacterModeCommand=type(
		"CharacterModeCommand", (), {"__init__": lambda s, st: setattr(s, "state", st)},
	),
	BreakCommand=type("BreakCommand", (), {"__init__": lambda s, t: setattr(s, "time", t)}),
	PitchCommand=type("PitchCommand", (_Prosody,), {}),
)
module(
	"synthDriverHandler",
	SynthDriver=SynthDriverBase,
	VoiceInfo=VoiceInfo,
	synthIndexReached=Notifier("index"),
	synthDoneSpeaking=Notifier("done"),
)

spec = importlib.util.spec_from_file_location("rsynth_driver", DRIVER)
drv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drv)
from speech.commands import BreakCommand, CharacterModeCommand, IndexCommand, PitchCommand  # noqa: E402

# --- tests ---------------------------------------------------------------

failures = 0


def check(cond, msg):
	global failures
	if not cond:
		failures += 1
		print("FAIL:", msg)


def wait_for(kind, timeout=20.0):
	end = time.time() + timeout
	while time.time() < end:
		with events_lock:
			if any(k == kind for k, _ in events):
				return True
		time.sleep(0.01)
	return False


def take():
	with events_lock:
		out = list(events)
		events.clear()
	return out


def audio_bytes(evs):
	return sum(v for k, v in evs if k == "audio")


check(drv.SynthDriver.check(), "check() false: is rsynth.dll beside the driver? Run package.py.")
synth = drv.SynthDriver()

# 1. Text, index marks, done -- in that order.
synth.speak(["Hello,", IndexCommand(1), "world.", IndexCommand(2)])
check(wait_for("done"), "never reported done")
evs = take()
kinds = [k for k, _ in evs if k in ("index", "done")]
check(kinds == ["index", "index", "done"], f"index/done order: {kinds}")
check([v for k, v in evs if k == "index"] == [1, 2], "index values")
marks = [i for i, (k, _) in enumerate(evs) if k == "mark"]
check(len(marks) == 2, f"{len(marks)} index callbacks attached, want 2")
if len(marks) == 2:
	check(audio_bytes(evs[: marks[0]]) > 0, "no audio before the first index")
	check(audio_bytes(evs[marks[0] : marks[1]]) > 0, "no audio between the index marks")
	check(audio_bytes(evs[marks[1] :]) == 0, "audio after the last index")
hello_bytes = audio_bytes(evs)

# 2. Cancel during a long utterance: audio stops, no done for it.
long_text = "This sentence goes on and on, clause after clause, for a long time. " * 20
synth.speak([long_text])
end = time.time() + 10
while time.time() < end and audio_bytes(list(events)) < 20000:
	time.sleep(0.005)
synth.cancel()
time.sleep(0.5)
evs = take()
stop_at = max(i for i, (k, _) in enumerate(evs) if k == "stop")
after = audio_bytes(evs[stop_at + 1 :])
check(after <= 2 * 1024 * 2, f"{after} bytes fed after the last stop")
check(not any(k == "done" for k, _ in evs), "done reported for a cancelled utterance")
total = audio_bytes(evs)
check(total < 22050 * 2 * 20, f"cancel did not stop synthesis ({total} bytes)")

# 3. A setting changed then a cancel: the setting survives.
synth._set_rate(100)
synth.cancel()
synth.speak(["Hello, world."])
check(wait_for("done"), "no done after a rate change")
fast = audio_bytes(take())
check(fast < hello_bytes * 0.6, f"rate 100 not faster: {fast} vs {hello_bytes}")
synth._set_rate(50)

# 4. Variant: a new sample rate means a new player.
synth._set_variant("11025")
synth.speak(["Eleven kilohertz."])
check(wait_for("done"), "no done after variant change")
take()
check(WavePlayer.instances[-1].samplesPerSec == 11025, "player not reopened at 11025")
synth._set_variant("22050")

# 5. Voices, pitch command, spelling, break, monotone, volume.
for voice in ("british", "rules", "american"):
	synth._set_voice(voice)
	synth.speak(["Schedule a tomato."])
	check(wait_for("done"), f"voice {voice}: no done")
	check(audio_bytes(take()) > 0, f"voice {voice}: no audio")
synth.speak([PitchCommand(offset=30), CharacterModeCommand(True), "A", CharacterModeCommand(False), PitchCommand()])
check(wait_for("done"), "spelling: no done")
check(audio_bytes(take()) > 0, "spelling: no audio")
synth.speak(["Before", BreakCommand(500), "after"])
check(wait_for("done"), "break: no done")
check(audio_bytes(take()) > 22050 * 2 * 0.5, "break shorter than 500 ms")
synth._set_monotone(True)
synth._set_volume(30)
synth.speak(["Flat and quiet."])
check(wait_for("done"), "monotone: no done")
check(audio_bytes(take()) > 0, "monotone: no audio")
check(synth._get_monotone() is True and synth._get_volume() == 30, "settings did not stick")

# 6. Hostile text does not take the driver down.
synth.speak(["日本語 \U0001f600 café [x] 12345678901234567890 \x00\x07"])
check(wait_for("done"), "hostile text: no done")
evs = take()
check(not any(k == "error" for k, _ in evs), "hostile text logged an error")

synth.terminate()
check(not synth._thread.is_alive(), "speak thread still alive after terminate")
check(any(k == "saved" for k, _ in take()), "base terminate (settings save) not called")

print("all passed" if not failures else f"{failures} failure(s)")
sys.exit(1 if failures else 0)
