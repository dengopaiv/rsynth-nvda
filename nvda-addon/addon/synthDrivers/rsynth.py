# NVDA synthesizer driver for RSynth, over the native library.
#
# Copyright (c) 2026 the rsynth-nvda contributors.
# Licensed under the GNU Library General Public License, version 2 or (at
# your option) any later version.  RSynth itself is by Nick Ing-Simmons,
# 1994-2004; see NOTICE.md in the add-on.
"""NVDA driver for RSynth: Nick Ing-Simmons' formant synthesizer, in C.

Everything that makes speech is inside rsynth.dll: the text front end, the
CMU pronouncing dictionary (compiled in), the NRL letter-to-sound rules,
the phone-to-element tables and the synthesizer.  This file only turns
NVDA's speech sequences into work for that library and its audio into
NVDA's player.

  rsynth.dll (ctypes) -- rs_* in include/rsynth_api.h
  SynthDriver         -- NVDA-facing; queues work, never synthesizes
  _speak_thread       -- the only thread that calls the engine after start

Cancellation is an epoch counter.  cancel() bumps it; queued work from an
older epoch is dropped, and the audio callback returns 1 the moment it sees
the epoch move, which stops synthesis inside the library at the next
element.  Settings changes are queued with no epoch, so a cancel never
loses one.

The add-on is 64-bit only, as NVDA 2026 is.
"""

import ctypes
import os
import queue
import threading

import addonHandler
import config
import nvwave
from autoSettingsUtils.driverSetting import BooleanDriverSetting
from logHandler import log
from speech.commands import (
	BreakCommand,
	CharacterModeCommand,
	IndexCommand,
	PitchCommand,
)
from synthDriverHandler import SynthDriver as BaseSynthDriver
from synthDriverHandler import VoiceInfo, synthDoneSpeaking, synthIndexReached

addonHandler.initTranslation()

_DIR = os.path.dirname(os.path.abspath(__file__))
_DLL = os.path.join(_DIR, "rsynth.dll")

#: Must match RS_API_VERSION in rsynth_api.h.
_API_VERSION = 1

#: Values of enum rs_lexicon.
_LEX_CMU_AMERICAN = 0
_LEX_CMU_BRITISH = 1
_LEX_RULES = 2
_SPEAK_SPELL = 1

#: voice id -> (display name, language, lexicon)
_VOICES = {
	# Translators: an RSynth voice: the CMU dictionary read with American phones.
	"american": (_("American (CMU dictionary)"), "en_US", _LEX_CMU_AMERICAN),
	# Translators: an RSynth voice: the CMU dictionary read with British phones.
	"british": (_("British phones (CMU dictionary)"), "en_GB", _LEX_CMU_BRITISH),
	# Translators: an RSynth voice: no dictionary, the 1976 letter-to-sound rules only.
	"rules": (_("Letter-to-sound rules only (NRL 1976)"), "en", _LEX_RULES),
}

#: variant id -> (display name, sample rate)
_VARIANTS = {
	# Translators: an RSynth sample rate.
	"22050": (_("22 kHz"), 22050),
	# Translators: an RSynth sample rate.
	"16000": (_("16 kHz"), 16000),
	# Translators: an RSynth sample rate; 11025 Hz was the original Linux default.
	"11025": (_("11 kHz (original)"), 11025),
	# Translators: an RSynth sample rate; 8000 Hz was the original default elsewhere.
	"8000": (_("8 kHz (original)"), 8000),
}

#: The original's base pitch (saymain.c, -F 133).
_BASE_F0 = 133.0
#: The original's frame length, in ms (saymain.c, -m 10).  Every duration
#: in the engine is counted in frames, so this is what rate changes.
_BASE_FRAME_MS = 10.0
#: Output scale at volume 100.  Peaks at scale 1 stay near 22000 of 32767.
_VOLUME_MAX_SCALE = 1.3

_AUDIO_FN = ctypes.CFUNCTYPE(
	ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16), ctypes.c_int,
)


def _rate_factor(rate):
	"""NVDA rate 0..100 to a speed factor: 0 is half speed, 50 is 1.25 times
	the original, 100 is four times.  Exponential in each half, so equal
	steps sound like equal ratios."""
	if rate <= 50:
		return 0.5 * 2.5 ** (rate / 50.0)
	return 1.25 * 3.2 ** ((rate - 50) / 50.0)


def _f0_for_pitch(pitch):
	"""NVDA pitch 0..100 to Hz: an octave either side of the original 133."""
	return _BASE_F0 * 2.0 ** ((pitch - 50) / 50.0)


def _output_device():
	try:
		return config.conf["audio"]["outputDevice"]
	except KeyError:
		return config.conf["speech"]["outputDevice"]


