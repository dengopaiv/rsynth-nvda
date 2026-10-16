#!/usr/bin/env python3
"""Check rsynth_gui.exe from outside, the way a screen reader sees it.

    python tests/gui_check.py <rsynth_gui.exe> <rsynth_say.exe>

Windows only; needs comtypes (for oleacc's IAccessible).

The GUI runs on a desktop of its own (CreateDesktop), and this script's
thread moves there too. This machine is shared with someone using NVDA: on
their desktop the window would be reachable by their keystrokes and window
switching, and one run on 2026-10-16 failed that way. On a separate
desktop nothing the user does reaches the GUI, NVDA never sees it, and
it never takes the focus from them. Its sound is played at volume 0.

What it checks (docs/07-gui.md has the results):

1. MSAA: every tab stop's role, name, value and state through
   AccessibleObjectFromWindow, which is the layer NVDA reads for standard
   Win32 controls. Every one must have a name; each number field's name
   must be its label, unit included. Each control's group is found the way
   NVDA finds it (IAccessibleHandler.findGroupboxObject) and compared with
   the group it is drawn in.
2. Tab order: real Tab and Shift+Tab keystrokes posted to the focused
   control, the focus read back with GetGUIThreadInfo. Forward through every
   control and round to the start; backwards from the start.
3. Number fields: Up, Page Up and Down step the value; an out-of-range value
   is clamped on leaving the field; text that is not a number is put back.
4. Commands: Alt+letter, Show phonemes (compared with rsynth_say -p), Save
   as WAV through the real file dialog (compared sample for sample with
   rsynth_say), saving and opening a voice, Ctrl+Enter, Esc, Reset,
   Monotone, and closing.

Modifier keys are set by attaching to the GUI thread's input state
(AttachThreadInput + SetKeyboardState), which is what GetKeyState reads
there; nothing is sent to the real keyboard.

Copyright (c) 2026 the rsynth-nvda contributors.
Licensed under the GNU Library General Public License, version 2 or
(at your option) any later version.
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import tempfile
import time
import wave

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# The private desktop, entered before comtypes initialises COM: a thread can
# change desktop only while it owns no windows, and COM may create one.
DESKTOP_NAME = "rsynth_gui_check"
user32.CreateDesktopW.restype = wt.HANDLE
user32.CreateDesktopW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.c_void_p,
								  wt.DWORD, wt.DWORD, ctypes.c_void_p]
user32.SetThreadDesktop.argtypes = [wt.HANDLE]
user32.CloseDesktop.argtypes = [wt.HANDLE]
DESKTOP = user32.CreateDesktopW(DESKTOP_NAME, None, None, 0, 0x10000000, None)  # GENERIC_ALL
if not DESKTOP or not user32.SetThreadDesktop(DESKTOP):
	sys.exit(f"could not create or enter a private desktop (error {ctypes.get_last_error()})")

import comtypes  # noqa: E402
import comtypes.client  # noqa: E402

comtypes.client.GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible  # noqa: E402

oleacc = ctypes.WinDLL("oleacc")


class STARTUPINFOW(ctypes.Structure):
	_fields_ = [
		("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
		("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
		("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
		("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
		("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
		("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
	]


class PROCESS_INFORMATION(ctypes.Structure):
	_fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
				("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


kernel32.CreateProcessW.argtypes = [
	wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
	ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
	ctypes.POINTER(PROCESS_INFORMATION)]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
user32.WaitForInputIdle.argtypes = [wt.HANDLE, wt.DWORD]


class Process:
	"""A process started on the private desktop (subprocess cannot set
	STARTUPINFO.lpDesktop)."""

	def __init__(self, exe):
		si = STARTUPINFOW()
		si.cb = ctypes.sizeof(si)
		si.lpDesktop = DESKTOP_NAME
		pi = PROCESS_INFORMATION()
		cmd = ctypes.create_unicode_buffer(f'"{exe}"')
		if not kernel32.CreateProcessW(exe, cmd, None, None, False, 0, None, None,
									   ctypes.byref(si), ctypes.byref(pi)):
			sys.exit(f"could not start {exe} (error {ctypes.get_last_error()})")
		kernel32.CloseHandle(pi.hThread)
		self.handle, self.pid = pi.hProcess, pi.dwProcessId

	def poll(self):
		code = wt.DWORD()
		kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code))
		return None if code.value == 259 else code.value  # STILL_ACTIVE

	def wait(self, timeout):
		kernel32.WaitForSingleObject(self.handle, int(timeout * 1000))
		return self.poll()

	def kill(self):
		kernel32.TerminateProcess(self.handle, 1)

user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetParent.restype = wt.HWND
user32.GetParent.argtypes = [wt.HWND]
user32.GetWindow.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetDlgItem.restype = wt.HWND
user32.GetDlgItem.argtypes = [wt.HWND, ctypes.c_int]
oleacc.GetRoleTextW.argtypes = [wt.DWORD, wt.LPWSTR, wt.UINT]

WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH = 0x000C, 0x000D, 0x000E
WM_CLOSE, WM_COMMAND = 0x0010, 0x0111
WM_KEYDOWN, WM_KEYUP, WM_SYSCHAR = 0x0100, 0x0101, 0x0106
BM_GETCHECK, BM_CLICK = 0x00F0, 0x00F5
CB_GETCURSEL = 0x0147
VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU, VK_ESCAPE = 0x09, 0x0D, 0x10, 0x11, 0x12, 0x1B
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
VK_PRIOR, VK_NEXT, VK_UP, VK_DOWN = 0x21, 0x22, 0x26, 0x28
GWL_STYLE = -16
WS_TABSTOP, WS_VISIBLE = 0x00010000, 0x10000000
OBJID_CLIENT = -4
GW_HWNDPREV = 3

# Control ids, as in gui/rsynth_gui.cpp.
ID_TEXT, ID_READAS, ID_LEXICON, ID_RATE = 100, 101, 102, 103
ID_SPEAK, ID_STOP, ID_SAVEWAV, ID_PHONEMES, ID_USEPHONES = 104, 105, 106, 107, 108
ID_MONOTONE, ID_RESET, ID_OUTPUT, ID_STATUS = 109, 110, 111, 112
ID_NUM_EDIT = 200
P_FRAME, P_SPEED, P_F0, P_GAIN, P_VOLUME = 0, 1, 2, 3, 4
ID_OPEN_VOICE, ID_SAVE_VOICE = 400, 401

failures = 0
checks = 0


def check(cond, what):
	global failures, checks
	checks += 1
	if cond:
		print(f"  ok    {what}")
	else:
		failures += 1
		print(f"  FAIL  {what}")


class GUITHREADINFO(ctypes.Structure):
	_fields_ = [
		("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND),
		("hwndFocus", wt.HWND), ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
		("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT),
	]


def text_of(hwnd):
	n = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
	buf = ctypes.create_unicode_buffer(n + 2)
	user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.addressof(buf))
	return buf.value


def set_text(hwnd, s):
	buf = ctypes.create_unicode_buffer(s)
	user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.addressof(buf))


def class_of(hwnd):
	buf = ctypes.create_unicode_buffer(64)
	user32.GetClassNameW(hwnd, buf, 64)
	return buf.value


def children(parent):
	out = []
	proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(lambda h, _: out.append(h) or True)
	user32.EnumChildWindows(parent, proc, 0)
	return out


def top_windows(pid):
	out = []

	def cb(h, _):
		p = wt.DWORD()
		user32.GetWindowThreadProcessId(h, ctypes.byref(p))
		if p.value == pid:
			out.append(h)
		return True

	user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
	return out


def wait_for(fn, timeout=10.0, step=0.05):
	end = time.time() + timeout
	while time.time() < end:
		v = fn()
		if v:
			return v
		time.sleep(step)
	return fn()


def role_text(role):
	buf = ctypes.create_unicode_buffer(64)
	oleacc.GetRoleTextW(role, buf, 64)
	return buf.value


def msaa(hwnd):
	ptr = ctypes.POINTER(IAccessible)()
	hr = oleacc.AccessibleObjectFromWindow(
		hwnd, ctypes.c_long(OBJID_CLIENT), ctypes.byref(IAccessible._iid_), ctypes.byref(ptr))
	if hr != 0 or not ptr:
		return None
	acc = ptr

	def get(name):
		try:
			return getattr(acc, name)(0)
		except Exception:
			try:
				return getattr(acc, name)[0]
			except Exception:
				return None

	role = get("accRole")
	return {
		"role": role_text(role) if isinstance(role, int) else str(role),
		"name": get("accName"),
		"value": get("accValue"),
		"state": get("accState"),
	}


class Gui:
	def __init__(self, exe):
		self.proc = Process(exe)
		self.main = wait_for(lambda: next(
			(h for h in top_windows(self.proc.pid) if class_of(h) == "RSynthGui"), None))
		if not self.main:
			sys.exit("rsynth_gui did not open a window")
		self.tid = user32.GetWindowThreadProcessId(self.main, None)
		wait_for(lambda: self.item(ID_STATUS) and "Ready" in self.status())
		# A message queue for this thread, so that it can attach input.
		msg = wt.MSG()
		user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
		self.my_tid = kernel32.GetCurrentThreadId()

	def item(self, cid):
		return user32.GetDlgItem(self.main, cid)

	def status(self):
		return text_of(self.item(ID_STATUS))

	def focus(self):
		gti = GUITHREADINFO()
		gti.cbSize = ctypes.sizeof(gti)
		user32.GetGUIThreadInfo(self.tid, ctypes.byref(gti))
		return gti.hwndFocus

	def settle(self):
		"""Wait until the GUI has handled everything posted to it.

		A SendMessage round trip is not enough on its own: a thread handles
		sent messages before it takes posted ones from its queue, so it can
		answer while posted keys are still waiting. WaitForInputIdle returns
		once the thread is blocked in GetMessage with nothing queued."""
		time.sleep(0.02)
		user32.WaitForInputIdle(self.proc.handle, 2000)
		user32.SendMessageW(self.main, WM_GETTEXTLENGTH, 0, 0)
		time.sleep(0.03)

	def _modifiers(self, held):
		state = (ctypes.c_ubyte * 256)()
		user32.GetKeyboardState(state)
		for m in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LSHIFT, VK_RSHIFT,
				  VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU):
			state[m] = 0
		for m in held:
			state[m] = 0x80
		user32.SetKeyboardState(state)

	def key(self, vk, mods=()):
		"""Post a key to the focused control, with exactly `mods` held in the
		GUI thread's key state.

		The state is set for every key, not only when a modifier is wanted:
		the GUI reads GetKeyState, and a Ctrl the user happens to press while
		this runs (NVDA users press it to silence speech) once turned every
		posted Tab into Ctrl+Tab, which the GUI rightly does not treat as Tab
		(docs/07)."""
		target = self.focus() or self.main
		user32.AttachThreadInput(self.my_tid, self.tid, True)
		self._modifiers(mods)
		user32.PostMessageW(target, WM_KEYDOWN, vk, 1)
		user32.PostMessageW(target, WM_KEYUP, vk, 0xC0000001)
		self.settle()
		self._modifiers(())
		user32.AttachThreadInput(self.my_tid, self.tid, False)

	def command(self, cid):
		user32.PostMessageW(self.main, WM_COMMAND, cid, 0)
		self.settle()

	def dialog(self):
		return wait_for(lambda: next(
			(h for h in top_windows(self.proc.pid)
			 if class_of(h) == "#32770" and user32.IsWindowVisible(h)), None))

	def file_dialog(self, path):
		"""Type a path into the open file dialog and press its OK button."""
		dlg = self.dialog()
		if not dlg:
			return False
		time.sleep(0.5)
		edits = [h for h in children(dlg) if class_of(h) == "Edit"
				 and user32.IsWindowVisible(h)
				 and class_of(user32.GetParent(h)) in ("ComboBox", "ComboBoxEx32")]
		if not edits:
			edits = [h for h in children(dlg) if class_of(h) == "Edit" and user32.IsWindowVisible(h)]
		if not edits:
			return False
		set_text(edits[0], path)
		ok = user32.GetDlgItem(dlg, 1)
		user32.PostMessageW(ok, BM_CLICK, 0, 0)
		return wait_for(lambda: not user32.IsWindow(dlg), timeout=10)


def tab_stops(main):
	return [h for h in children(main)
			if user32.GetParent(h) == main
			and user32.GetWindowLongW(h, GWL_STYLE) & WS_TABSTOP]


def read_wav(path):
	with wave.open(path, "rb") as w:
		return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())


def main():
	if len(sys.argv) != 3:
		sys.exit(__doc__)
	exe, say = (os.path.abspath(p) for p in sys.argv[1:3])
	tmp = tempfile.mkdtemp(prefix="rsynth_gui_check_")
	g = Gui(exe)
	try:
		run(g, say, tmp)
	finally:
		if g.proc.poll() is None:
			g.proc.kill()
			g.proc.wait(5)
		kernel32.CloseHandle(g.proc.handle)
		user32.CloseDesktop(DESKTOP)
	print(f"\n{checks} checks, {failures} failed")
	return 1 if failures else 0


def run(g, say, tmp):
	stops = tab_stops(g.main)

	print("1. What MSAA reports for each tab stop, in creation order")
	for h in stops:
		info = msaa(h)
		label = class_of(user32.GetWindow(h, GW_HWNDPREV))
		print(f"     {class_of(h):10} role={info['role']!r:22} name={info['name']!r} value={info['value']!r}")
		check(bool(info["name"]), f"has a name: {info['name']!r} ({class_of(h)})")
	# The group NVDA would announce, found the way NVDA finds it
	# (IAccessibleHandler.findGroupboxObject in NVDA 2026.3's source): back
	# through the previous windows to the first visible Button with a
	# BS_GROUPBOX bit, MSAA role grouping, whose rectangle holds the control.
	def nvda_group(h):
		r = wt.RECT()
		user32.GetWindowRect(h, ctypes.byref(r))
		p = user32.GetWindow(h, GW_HWNDPREV)
		while p:
			if (class_of(p) == "Button" and user32.GetWindowLongW(p, GWL_STYLE) & 7
					and user32.IsWindowVisible(p)):
				info = msaa(p)
				g_r = wt.RECT()
				user32.GetWindowRect(p, ctypes.byref(g_r))
				if (info["role"] == role_text(20)  # ROLE_SYSTEM_GROUPING
						and r.left >= g_r.left and r.right <= g_r.right
						and r.top >= g_r.top and r.bottom <= g_r.bottom):
					return info["name"]
			p = user32.GetWindow(p, GW_HWNDPREV)
		return None

	prosody, speaker = "Prosody and output", "Speaker: fixed formants and bandwidths"
	for h in stops:
		cid = user32.GetDlgCtrlID(h)
		if ID_NUM_EDIT <= cid < ID_NUM_EDIT + 6 or cid in (ID_MONOTONE, ID_RESET):
			want = prosody
		elif ID_NUM_EDIT + 6 <= cid < ID_NUM_EDIT + 16:
			want = speaker
		else:
			want = None
		got = nvda_group(h)
		check(got == want, f"NVDA's group for {msaa(h)['name']!r}: {got!r}")

	for i, want in ((P_FRAME, "Frame length (ms):"), (P_F0, "Base pitch (Hz):"),
					(P_VOLUME, "Volume (%):")):
		info = msaa(g.item(ID_NUM_EDIT + i))
		check(info["name"] == want and info["value"] not in (None, ""),
			  f"number field named {want!r} with value {info['value']!r}")

	print("2. Tab order")
	check(g.focus() == g.item(ID_TEXT), "starts in the text box")
	seen = [g.focus()]
	for _ in range(len(stops)):
		g.key(VK_TAB)
		seen.append(g.focus())
	check(seen[:-1] == stops, f"Tab visits all {len(stops)} tab stops in creation order")
	if seen[:-1] != stops:
		print("        visited:", [class_of(h) + ":" + str(user32.GetDlgCtrlID(h)) for h in seen])
	check(seen[-1] == stops[0], "Tab wraps round to the text box")
	g.key(VK_TAB, (VK_SHIFT,))
	check(g.focus() == stops[-1], "Shift+Tab from the text box goes to the last control")
	g.key(VK_TAB, (VK_SHIFT,))
	check(g.focus() == stops[-2], "Shift+Tab again goes one further back")

	print("3. Number fields")
	pitch = g.item(ID_NUM_EDIT + P_F0)
	while g.focus() != pitch:
		g.key(VK_TAB)
	check(text_of(pitch) == "133", f"base pitch starts at 133 ({text_of(pitch)!r})")
	g.key(VK_UP)
	check(text_of(pitch) == "134", f"Up steps to 134 ({text_of(pitch)!r})")
	g.key(VK_PRIOR)
	check(text_of(pitch) == "144", f"Page Up steps ten to 144 ({text_of(pitch)!r})")
	g.key(VK_DOWN)
	check(text_of(pitch) == "143", f"Down steps to 143 ({text_of(pitch)!r})")
	check(msaa(pitch)["value"] == "143", "MSAA reports the new value")
	set_text(pitch, "999")
	g.key(VK_TAB)
	check(text_of(pitch) == "400" and "outside the range" in g.status(),
		  f"999 is clamped to 400 on leaving: {text_of(pitch)!r}, {g.status()!r}")
	g.key(VK_TAB, (VK_SHIFT,))
	set_text(pitch, "abc")
	g.key(VK_TAB)
	check(text_of(pitch) == "400" and "not a number" in g.status(),
		  f"'abc' is put back: {text_of(pitch)!r}, {g.status()!r}")
	g.command(ID_RESET)
	check(text_of(pitch) == "133", "Reset puts it back to 133")

	print("4. Commands")
	user32.PostMessageW(g.focus(), WM_SYSCHAR, ord("l"), 1 << 29)
	g.settle()
	check(g.focus() == g.item(ID_LEXICON), "Alt+L goes to the lexicon")
	user32.PostMessageW(g.focus(), WM_SYSCHAR, ord("t"), 1 << 29)
	g.settle()
	check(g.focus() == g.item(ID_TEXT), "Alt+T goes to the text box")

	text = "The quick brown fox, 1,234 times, on the 21st of May."
	set_text(g.item(ID_TEXT), text)
	g.command(ID_PHONEMES)
	out = text_of(g.item(ID_OUTPUT))
	want = subprocess.run([say, "-p", text], capture_output=True, text=True).stdout.strip()
	norm = subprocess.run([say, "-n", text], capture_output=True, text=True).stdout.strip()
	check(want and want in out, "Show phonemes gives what rsynth_say -p gives")
	check(norm and norm in out, "and the normalized text rsynth_say -n gives")
	check(g.focus() == g.item(ID_OUTPUT), "and moves the focus to the output box")

	wav = os.path.join(tmp, "gui.wav")
	ref = os.path.join(tmp, "ref.wav")
	user32.PostMessageW(g.main, WM_COMMAND, ID_SAVEWAV, 0)
	check(g.file_dialog(wav), "the Save as WAV dialog took a file name")
	wait_for(lambda: "Saved" in g.status(), timeout=20)
	check("Saved gui.wav" in g.status(), f"status: {g.status()!r}")
	subprocess.run([say, "-o", ref, text], check=True, capture_output=True)
	a, b = read_wav(wav), read_wav(ref)
	check(a[:3] == (22050, 1, 2), f"the WAV is 22050 Hz mono 16-bit: {a[:3]}")
	check(a[3] == b[3] and len(a[3]) > 0,
		  f"its {len(a[3]) // 2} samples equal rsynth_say's {len(b[3]) // 2}")

	voice = os.path.join(tmp, "test.rsv")
	set_text(g.item(ID_NUM_EDIT + P_F0), "180")
	user32.SendMessageW(g.item(ID_MONOTONE), BM_CLICK, 0, 0)
	check(user32.SendMessageW(g.item(ID_MONOTONE), BM_GETCHECK, 0, 0) == 1, "Monotone checks")
	user32.PostMessageW(g.main, WM_COMMAND, ID_SAVE_VOICE, 0)
	check(g.file_dialog(voice), "the Save voice dialog took a file name")
	check(wait_for(lambda: os.path.exists(voice)), "the voice file was written")
	g.command(ID_RESET)
	check(text_of(g.item(ID_NUM_EDIT + P_F0)) == "133"
		  and user32.SendMessageW(g.item(ID_MONOTONE), BM_GETCHECK, 0, 0) == 0,
		  "Reset clears pitch and Monotone")
	user32.PostMessageW(g.main, WM_COMMAND, ID_OPEN_VOICE, 0)
	check(g.file_dialog(voice), "the Open voice dialog took a file name")
	wait_for(lambda: "Voice loaded" in g.status())
	check(text_of(g.item(ID_NUM_EDIT + P_F0)) == "180"
		  and user32.SendMessageW(g.item(ID_MONOTONE), BM_GETCHECK, 0, 0) == 1,
		  f"opening it brings back pitch 180 and Monotone: {g.status()!r}")
	g.command(ID_RESET)

	# Speaking, silently.
	set_text(g.item(ID_NUM_EDIT + P_VOLUME), "0")
	set_text(g.item(ID_TEXT), "Test.")
	g.key(VK_RETURN, (VK_CONTROL,))
	check(wait_for(lambda: "Speaking" in g.status() or "Finished" in g.status(), timeout=5),
		  f"Ctrl+Enter speaks: {g.status()!r}")
	check(wait_for(lambda: "Finished" in g.status(), timeout=10),
		  f"and playback finishes: {g.status()!r}")
	set_text(g.item(ID_TEXT), "This is a long passage that goes on. " * 40)
	g.key(VK_RETURN, (VK_CONTROL,))
	wait_for(lambda: "Speaking" in g.status(), timeout=5)
	time.sleep(0.3)
	g.key(VK_ESCAPE)
	check(g.status() == "Stopped.", f"Esc stops: {g.status()!r}")
	time.sleep(0.5)
	check(g.status() == "Stopped.", f"and nothing finishes afterwards: {g.status()!r}")
	g.key(VK_ESCAPE)
	check(g.status() == "Nothing to stop.", f"Esc when idle: {g.status()!r}")

	user32.PostMessageW(g.main, WM_CLOSE, 0, 0)
	code = g.proc.wait(10)
	check(code == 0, f"closes cleanly (exit code {code})")


if __name__ == "__main__":
	sys.exit(main())
