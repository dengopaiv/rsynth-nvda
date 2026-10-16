# Test harness for the RSynth driver inside a real NVDA. Belongs to no
# release: tests/nvda_test/make_bundle.py adds it to a copy of the add-on
# for C:\git\environment\test-addon.ps1, which runs NVDA on a throwaway
# profile. Every line it logs starts with RSYNTHTEST so a run can be read
# back out of the log.
#
# Copyright (c) 2026 the rsynth-nvda contributors. LGPL v2 or later.

import time

import core
import globalPluginHandler
import speech
import synthDriverHandler
from logHandler import log
from speech.commands import IndexCommand
from synthDriverHandler import synthDoneSpeaking, synthIndexReached

T0 = time.monotonic()


def L(msg):
	log.info(f"RSYNTHTEST {time.monotonic() - T0:7.3f} {msg}")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self.steps = [
			self.select,
			self.direct_with_indexes,
			self.through_speech_manager,
			self.cancel_long,
			self.after_cancel,
			self.rate_and_pitch,
			self.variant_11k,
			self.voice_rules,
			self.spelling,
			self.restore,
			self.finish,
		]
		synthIndexReached.register(self.on_index)
		synthDoneSpeaking.register(self.on_done)
		core.callLater(3000, self.next)

	def terminate(self):
		synthIndexReached.unregister(self.on_index)
		synthDoneSpeaking.unregister(self.on_done)

	def on_index(self, synth=None, index=None):
		L(f"index {index} from {getattr(synth, 'name', synth)}")

	def on_done(self, synth=None):
		L(f"done from {getattr(synth, 'name', synth)}")

	def next(self, delay=0):
		if self.steps:
			step = self.steps.pop(0)

			def run():
				try:
					wait = step()
				except Exception:
					log.error("RSYNTHTEST step failed", exc_info=True)
					wait = 500
				core.callLater(wait or 2500, self.next)

			core.callLater(delay, run)

	# ---- steps; each returns how long to wait before the next ----------

	def select(self):
		ok = synthDriverHandler.setSynth("rsynth")
		s = synthDriverHandler.getSynth()
		L(f"setSynth ok={ok} synth={s.name} voice={s.voice} variant={s.variant} "
		  f"rate={s.rate} pitch={s.pitch} volume={s.volume}")
		L(f"voices={list(s.availableVoices)} variants={list(s.availableVariants)}")
		return 2000

	def direct_with_indexes(self):
		L("direct: speak with indexes 101, 102")
		synthDriverHandler.getSynth().speak(
			["Hello from R Synth.", IndexCommand(101), "This is the second part.", IndexCommand(102)],
		)
		return 6000

	def through_speech_manager(self):
		L("manager: speakMessage")
		speech.speakMessage("The speech manager is driving R Synth now. One, two, three.")
		return 6000

	def cancel_long(self):
		L("cancel: long text, cancel after 800 ms")
		speech.speakMessage(
			"This is a long passage that should be interrupted before it finishes, "
			"because the test cancels speech while it is still talking about nothing in particular. " * 3,
		)

		def cancel():
			L("cancel: cancelSpeech")
			speech.cancelSpeech()

		core.callLater(800, cancel)
		return 3000

	def after_cancel(self):
		L("after cancel: short text")
		speech.speakMessage("Speaking again after a cancel.")
		return 4000

	def rate_and_pitch(self):
		s = synthDriverHandler.getSynth()
		s.rate = 80
		s.pitch = 70
		L(f"rate={s.rate} pitch={s.pitch}")
		speech.speakMessage("Faster and higher, 1,234 people on the 21st.")
		return 5000

	def variant_11k(self):
		s = synthDriverHandler.getSynth()
		s.rate = 50
		s.pitch = 50
		s.variant = "11025"
		L(f"variant={s.variant}")
		speech.speakMessage("Eleven kilohertz, as the original ran.")
		return 5000

	def voice_rules(self):
		s = synthDriverHandler.getSynth()
		s.variant = "22050"
		s.voice = "rules"
		L(f"voice={s.voice} variant={s.variant}")
		speech.speakMessage("Letter to sound rules only, no dictionary.")
		return 5000

	def spelling(self):
		s = synthDriverHandler.getSynth()
		s.voice = "american"
		L("spelling: speakSpelling NVDA")
		speech.speakSpelling("NVDA")
		return 5000

	def restore(self):
		s = synthDriverHandler.getSynth()
		L(f"final voice={s.voice} variant={s.variant} rate={s.rate} pitch={s.pitch}")
		return 500

	def finish(self):
		L("END")
		return 500