class _Lib:
	"""rsynth.dll with every signature declared.  Undeclared, ctypes would
	pass the engine handle as a 32-bit int: a crash once the heap is
	above 4 GB."""

	def __init__(self, path):
		lib = self.lib = ctypes.CDLL(path)
		p = ctypes.c_void_p
		d = ctypes.c_double
		for name, res, args in (
			("rs_api_version", ctypes.c_int, []),
			("rs_version_string", ctypes.c_char_p, []),
			("rs_create", p, [ctypes.c_int]),
			("rs_destroy", None, [p]),
			("rs_sample_rate", ctypes.c_int, [p]),
			("rs_set_frame_ms", None, [p, d]),
			("rs_set_speed", None, [p, d]),
			("rs_set_f0", None, [p, d]),
			("rs_set_gain_db", None, [p, d]),
			("rs_set_volume", None, [p, d]),
			("rs_set_smooth", None, [p, d]),
			("rs_set_monotone", None, [p, ctypes.c_int]),
			("rs_set_lexicon", None, [p, ctypes.c_int]),
			("rs_speak", ctypes.c_int, [p, ctypes.c_char_p, ctypes.c_uint, _AUDIO_FN, p]),
		):
			fn = getattr(lib, name)
			fn.restype, fn.argtypes = res, args
		if lib.rs_api_version() != _API_VERSION:
			raise RuntimeError(
				f"rsynth.dll speaks API {lib.rs_api_version()}, driver wants {_API_VERSION}",
			)


class SynthDriver(BaseSynthDriver):
	name = "rsynth"
	# Translators: the name of the RSynth synthesizer in NVDA's list.
	description = _("RSynth")

	supportedSettings = (
		BaseSynthDriver.VoiceSetting(),
		BaseSynthDriver.VariantSetting(),
		BaseSynthDriver.RateSetting(),
		BaseSynthDriver.PitchSetting(),
		BaseSynthDriver.VolumeSetting(),
		BooleanDriverSetting(
			"monotone",
			# Translators: an RSynth setting: hold the pitch flat.
			_("&Monotone"),
			defaultVal=False,
		),
	)
	supportedCommands = {IndexCommand, CharacterModeCommand, BreakCommand, PitchCommand}
	supportedNotifications = {synthIndexReached, synthDoneSpeaking}

	@classmethod
	def check(cls):
		return ctypes.sizeof(ctypes.c_void_p) == 8 and os.path.isfile(_DLL)

	def __init__(self):
		# Driver.__init__ registers the config save action; without it no
		# setting of this driver survives a restart.
		super().__init__()
		self._lib = _Lib(_DLL).lib
		log.info(f"RSynth: {self._lib.rs_version_string().decode('ascii', 'replace')}")
		self._engine = None
		self._player = None
		self._voice = "american"
		self._variant = "22050"
		self._rate = 50
		self._pitch = 50
		self._volume = 100
		self._monotone = False
		self._epoch = 0
		self._queue = queue.Queue()
		# Kept on self: ctypes does not keep a callback alive for C.
		self._audio_cb = _AUDIO_FN(self._on_audio)
		self._feed_epoch = 0
		# Created here, on the main thread, before the speak thread exists;
		# afterwards only the speak thread touches the engine and player.
		self._open()
		self._thread = threading.Thread(target=self._speak_thread, name="rsynth", daemon=True)
		self._thread.start()

	def terminate(self):
		self.cancel()
		self._queue.put(None)
		self._thread.join(timeout=3)
		if self._player:
			self._player.close()
			self._player = None
		if self._engine:
			self._lib.rs_destroy(self._engine)
			self._engine = None
		super().terminate()

	# ---- engine and player -------------------------------------------

	def _open(self):
		"""(Re)create the engine for the current variant's sample rate,
		with every setting applied, and a player to match."""
		rate = _VARIANTS[self._variant][1]
		if self._engine and self._lib.rs_sample_rate(self._engine) != rate:
			self._lib.rs_destroy(self._engine)
			self._engine = None
		if not self._engine:
			self._engine = self._lib.rs_create(rate)
			if not self._engine:
				raise RuntimeError(f"rs_create({rate}) failed")
		self._apply_all()
		if self._player is None or self._player.samplesPerSec != rate:
			old = self._player
			self._player = nvwave.WavePlayer(
				channels=1,
				samplesPerSec=rate,
				bitsPerSample=16,
				outputDevice=_output_device(),
			)
			if old:
				old.close()

	def _apply_all(self):
		lib, e = self._lib, self._engine
		lib.rs_set_lexicon(e, _VOICES[self._voice][2])
		lib.rs_set_frame_ms(e, _BASE_FRAME_MS / _rate_factor(self._rate))
		lib.rs_set_f0(e, _f0_for_pitch(self._pitch))
		lib.rs_set_volume(e, _VOLUME_MAX_SCALE * self._volume / 100.0)
		lib.rs_set_monotone(e, 1 if self._monotone else 0)

	# ---- settings ----------------------------------------------------
	# Setters record the value and queue an "apply" with no epoch; the
	# speak thread applies it between utterances.

	def _changed(self, reopen=False):
		self._queue.put((None, "reopen" if reopen else "apply", None))

	def _getAvailableVoices(self):
		return {vid: VoiceInfo(vid, name, lang) for vid, (name, lang, _lex) in _VOICES.items()}

	def _get_voice(self):
		return self._voice

	def _set_voice(self, value):
		if value in _VOICES:
			self._voice = value
			self._changed()

	def _getAvailableVariants(self):
		return {vid: VoiceInfo(vid, name) for vid, (name, _rate) in _VARIANTS.items()}

	def _get_variant(self):
		return self._variant

	def _set_variant(self, value):
		if value in _VARIANTS and value != self._variant:
			self._variant = value
			self._changed(reopen=True)

	def _get_rate(self):
		return self._rate

	def _set_rate(self, value):
		self._rate = max(0, min(100, int(value)))
		self._changed()

	def _get_pitch(self):
		return self._pitch

	def _set_pitch(self, value):
		self._pitch = max(0, min(100, int(value)))
		self._changed()

	def _get_volume(self):
		return self._volume

	def _set_volume(self, value):
		self._volume = max(0, min(100, int(value)))
		self._changed()

	def _get_monotone(self):
		return self._monotone

	def _set_monotone(self, value):
		self._monotone = bool(value)
		self._changed()

	# ---- speaking ----------------------------------------------------

	def speak(self, speechSequence):
		epoch = self._epoch
		spell = False
		pitch = self._pitch
		text = []

		def flush():
			if text:
				joined = " ".join(text)
				if joined.strip():
					self._queue.put((epoch, "text", (joined, spell, pitch)))
				text.clear()

		for item in speechSequence:
			if isinstance(item, str):
				text.append(item)
			elif isinstance(item, IndexCommand):
				flush()
				self._queue.put((epoch, "index", item.index))
			elif isinstance(item, CharacterModeCommand):
				flush()
				spell = item.state
			elif isinstance(item, BreakCommand):
				flush()
				self._queue.put((epoch, "break", item.time))
			elif isinstance(item, PitchCommand):
				flush()
				pitch = item.newValue
		flush()
		self._queue.put((epoch, "done", None))

	def cancel(self):
		self._epoch += 1
		# Drop queued speech but keep settings changes: a rate change queued
		# just before a cancel must still happen.
		keep = []
		try:
			while True:
				item = self._queue.get_nowait()
				if item is not None and item[0] is None:
					keep.append(item)
				elif item is None:
					keep.append(item)
		except queue.Empty:
			pass
		for item in keep:
			self._queue.put(item)
		if self._player:
			self._player.stop()

	def pause(self, switch):
		if self._player:
			self._player.pause(switch)

	# ---- the speak thread --------------------------------------------

	def _speak_thread(self):
		while True:
			item = self._queue.get()
			if item is None:
				return
			epoch, kind, payload = item
			try:
				if epoch is not None and epoch != self._epoch:
					continue
				if kind == "apply":
					self._apply_all()
				elif kind == "reopen":
					self._open()
				elif kind == "text":
					self._say(epoch, *payload)
				elif kind == "index":
					# Reached when the audio before it has played, not when
					# it was synthesized: an empty chunk carries the callback.
					self._player.feed(
						b"",
						onDone=lambda index=payload: synthIndexReached.notify(synth=self, index=index),
					)
				elif kind == "break":
					self._silence(epoch, payload)
				elif kind == "done":
					self._player.idle()
					if epoch == self._epoch:
						synthDoneSpeaking.notify(synth=self)
			except Exception:
				log.error("RSynth speak thread", exc_info=True)

	def _say(self, epoch, text, spell, pitch):
		self._feed_epoch = epoch
		changed_pitch = pitch != self._pitch
		if changed_pitch:
			self._lib.rs_set_f0(self._engine, _f0_for_pitch(pitch))
		try:
			self._lib.rs_speak(
				self._engine,
				text.encode("utf-8", "replace"),
				_SPEAK_SPELL if spell else 0,
				self._audio_cb,
				None,
			)
		finally:
			if changed_pitch:
				self._lib.rs_set_f0(self._engine, _f0_for_pitch(self._pitch))

	def _on_audio(self, user, samples, count):
		"""Called by rsynth.dll on the speak thread with a block of PCM.
		Returns 1 to stop synthesis once a cancel has happened."""
		try:
			if self._feed_epoch != self._epoch:
				return 1
			data = ctypes.string_at(samples, count * 2)
			self._player.feed(data)
			if self._feed_epoch != self._epoch:
				# cancel() ran while this block was being fed, so its stop()
				# may have come first and this block would sound at the head
				# of the next utterance.  Stop again.
				self._player.stop()
				return 1
			return 0
		except Exception:
			log.error("RSynth audio callback", exc_info=True)
			return 1

	def _silence(self, epoch, ms):
		rate = self._player.samplesPerSec
		remaining = max(0, int(rate * ms / 1000))
		block = rate // 50
		while remaining > 0 and epoch == self._epoch:
			n = min(block, remaining)
			self._player.feed(bytes(2 * n))
			remaining -= n
