/*
    rsynth_gui.cpp - the RSynth desktop GUI. C++17 over plain Win32.

    It replaces rsynth_gui.py, the wxPython GUI of the Python port, which
    now lives only on the branch python-port. This program drives the
    original C engine through its public API (include/rsynth_api.h),
    linked in statically, so it is one 64-bit exe with nothing beside it.
    docs/07-gui.md describes it and how it was checked.

    Accessibility is the point, not a detail (CLAUDE.md section 3):
      - standard controls only: edits, combo boxes, buttons, a check box,
        edit + up-down pairs for numbers, group boxes, a menu bar and a
        status bar; no tab control (see Tab order below);
      - every control that has no text of its own has a static label
        immediately before it in creation order, which is what gives it
        its accessible name, unit included ("Base pitch (Hz):");
      - full keyboard operation: Tab and Shift+Tab over an explicit order,
        Alt+letter to every main control, Ctrl+Enter speaks from anywhere,
        Esc stops, Page Up / Page Down move a number ten steps;
      - the focused control's explanation goes to the status bar (NVDA+End
        reads it), and so does every result; failures get a message box.

    Tab order. The keyboard is handled here, not by IsDialogMessage: the
    order is the creation order of the focusable controls, kept in
    g_tabOrder. wintalker's GUI, the model for this one, lost Tab inside a
    tab control under IsDialogMessage (its docs/01, 2026-10-16); with
    seventeen parameters there is no need for pages, so there are none.

    Numbers. The edit holds the text and is the authority; the up-down
    beside it only reports clicks and arrow keys (UDN_DELTAPOS), which step
    the value by the parameter's step and write it back. A typed value is
    used as soon as it parses and lies in range; on leaving the field it is
    clamped, or put back if it does not parse, and the status bar says so.

    Synthesis runs on a worker thread from a fresh engine per utterance,
    built from a copy of the settings, so the engine is never shared
    between threads. The samples are collected in memory (the engine runs
    some 300 times faster than real time) and played through waveOut in
    blocks; Esc cancels the synthesis and resets the device.

    Copyright (c) 2026 the rsynth-nvda contributors.
    Licensed under the GNU Library General Public License, version 2 or
    (at your option) any later version.
*/
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <commctrl.h>
#include <commdlg.h>
#include <mmsystem.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <cwctype>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "rsynth_api.h"

namespace {

// ---------------------------------------------------------------------------
// Identifiers

enum : int {
    ID_TEXT = 100, ID_READAS, ID_LEXICON, ID_RATE,
    ID_SPEAK, ID_STOP, ID_SAVEWAV, ID_PHONEMES, ID_USEPHONES,
    ID_MONOTONE, ID_RESET, ID_OUTPUT, ID_STATUS,
    ID_NUM_EDIT = 200,      // + parameter index
    ID_NUM_SPIN = 300,      // + parameter index
    ID_OPEN_VOICE = 400, ID_SAVE_VOICE, ID_EXIT, ID_KEYS, ID_ABOUT,
};

constexpr UINT WM_APP_DONE = WM_APP + 1;

// ---------------------------------------------------------------------------
// Parameters

enum Param {
    P_FRAME, P_SPEED, P_F0, P_GAIN, P_VOLUME, P_SMOOTH,
    P_F4, P_B4, P_F5, P_B5, P_F6, P_B4P, P_B5P, P_B6P, P_FNP, P_BN,
    P_COUNT
};
constexpr int FIRST_SPEAKER = P_F4;

struct NumSpec {
    const char *key;        // name in a voice file
    const wchar_t *label;   // accessible name, unit included
    double lo, hi, step, def;
    int decimals;
    int speaker;            // RS_SPK_*, or -1
    const wchar_t *help;
};

// The speaker rows' range and default are filled from the engine itself
// at start-up (rs_speaker_range, rs_get_speaker), so they cannot drift
// from what the library clamps to. The others are the original `say`
// defaults, as rsynth_api.h documents them.
NumSpec g_spec[P_COUNT] = {
    { "frame_ms", L"Frame length (ms):", 1, 40, 0.5, 10, 1, -1,
      L"Length of one synthesis frame. Every duration is counted in frames, "
      L"so this is the speaking rate: 5 ms speaks twice as fast as 10, with "
      L"nothing dropped. Original option -m." },
    { "speed", L"Duration multiplier:", 0.1, 15, 0.05, 1, 2, -1,
      L"Multiplies every element's duration; larger is slower. It rounds to "
      L"whole frames, so values well below 1 drop short sounds, as the "
      L"original did. Original option -S." },
    { "f0", L"Base pitch (Hz):", 40, 400, 1, 133, 0, -1,
      L"The typical voicing frequency the intonation is built around. "
      L"Original option -F." },
    { "gain_db", L"Gain (dB):", 4, 80, 1, 57, 0, -1,
      L"Overall gain into the output filter; 60 dB is unity. Too much "
      L"clips, and the status bar reports it. Original option -G." },
    { "volume_percent", L"Volume (%):", 0, 200, 5, 100, 0, -1,
      L"Scales the samples after synthesis, before clipping. 100 leaves "
      L"them as the engine made them." },
    { "smooth", L"Smoothing:", 0.01, 1, 0.05, 0.5, 2, -1,
      L"Fraction of each frame's new parameter values taken at once; 1 is "
      L"no smoothing, smaller blurs the transitions. Original option -K." },
    { "f4_hz", L"F4 frequency (Hz):", 0, 0, 10, 0, 0, RS_SPK_F4,
      L"Fourth formant, fixed for the speaker, used by the cascade and the "
      L"parallel branch." },
    { "b4_hz", L"F4 bandwidth, cascade (Hz):", 0, 0, 10, 0, 0, RS_SPK_B4,
      L"Bandwidth of the fourth formant in the cascade (voiced) branch." },
    { "f5_hz", L"F5 frequency (Hz):", 0, 0, 10, 0, 0, RS_SPK_F5,
      L"Fifth formant. In the cascade branch only above 8000 Hz sampling; "
      L"always in the parallel branch." },
    { "b5_hz", L"F5 bandwidth, cascade (Hz):", 0, 0, 10, 0, 0, RS_SPK_B5,
      L"Bandwidth of the fifth formant in the cascade branch." },
    { "f6_hz", L"F6 frequency (Hz):", 0, 0, 10, 0, 0, RS_SPK_F6,
      L"Sixth formant, parallel (frication) branch only." },
    { "b4p_hz", L"F4 bandwidth, parallel (Hz):", 0, 0, 10, 0, 0, RS_SPK_B4P,
      L"Bandwidth of the fourth formant in the parallel (frication) branch." },
    { "b5p_hz", L"F5 bandwidth, parallel (Hz):", 0, 0, 10, 0, 0, RS_SPK_B5P,
      L"Bandwidth of the fifth formant in the parallel branch." },
    { "b6p_hz", L"F6 bandwidth, parallel (Hz):", 0, 0, 10, 0, 0, RS_SPK_B6P,
      L"Bandwidth of the sixth formant in the parallel branch." },
    { "fnp_hz", L"Nasal pole frequency (Hz):", 0, 0, 4, 0, 0, RS_SPK_FNP,
      L"The fixed nasal pole. The original sets it to the nasal zero of a "
      L"non-nasal element, so that outside nasals the two cancel." },
    { "bn_hz", L"Nasal bandwidth (Hz):", 0, 0, 10, 0, 0, RS_SPK_BN,
      L"Bandwidth of the nasal pole and of the nasal zero." },
};

const int kRates[] = { 8000, 11025, 16000, 22050, 32000, 44100, 48000 };
constexpr int kDefaultRateIndex = 3;     // 22050, as the add-on

const wchar_t *const kReadAs[] = {
    L"Text", L"Spelled out, character by character", L"Phonemes (SAMPA)"
};
enum { READ_TEXT, READ_SPELL, READ_PHONES };

const wchar_t *const kLexicon[] = {
    L"CMU dictionary, American", L"CMU dictionary, British",
    L"Letter-to-sound rules only"
};
const char *const kLexiconKey[] = { "american", "british", "rules" };

struct Settings {
    double num[P_COUNT];
    bool monotone;
    int lexicon;        // RS_LEX_*
    int rate;           // Hz
};

// ---------------------------------------------------------------------------
// Window state

HINSTANCE g_inst;
HWND g_main, g_status;
HWND g_textLabel, g_text, g_readAsLabel, g_readAs, g_lexLabel, g_lexicon;
HWND g_rateLabel, g_rate;
HWND g_speak, g_stop, g_saveWav, g_phonemes, g_usePhones;
HWND g_groupProsody, g_groupSpeaker, g_monotone, g_reset;
HWND g_outLabel, g_output;
HWND g_label[P_COUNT], g_edit[P_COUNT], g_spin[P_COUNT];
HFONT g_font;
UINT g_dpi = 96;
HACCEL g_accel;
HWND g_lastFocus;
std::vector<HWND> g_tabOrder;

Settings g_set;
bool g_updating;        // set while the program itself writes a field

// ---------------------------------------------------------------------------
// Small helpers

int S(int dip) { return MulDiv(dip, (int) g_dpi, 96); }

std::wstring WindowText(HWND h)
{
    int n = GetWindowTextLengthW(h);
    std::wstring s((size_t) n + 1, L'\0');
    n = GetWindowTextW(h, s.data(), n + 1);
    s.resize((size_t) (n > 0 ? n : 0));
    return s;
}

std::string ToUtf8(const std::wstring &w)
{
    if (w.empty())
        return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int) w.size(),
                                nullptr, 0, nullptr, nullptr);
    std::string s((size_t) n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int) w.size(), s.data(), n,
                        nullptr, nullptr);
    return s;
}

std::wstring FromUtf8(const std::string &s)
{
    if (s.empty())
        return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int) s.size(),
                                nullptr, 0);
    std::wstring w((size_t) n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int) s.size(), w.data(), n);
    return w;
}

void Status(const std::wstring &s)
{
    SendMessageW(g_status, SB_SETTEXTW, SB_SIMPLEID, (LPARAM) s.c_str());
}

void ErrorBox(const std::wstring &s)
{
    MessageBoxW(g_main, s.c_str(), L"RSynth", MB_OK | MB_ICONERROR);
}

std::wstring FormatNum(double v, int decimals)
{
    wchar_t buf[64];
    swprintf(buf, 64, L"%.*f", decimals, v);
    return buf;
}

double RoundTo(double v, int decimals)
{
    double k = std::pow(10.0, decimals);
    return std::round(v * k) / k;
}

double Clamp(double v, double lo, double hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

// Accepts "12.5" and "12,5"; the whole field must be the number.
bool ParseNum(const std::wstring &text, double *out)
{
    std::wstring t = text;
    for (auto &c : t)
        if (c == L',')
            c = L'.';
    const wchar_t *p = t.c_str();
    wchar_t *end = nullptr;
    double v = wcstod(p, &end);
    if (end == p)
        return false;
    while (*end && iswspace(*end))
        end++;
    if (*end || !std::isfinite(v))
        return false;
    *out = v;
    return true;
}

double Seconds(size_t samples, int rate)
{
    return rate > 0 ? (double) samples / rate : 0.0;
}

// ---------------------------------------------------------------------------
// The engine

rs_engine *MakeEngine(const Settings &s)
{
    rs_engine *e = rs_create(s.rate);
    if (!e)
        return nullptr;
    rs_set_frame_ms(e, s.num[P_FRAME]);
    rs_set_speed(e, s.num[P_SPEED]);
    rs_set_f0(e, s.num[P_F0]);
    rs_set_gain_db(e, s.num[P_GAIN]);
    rs_set_volume(e, s.num[P_VOLUME] / 100.0);
    rs_set_smooth(e, s.num[P_SMOOTH]);
    rs_set_monotone(e, s.monotone ? 1 : 0);
    rs_set_lexicon(e, s.lexicon);
    for (int i = FIRST_SPEAKER; i < P_COUNT; i++)
        rs_set_speaker(e, g_spec[i].speaker, s.num[i]);
    return e;
}

void FillSpeakerSpecs()
{
    rs_engine *e = rs_create(22050);
    for (int i = FIRST_SPEAKER; i < P_COUNT; i++) {
        rs_speaker_range(g_spec[i].speaker, &g_spec[i].lo, &g_spec[i].hi);
        g_spec[i].def = e ? rs_get_speaker(e, g_spec[i].speaker) : g_spec[i].lo;
    }
    rs_destroy(e);
}

Settings Defaults()
{
    Settings s{};
    for (int i = 0; i < P_COUNT; i++)
        s.num[i] = g_spec[i].def;
    s.monotone = false;
    s.lexicon = RS_LEX_CMU_AMERICAN;
    s.rate = kRates[kDefaultRateIndex];
    return s;
}

// Text to phonemes, or to the front end's normalized text, as rs_speak
// would see it with the current settings.
std::string FrontEnd(const std::string &utf8, unsigned flags, bool phones)
{
    rs_engine *e = MakeEngine(g_set);
    if (!e)
        return {};
    auto fn = phones ? rs_text_to_phones : rs_normalize;
    std::string out;
    int n = fn(e, utf8.c_str(), flags, nullptr, 0);
    if (n > 0) {
        out.assign((size_t) n + 1, '\0');
        fn(e, utf8.c_str(), flags, out.data(), n + 1);
        out.resize((size_t) n);
    }
    rs_destroy(e);
    return out;
}

// ---------------------------------------------------------------------------
// WAV files

bool WriteWav(const std::wstring &path, const std::vector<int16_t> &pcm,
              int rate, std::wstring *err)
{
    FILE *f = _wfopen(path.c_str(), L"wb");
    if (!f) {
        *err = L"Could not create the file.";
        return false;
    }
    auto u32 = [&](uint32_t v) {
        unsigned char b[4] = { (unsigned char) v, (unsigned char) (v >> 8),
                               (unsigned char) (v >> 16), (unsigned char) (v >> 24) };
        fwrite(b, 1, 4, f);
    };
    auto u16 = [&](uint16_t v) {
        unsigned char b[2] = { (unsigned char) v, (unsigned char) (v >> 8) };
        fwrite(b, 1, 2, f);
    };
    uint32_t data = (uint32_t) (pcm.size() * 2);
    fwrite("RIFF", 1, 4, f);
    u32(36 + data);
    fwrite("WAVEfmt ", 1, 8, f);
    u32(16);
    u16(1);                     // PCM
    u16(1);                     // mono
    u32((uint32_t) rate);
    u32((uint32_t) rate * 2);
    u16(2);
    u16(16);
    fwrite("data", 1, 4, f);
    u32(data);
    for (int16_t s : pcm)
        u16((uint16_t) s);
    bool ok = !ferror(f);
    if (fclose(f) != 0)
        ok = false;
    if (!ok)
        *err = L"Writing the file failed (is the disk full?).";
    return ok;
}

// ---------------------------------------------------------------------------
// Synthesis on a worker thread

struct Result {
    unsigned id = 0;
    int rc = 0;                 // rs_speak's: 0 done, 1 cancelled, <0 error
    int rate = 0;
    bool toFile = false;
    std::wstring path;
    bool fileOk = false;
    std::wstring fileErr;
    std::vector<int16_t> pcm;
    size_t fullScale = 0;       // samples at the clipping limit
};

struct Collect {
    Result *r;
    std::atomic<bool> *cancel;
};

int OnAudio(void *user, const int16_t *s, int n)
{
    auto *c = (Collect *) user;
    c->r->pcm.insert(c->r->pcm.end(), s, s + n);
    for (int i = 0; i < n; i++)
        if (s[i] >= 32767 || s[i] <= -32767)
            c->r->fullScale++;
    return c->cancel->load() ? 1 : 0;
}

std::thread g_worker;
std::atomic<bool> g_cancel{ false };
unsigned g_jobId;               // results with another id are stale
bool g_synthesizing;

// Playback: the samples in blocks, so that no single waveOut buffer is
// enormous; finished when every block is marked done.
HWAVEOUT g_wo;
std::vector<int16_t> g_playPcm;
std::vector<WAVEHDR> g_hdrs;
int g_playRate;
size_t g_playFullScale;

void StopPlayback()
{
    if (!g_wo)
        return;
    HWAVEOUT w = g_wo;
    g_wo = nullptr;
    waveOutReset(w);
    for (auto &h : g_hdrs)
        waveOutUnprepareHeader(w, &h, sizeof h);
    waveOutClose(w);
    g_hdrs.clear();
}

// Cancels whatever is under way. Results already posted carry an old id
// and are dropped when they arrive.
bool StopAll()
{
    bool any = g_synthesizing || g_wo;
    g_cancel = true;
    if (g_worker.joinable())
        g_worker.join();
    g_synthesizing = false;
    g_jobId++;
    StopPlayback();
    return any;
}

std::wstring FullScaleNote(size_t n)
{
    if (!n)
        return {};
    return L" " + std::to_wstring(n) +
           L" samples reached full scale and clipped: lower the gain or the volume.";
}

bool Play(std::vector<int16_t> &&pcm, int rate, size_t fullScale)
{
    StopPlayback();
    g_playPcm = std::move(pcm);
    g_playRate = rate;
    g_playFullScale = fullScale;

    WAVEFORMATEX fmt{};
    fmt.wFormatTag = WAVE_FORMAT_PCM;
    fmt.nChannels = 1;
    fmt.nSamplesPerSec = (DWORD) rate;
    fmt.wBitsPerSample = 16;
    fmt.nBlockAlign = 2;
    fmt.nAvgBytesPerSec = (DWORD) rate * 2;
    HWAVEOUT w = nullptr;
    MMRESULT mr = waveOutOpen(&w, WAVE_MAPPER, &fmt, (DWORD_PTR) g_main, 0,
                              CALLBACK_WINDOW);
    if (mr != MMSYSERR_NOERROR) {
        wchar_t msg[256];
        waveOutGetErrorTextW(mr, msg, 256);
        ErrorBox(std::wstring(L"Could not open the sound device: ") + msg);
        return false;
    }
    g_wo = w;
    const size_t block = (size_t) rate;     // one second
    g_hdrs.assign((g_playPcm.size() + block - 1) / block, WAVEHDR{});
    for (size_t i = 0; i < g_hdrs.size(); i++) {
        size_t at = i * block;
        size_t n = std::min(block, g_playPcm.size() - at);
        g_hdrs[i].lpData = (LPSTR) (g_playPcm.data() + at);
        g_hdrs[i].dwBufferLength = (DWORD) (n * 2);
        waveOutPrepareHeader(w, &g_hdrs[i], sizeof(WAVEHDR));
    }
    for (auto &h : g_hdrs)
        waveOutWrite(w, &h, sizeof h);
    return true;
}

void OnPlaybackBlockDone(HWAVEOUT w)
{
    if (!g_wo || w != g_wo)
        return;
    for (auto &h : g_hdrs)
        if (!(h.dwFlags & WHDR_DONE))
            return;
    StopPlayback();
    wchar_t buf[96];
    swprintf(buf, 96, L"Finished: %.1f seconds at %d Hz.",
             Seconds(g_playPcm.size(), g_playRate), g_playRate);
    Status(buf + FullScaleNote(g_playFullScale));
}

void CommitFocusedNumber();

// The text to speak: the selection in the text box if there is one,
// otherwise all of it.
std::wstring TextToSpeak(bool *selection)
{
    std::wstring all = WindowText(g_text);
    DWORD a = 0, b = 0;
    SendMessageW(g_text, EM_GETSEL, (WPARAM) &a, (LPARAM) &b);
    *selection = b > a && b <= all.size();
    return *selection ? all.substr(a, b - a) : all;
}

void StartJob(bool toFile, const std::wstring &path)
{
    CommitFocusedNumber();
    bool selection = false;
    std::wstring w = TextToSpeak(&selection);
    bool blank = true;
    for (wchar_t c : w)
        if (!iswspace(c))
            blank = false;
    if (blank) {
        Status(L"Nothing to speak: the text box is empty.");
        return;
    }
    StopAll();
    g_cancel = false;
    g_synthesizing = true;
    unsigned id = g_jobId;
    Settings s = g_set;
    int mode = (int) SendMessageW(g_readAs, CB_GETCURSEL, 0, 0);
    std::string text = ToUtf8(w);
    HWND target = g_main;
    g_worker = std::thread([=] {
        auto r = std::make_unique<Result>();
        r->id = id;
        r->rate = s.rate;
        r->toFile = toFile;
        r->path = path;
        rs_engine *e = MakeEngine(s);
        if (!e) {
            r->rc = -2;
        } else {
            Collect c{ r.get(), &g_cancel };
            if (mode == READ_PHONES)
                r->rc = rs_speak_phones(e, text.c_str(), OnAudio, &c);
            else
                r->rc = rs_speak(e, text.c_str(),
                                 mode == READ_SPELL ? RS_SPEAK_SPELL : 0u,
                                 OnAudio, &c);
            rs_destroy(e);
        }
        if (toFile && r->rc == 0)
            r->fileOk = WriteWav(r->path, r->pcm, r->rate, &r->fileErr);
        if (PostMessageW(target, WM_APP_DONE, 0, (LPARAM) r.get()))
            r.release();
    });
    Status(selection ? L"Synthesizing the selection..." : L"Synthesizing...");
}

void OnJobDone(Result *raw)
{
    std::unique_ptr<Result> r(raw);
    if (r->id != g_jobId)
        return;                 // stopped or superseded
    if (g_worker.joinable())
        g_worker.join();
    g_synthesizing = false;
    if (r->rc < 0) {
        ErrorBox(L"The synthesizer failed (out of memory, or a sample rate it refused).");
        Status(L"Synthesis failed.");
        return;
    }
    if (r->rc == 1) {
        Status(L"Stopped.");
        return;
    }
    wchar_t buf[160];
    if (r->toFile) {
        if (!r->fileOk) {
            ErrorBox(L"Could not save " + r->path + L":\n" + r->fileErr);
            Status(L"Not saved.");
            return;
        }
        const wchar_t *name = wcsrchr(r->path.c_str(), L'\\');
        swprintf(buf, 160, L"Saved %ls: %.1f seconds at %d Hz.",
                 name ? name + 1 : r->path.c_str(),
                 Seconds(r->pcm.size(), r->rate), r->rate);
        Status(buf + FullScaleNote(r->fullScale));
        return;
    }
    if (r->pcm.empty()) {
        Status(L"The synthesizer produced no sound for this text.");
        return;
    }
    swprintf(buf, 160, L"Speaking %.1f seconds.", Seconds(r->pcm.size(), r->rate));
    if (Play(std::move(r->pcm), r->rate, r->fullScale))
        Status(buf + FullScaleNote(r->fullScale));
    else
        Status(L"Could not play the sound.");
}

// ---------------------------------------------------------------------------
// Settings <-> controls

void ShowNum(int i)
{
    g_updating = true;
    SetWindowTextW(g_edit[i], FormatNum(g_set.num[i], g_spec[i].decimals).c_str());
    g_updating = false;
}

void ShowSettings()
{
    for (int i = 0; i < P_COUNT; i++)
        ShowNum(i);
    SendMessageW(g_monotone, BM_SETCHECK,
                 g_set.monotone ? BST_CHECKED : BST_UNCHECKED, 0);
    SendMessageW(g_lexicon, CB_SETCURSEL, (WPARAM) g_set.lexicon, 0);
    int r = kDefaultRateIndex;
    for (int k = 0; k < (int) (sizeof kRates / sizeof kRates[0]); k++)
        if (kRates[k] == g_set.rate)
            r = k;
    SendMessageW(g_rate, CB_SETCURSEL, (WPARAM) r, 0);
}

std::wstring RangeText(int i)
{
    const NumSpec &p = g_spec[i];
    return L"Range " + FormatNum(p.lo, p.decimals) + L" to " +
           FormatNum(p.hi, p.decimals) + L", default " +
           FormatNum(p.def, p.decimals) + L".";
}

std::wstring PlainLabel(int i)
{
    std::wstring s = g_spec[i].label;
    if (!s.empty() && s.back() == L':')
        s.pop_back();
    return s;
}

void StepNum(int i, int steps)
{
    double v = g_set.num[i];
    ParseNum(WindowText(g_edit[i]), &v);
    const NumSpec &p = g_spec[i];
    v = Clamp(RoundTo(v + steps * p.step, p.decimals), p.lo, p.hi);
    g_set.num[i] = v;
    ShowNum(i);
}

// A note from a field that was just left, kept for the help of the control
// that takes the focus next: that help would otherwise overwrite it at
// once (EN_KILLFOCUS comes before the next EN_SETFOCUS).
std::wstring g_pendingNote;

// Puts the field's text into the settings. `leaving` is set when the focus
// is moving away, so that the note goes out with the next control's help.
// A clamped or refused value also beeps: the field is no longer focused,
// so a screen reader does not read its new value, and the beep is the
// cue to look at the status bar.
void CommitNum(int i, bool leaving)
{
    const NumSpec &p = g_spec[i];
    std::wstring t = WindowText(g_edit[i]);
    std::wstring note;
    double v;
    if (!ParseNum(t, &v)) {
        note = PlainLabel(i) + L": \"" + t + L"\" is not a number; kept " +
               FormatNum(g_set.num[i], p.decimals) + L".";
    } else if (v < p.lo || v > p.hi) {
        g_set.num[i] = Clamp(v, p.lo, p.hi);
        note = PlainLabel(i) + L": " + t + L" is outside the range; set to " +
               FormatNum(g_set.num[i], p.decimals) + L". " + RangeText(i);
    } else {
        g_set.num[i] = v;
    }
    ShowNum(i);
    if (note.empty())
        return;
    MessageBeep(MB_ICONWARNING);
    if (leaving)
        g_pendingNote = note;
    Status(note);
}

int NumIndex(HWND h)
{
    for (int i = 0; i < P_COUNT; i++)
        if (g_edit[i] == h)
            return i;
    return -1;
}

void CommitFocusedNumber()
{
    int i = NumIndex(GetFocus());
    if (i >= 0)
        CommitNum(i, false);
}

// ---------------------------------------------------------------------------
// Voice files: plain text, one "key value" per line, '#' starts a comment.

std::wstring FileDialog(bool save, const wchar_t *filter, const wchar_t *ext,
                        const wchar_t *title, const wchar_t *initial)
{
    wchar_t file[MAX_PATH] = L"";
    if (initial)
        wcsncpy(file, initial, MAX_PATH - 1);
    OPENFILENAMEW ofn{};
    ofn.lStructSize = sizeof ofn;
    ofn.hwndOwner = g_main;
    ofn.lpstrFilter = filter;
    ofn.lpstrFile = file;
    ofn.nMaxFile = MAX_PATH;
    ofn.lpstrDefExt = ext;
    ofn.lpstrTitle = title;
    ofn.Flags = OFN_EXPLORER | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR |
                (save ? OFN_OVERWRITEPROMPT : OFN_FILEMUSTEXIST);
    BOOL ok = save ? GetSaveFileNameW(&ofn) : GetOpenFileNameW(&ofn);
    return ok ? std::wstring(file) : std::wstring();
}

const wchar_t kVoiceFilter[] = L"RSynth voices (*.rsv)\0*.rsv\0All files\0*.*\0";

void SaveVoice()
{
    CommitFocusedNumber();
    std::wstring path = FileDialog(true, kVoiceFilter, L"rsv", L"Save voice", L"voice.rsv");
    if (path.empty())
        return;
    FILE *f = _wfopen(path.c_str(), L"w");
    if (!f) {
        ErrorBox(L"Could not create " + path + L".");
        return;
    }
    fprintf(f, "# RSynth voice, written by rsynth_gui\n");
    fprintf(f, "sample_rate %d\n", g_set.rate);
    fprintf(f, "lexicon %s\n", kLexiconKey[g_set.lexicon]);
    fprintf(f, "monotone %d\n", g_set.monotone ? 1 : 0);
    for (int i = 0; i < P_COUNT; i++)
        fprintf(f, "%s %.*f\n", g_spec[i].key, g_spec[i].decimals, g_set.num[i]);
    bool ok = !ferror(f);
    if (fclose(f) != 0)
        ok = false;
    if (!ok)
        ErrorBox(L"Writing " + path + L" failed.");
    else
        Status(L"Voice saved to " + path + L".");
}

void OpenVoice()
{
    std::wstring path = FileDialog(false, kVoiceFilter, L"rsv", L"Open voice", nullptr);
    if (path.empty())
        return;
    FILE *f = _wfopen(path.c_str(), L"r");
    if (!f) {
        ErrorBox(L"Could not open " + path + L".");
        return;
    }
    Settings s = Defaults();    // what the file does not mention is default
    char line[256];
    int unknown = 0, adjusted = 0;
    while (fgets(line, sizeof line, f)) {
        char key[64], value[64];
        if (line[0] == '#' || sscanf(line, "%63s %63s", key, value) != 2)
            continue;
        bool known = false;
        if (!strcmp(key, "sample_rate")) {
            int r = atoi(value);
            for (int k : kRates)
                if (k == r) {
                    s.rate = r;
                    known = true;
                }
            if (!known) {
                adjusted++;
                known = true;
            }
        } else if (!strcmp(key, "lexicon")) {
            for (int k = 0; k < 3; k++)
                if (!strcmp(value, kLexiconKey[k])) {
                    s.lexicon = k;
                    known = true;
                }
        } else if (!strcmp(key, "monotone")) {
            s.monotone = atoi(value) != 0;
            known = true;
        } else {
            for (int i = 0; i < P_COUNT; i++)
                if (!strcmp(key, g_spec[i].key)) {
                    double v = 0;
                    std::wstring wv = FromUtf8(value);
                    if (ParseNum(wv, &v)) {
                        double c = Clamp(v, g_spec[i].lo, g_spec[i].hi);
                        adjusted += c != v;
                        s.num[i] = c;
                        known = true;
                    }
                }
        }
        unknown += !known;
    }
    fclose(f);
    g_set = s;
    ShowSettings();
    std::wstring msg = L"Voice loaded from " + path + L".";
    if (unknown)
        msg += L" " + std::to_wstring(unknown) + L" line(s) not understood and skipped.";
    if (adjusted)
        msg += L" " + std::to_wstring(adjusted) + L" value(s) out of range and adjusted.";
    Status(msg);
}

// ---------------------------------------------------------------------------
// Commands

void ShowPhonemes()
{
    CommitFocusedNumber();
    bool selection = false;
    std::string text = ToUtf8(TextToSpeak(&selection));
    int mode = (int) SendMessageW(g_readAs, CB_GETCURSEL, 0, 0);
    std::wstring out;
    if (mode == READ_PHONES) {
        out = L"The text is read as phonemes already; it goes to the "
              L"synthesizer as it is.";
    } else {
        unsigned flags = mode == READ_SPELL ? RS_SPEAK_SPELL : 0u;
        out = L"Normalized text:\r\n" + FromUtf8(FrontEnd(text, flags, false)) +
              L"\r\n\r\nPhonemes (SAMPA):\r\n" + FromUtf8(FrontEnd(text, flags, true));
    }
    SetWindowTextW(g_output, out.c_str());
    SetFocus(g_output);
    SendMessageW(g_output, EM_SETSEL, 0, 0);
    Status(L"The front end's output is in the output box.");
}

void UsePhonemes()
{
    CommitFocusedNumber();
    int mode = (int) SendMessageW(g_readAs, CB_GETCURSEL, 0, 0);
    if (mode == READ_PHONES) {
        Status(L"The text is phonemes already.");
        return;
    }
    std::string text = ToUtf8(WindowText(g_text));
    std::string ph = FrontEnd(text, mode == READ_SPELL ? RS_SPEAK_SPELL : 0u, true);
    SetWindowTextW(g_text, FromUtf8(ph).c_str());
    SendMessageW(g_readAs, CB_SETCURSEL, READ_PHONES, 0);
    SetFocus(g_text);
    Status(L"The text box now holds the phonemes, and Read as is set to "
           L"Phonemes. Edit them and speak.");
}

void ResetVoice()
{
    g_set = Defaults();
    ShowSettings();
    Status(L"All voice settings are back to their defaults.");
}

void ShowKeys()
{
    MessageBoxW(g_main,
        L"Ctrl+Enter\tSpeak (the selection, if there is one)\n"
        L"Esc\tStop\n"
        L"Ctrl+S\tSave the speech as a WAV file\n"
        L"Ctrl+P\tShow the normalized text and phonemes\n"
        L"Ctrl+U\tReplace the text with its phonemes\n"
        L"Ctrl+R\tReset the voice to the defaults\n"
        L"Ctrl+O\tOpen a voice file\n"
        L"Ctrl+Shift+S\tSave the voice to a file\n"
        L"F1\tThis list\n\n"
        L"In a number field: Up and Down step the value, Page Up and Page "
        L"Down step it ten times, or type a value.\n"
        L"Alt plus the underlined letter moves to a control. NVDA+End reads "
        L"the status bar, which explains the focused control and reports "
        L"every result.",
        L"RSynth keys", MB_OK | MB_ICONINFORMATION);
}

void ShowAbout()
{
    std::wstring v = FromUtf8(rs_version_string());
    std::wstring msg =
        v + L"\n\n"
        L"RSynth: a formant synthesizer by Nick Ing-Simmons, 1994-2004, "
        L"after the Klatt synthesizer and the Holmes, Mattingly and Shearme "
        L"rule system. GNU Library General Public License, version 2 or "
        L"later.\n\n"
        L"Pronunciation: the CMU Pronouncing Dictionary, Carnegie Mellon "
        L"University, BSD-style licence.\n\n"
        L"This GUI and the library interface: the rsynth-nvda contributors, "
        L"2026, under the same licence as RSynth. See NOTICE.md.";
    MessageBoxW(g_main, msg.c_str(), L"About RSynth", MB_OK | MB_ICONINFORMATION);
}

void Command(int id)
{
    switch (id) {
    case ID_SPEAK:
        StartJob(false, L"");
        break;
    case ID_STOP:
        Status(StopAll() ? L"Stopped." : L"Nothing to stop.");
        break;
    case ID_SAVEWAV: {
        CommitFocusedNumber();
        std::wstring path = FileDialog(true, L"WAV files (*.wav)\0*.wav\0All files\0*.*\0",
                                       L"wav", L"Save speech as WAV", L"rsynth.wav");
        if (!path.empty())
            StartJob(true, path);
        break;
    }
    case ID_PHONEMES:
        ShowPhonemes();
        break;
    case ID_USEPHONES:
        UsePhonemes();
        break;
    case ID_RESET:
        ResetVoice();
        break;
    case ID_OPEN_VOICE:
        OpenVoice();
        break;
    case ID_SAVE_VOICE:
        SaveVoice();
        break;
    case ID_EXIT:
        PostMessageW(g_main, WM_CLOSE, 0, 0);
        break;
    case ID_KEYS:
        ShowKeys();
        break;
    case ID_ABOUT:
        ShowAbout();
        break;
    }
}

// ---------------------------------------------------------------------------
// Creating and laying out the controls

// Creation order is z-order, and it matters twice: a static label just
// before a control names it, and a group box just before its controls is
// how NVDA finds the group (it looks back through previous siblings for a
// grouping whose rectangle holds the control). No WS_CLIPSIBLINGS, as in a
// dialog template: a control with it clips out every sibling above it, and
// the group box is above its own controls, so they were not drawn at all.
HWND Make(DWORD exStyle, const wchar_t *cls, const wchar_t *text, DWORD style,
          int id, bool tabStop)
{
    HWND h = CreateWindowExW(exStyle, cls, text,
                             WS_CHILD | WS_VISIBLE | style |
                                 (tabStop ? WS_TABSTOP : 0),
                             0, 0, 10, 10, g_main, (HMENU) (INT_PTR) id,
                             g_inst, nullptr);
    if (tabStop)
        g_tabOrder.push_back(h);
    return h;
}

HWND Label(const wchar_t *text)
{
    return Make(0, L"STATIC", text, SS_LEFT, -1, false);
}

HWND Button(const wchar_t *text, int id)
{
    return Make(0, L"BUTTON", text, BS_PUSHBUTTON | BS_NOTIFY, id, true);
}

HWND Combo(int id, const wchar_t *const *items, int n, int sel)
{
    HWND h = Make(0, WC_COMBOBOXW, L"", CBS_DROPDOWNLIST | WS_VSCROLL, id, true);
    for (int i = 0; i < n; i++)
        SendMessageW(h, CB_ADDSTRING, 0, (LPARAM) items[i]);
    SendMessageW(h, CB_SETCURSEL, (WPARAM) sel, 0);
    return h;
}

LRESULT CALLBACK NumEditProc(HWND h, UINT msg, WPARAM wp, LPARAM lp,
                             UINT_PTR idx, DWORD_PTR)
{
    if (msg == WM_KEYDOWN && (wp == VK_PRIOR || wp == VK_NEXT)) {
        StepNum((int) idx, wp == VK_PRIOR ? 10 : -10);
        return 0;
    }
    if (msg == WM_CHAR && (wp == L'\r' || wp == 27))
        return 0;   // Enter and Esc are handled in the message loop; no beep
    return DefSubclassProc(h, msg, wp, lp);
}

void CreateNumber(int i)
{
    g_label[i] = Label(g_spec[i].label);
    g_edit[i] = Make(WS_EX_CLIENTEDGE, L"EDIT", L"", ES_LEFT | ES_AUTOHSCROLL,
                     ID_NUM_EDIT + i, true);
    g_spin[i] = Make(0, UPDOWN_CLASSW, L"", UDS_ARROWKEYS | UDS_HOTTRACK,
                     ID_NUM_SPIN + i, false);
    SendMessageW(g_spin[i], UDM_SETBUDDY, (WPARAM) g_edit[i], 0);
    // The position is never used; it sits mid-range so that both arrows
    // always report a click.
    SendMessageW(g_spin[i], UDM_SETRANGE32, 0, 100);
    SendMessageW(g_spin[i], UDM_SETPOS32, 0, 50);
    SetWindowSubclass(g_edit[i], NumEditProc, (UINT_PTR) i, 0);
}

void CreateControls()
{
    g_textLabel = Label(L"&Text to speak:");
    g_text = Make(WS_EX_CLIENTEDGE, L"EDIT",
                  L"Hello. This is RSynth, Nick Ing-Simmons' formant "
                  L"synthesizer, speaking 1,234 words on the 21st of May.",
                  ES_MULTILINE | ES_WANTRETURN | ES_AUTOVSCROLL | WS_VSCROLL,
                  ID_TEXT, true);
    SendMessageW(g_text, EM_SETLIMITTEXT, 0, 0);

    g_readAsLabel = Label(L"Read &as:");
    g_readAs = Combo(ID_READAS, kReadAs, 3, READ_TEXT);
    g_lexLabel = Label(L"&Lexicon:");
    g_lexicon = Combo(ID_LEXICON, kLexicon, 3, RS_LEX_CMU_AMERICAN);
    g_rateLabel = Label(L"Sample &rate (Hz):");
    {
        const wchar_t *items[7];
        static wchar_t names[7][16];
        for (int k = 0; k < 7; k++) {
            swprintf(names[k], 16, L"%d", kRates[k]);
            items[k] = names[k];
        }
        g_rate = Combo(ID_RATE, items, 7, kDefaultRateIndex);
    }

    g_speak = Button(L"&Speak", ID_SPEAK);
    g_stop = Button(L"St&op", ID_STOP);
    g_saveWav = Button(L"Save as &WAV...", ID_SAVEWAV);
    g_phonemes = Button(L"Show &phonemes", ID_PHONEMES);
    g_usePhones = Button(L"&Use phonemes as text", ID_USEPHONES);

    g_groupProsody = Make(0, L"BUTTON", L"Prosody and output", BS_GROUPBOX, -1, false);
    for (int i = 0; i < FIRST_SPEAKER; i++)
        CreateNumber(i);
    g_monotone = Make(0, L"BUTTON", L"&Monotone (hold the pitch flat)",
                      BS_AUTOCHECKBOX | BS_NOTIFY, ID_MONOTONE, true);
    g_reset = Button(L"Reset voice to &defaults", ID_RESET);

    g_groupSpeaker = Make(0, L"BUTTON", L"Speaker: fixed formants and bandwidths",
                          BS_GROUPBOX, -1, false);
    for (int i = FIRST_SPEAKER; i < P_COUNT; i++)
        CreateNumber(i);

    g_outLabel = Label(L"&Normalized text and phonemes:");
    g_output = Make(WS_EX_CLIENTEDGE, L"EDIT", L"",
                    ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | WS_VSCROLL,
                    ID_OUTPUT, true);

    g_status = CreateWindowExW(0, STATUSCLASSNAMEW, L"",
                               WS_CHILD | WS_VISIBLE | SBARS_SIZEGRIP, 0, 0, 0, 0,
                               g_main, (HMENU) (INT_PTR) ID_STATUS, g_inst, nullptr);
    SendMessageW(g_status, SB_SIMPLE, TRUE, 0);
}

void ApplyFont()
{
    if (g_font)
        DeleteObject(g_font);
    NONCLIENTMETRICSW ncm{};
    ncm.cbSize = sizeof ncm;
    SystemParametersInfoForDpi(SPI_GETNONCLIENTMETRICS, sizeof ncm, &ncm, 0, g_dpi);
    g_font = CreateFontIndirectW(&ncm.lfMessageFont);
    for (HWND h = GetWindow(g_main, GW_CHILD); h; h = GetWindow(h, GW_HWNDNEXT))
        SendMessageW(h, WM_SETFONT, (WPARAM) g_font, TRUE);
}

void Place(HWND h, int x, int y, int w, int hgt)
{
    MoveWindow(h, x, y, w, hgt, TRUE);
}

// Layout in 96-dpi units, scaled by S(). The two text boxes share the
// height that the fixed rows leave.
void Layout()
{
    if (!g_status)
        return;                 // WM_SIZE from CreateWindow, before the controls
    RECT rc;
    GetClientRect(g_main, &rc);
    RECT sr;
    GetWindowRect(g_status, &sr);
    const int statusH = sr.bottom - sr.top;
    const int W = rc.right, H = rc.bottom - statusH;
    const int M = S(10), labelH = S(18), editH = S(23), rowH = S(27);
    const int btnH = S(27), gap = S(6);

    const int numRows = P_COUNT - FIRST_SPEAKER;    // the taller group
    const int groupH = S(24) + numRows * rowH + S(8);
    const int fixed = M + labelH + gap + rowH + gap + btnH + gap + groupH +
                      gap + labelH + M;
    int flexible = H - fixed;
    if (flexible < S(120))
        flexible = S(120);
    const int textH = flexible * 55 / 100;
    const int outH = flexible - textH;

    int y = M;
    Place(g_textLabel, M, y, W - 2 * M, labelH);
    y += labelH;
    Place(g_text, M, y, W - 2 * M, textH);
    y += textH + gap;

    // Read as, Lexicon, Sample rate on one row.
    int x = M;
    auto pair = [&](HWND lab, HWND box, int labW, int boxW) {
        Place(lab, x, y + S(4), S(labW), labelH);
        x += S(labW) + S(4);
        Place(box, x, y, S(boxW), S(200));
        x += S(boxW) + S(14);
    };
    pair(g_readAsLabel, g_readAs, 54, 220);
    pair(g_lexLabel, g_lexicon, 50, 190);
    pair(g_rateLabel, g_rate, 100, 70);
    y += rowH + gap;

    x = M;
    auto button = [&](HWND b, int w) {
        Place(b, x, y, S(w), btnH);
        x += S(w) + gap;
    };
    button(g_speak, 80);
    button(g_stop, 80);
    button(g_saveWav, 120);
    button(g_phonemes, 120);
    button(g_usePhones, 160);
    y += btnH + gap;

    const int gw = (W - 2 * M - S(10)) / 2;
    auto group = [&](HWND g, int gx, int first, int last) {
        Place(g, gx, y, gw, groupH);
        int ry = y + S(22);
        const int editW = S(70), spinW = S(18);
        for (int i = first; i < last; i++) {
            Place(g_label[i], gx + S(10), ry + S(4), gw - S(20) - editW - spinW - S(6), labelH);
            Place(g_edit[i], gx + gw - S(10) - editW - spinW, ry, editW, editH);
            Place(g_spin[i], gx + gw - S(10) - spinW, ry, spinW, editH);
            ry += rowH;
        }
        return ry;
    };
    int ry = group(g_groupProsody, M, 0, FIRST_SPEAKER);
    Place(g_monotone, M + S(10), ry, gw - S(20), editH);
    ry += rowH;
    Place(g_reset, M + S(10), ry, S(180), btnH);
    group(g_groupSpeaker, M + gw + S(10), FIRST_SPEAKER, P_COUNT);
    y += groupH + gap;

    Place(g_outLabel, M, y, W - 2 * M, labelH);
    y += labelH;
    Place(g_output, M, y, W - 2 * M, outH);
}

// ---------------------------------------------------------------------------
// Help in the status bar for whatever has the focus

void HelpFor(HWND h)
{
    if (!g_pendingNote.empty()) {
        std::wstring note = g_pendingNote;
        g_pendingNote.clear();
        Status(note);
        return;
    }
    int i = NumIndex(h);
    if (i >= 0) {
        Status(g_spec[i].help + std::wstring(L" ") + RangeText(i));
        return;
    }
    if (h == g_text)
        Status(L"Type or paste text. Ctrl+Enter speaks it, or the selection; Esc stops. F1 lists the keys.");
    else if (h == g_readAs)
        Status(L"How the text is read: as text, spelled out, or as SAMPA phonemes like h@'loU.");
    else if (h == g_lexicon)
        Status(L"Where pronunciations come from: the CMU dictionary with American or British phones, or the 1976 letter-to-sound rules alone.");
    else if (h == g_rate)
        Status(L"Sample rate of the sound. The original drivers ran at 8000 or 11025 Hz; at 8000 the cascade F5 is left out.");
    else if (h == g_monotone)
        Status(L"Hold the pitch at the base pitch instead of following the intonation contour. Original option -M.");
    else if (h == g_output)
        Status(L"What the front end made of the text: the normalized ASCII the engine reads, and the phonemes it speaks.");
    else if (h == g_speak)
        Status(L"Speak the text, or the selection in it. Ctrl+Enter.");
    else if (h == g_stop)
        Status(L"Stop speaking. Esc.");
    else if (h == g_saveWav)
        Status(L"Synthesize the text into a WAV file instead of playing it. Ctrl+S.");
    else if (h == g_phonemes)
        Status(L"Show the normalized text and the phonemes in the output box. Ctrl+P.");
    else if (h == g_usePhones)
        Status(L"Replace the text with its phonemes, to edit the pronunciation by hand. Ctrl+U.");
    else if (h == g_reset)
        Status(L"Put every voice setting back to its default. Ctrl+R.");
}

// ---------------------------------------------------------------------------
// Keyboard

void MoveFocus(bool backwards)
{
    std::vector<HWND> order;
    for (HWND h : g_tabOrder)
        if (IsWindowEnabled(h) && IsWindowVisible(h))
            order.push_back(h);
    if (order.empty())
        return;
    HWND focus = GetFocus();
    int at = -1;
    for (int i = 0; i < (int) order.size(); i++)
        if (order[i] == focus || IsChild(order[i], focus))
            at = i;
    int n = (int) order.size();
    HWND next = at < 0 ? order[backwards ? n - 1 : 0]
                       : order[(at + (backwards ? n - 1 : 1)) % n];
    SetFocus(next);
    // As the dialog manager does: tabbing into a one-line edit selects it.
    if (NumIndex(next) >= 0)
        SendMessageW(next, EM_SETSEL, 0, -1);
}

bool AnyComboDropped()
{
    for (HWND c : { g_readAs, g_lexicon, g_rate })
        if (SendMessageW(c, CB_GETDROPPEDSTATE, 0, 0))
            return true;
    return false;
}

bool IsButton(HWND h)
{
    return h == g_speak || h == g_stop || h == g_saveWav || h == g_phonemes ||
           h == g_usePhones || h == g_reset;
}

// Alt+letter: the letter underlined in a label moves to its control; in a
// button or the check box it presses it, as in a dialog box. The menus
// use F, C and H, which nothing here does.
bool Mnemonic(wchar_t ch)
{
    struct { wchar_t key; HWND *target; bool press; } map[] = {
        { L'T', &g_text, false },    { L'A', &g_readAs, false },
        { L'L', &g_lexicon, false }, { L'R', &g_rate, false },
        { L'S', &g_speak, true },    { L'O', &g_stop, true },
        { L'W', &g_saveWav, true },  { L'P', &g_phonemes, true },
        { L'U', &g_usePhones, true }, { L'M', &g_monotone, true },
        { L'D', &g_reset, true },    { L'N', &g_output, false },
    };
    ch = (wchar_t) towupper(ch);
    for (auto &m : map)
        if (m.key == ch) {
            SetFocus(*m.target);
            if (m.press)
                SendMessageW(*m.target, BM_CLICK, 0, 0);
            return true;
        }
    return false;
}

// Keys the window handles itself. Returns true when the message is used up.
bool HandleKey(const MSG &m)
{
    if (m.hwnd != g_main && !IsChild(g_main, m.hwnd))
        return false;
    const bool ctrl = GetKeyState(VK_CONTROL) & 0x8000;
    const bool alt = GetKeyState(VK_MENU) & 0x8000;
    const bool shift = GetKeyState(VK_SHIFT) & 0x8000;
    if (m.message == WM_SYSCHAR)
        return Mnemonic((wchar_t) m.wParam);
    if (m.message != WM_KEYDOWN)
        return false;
    if (AnyComboDropped())
        return false;           // the open list wants Tab, Enter and Esc
    switch (m.wParam) {
    case VK_TAB:
        if (ctrl || alt)
            return false;
        MoveFocus(shift);
        return true;
    case VK_ESCAPE:
        Command(ID_STOP);
        return true;
    case VK_RETURN: {
        if (ctrl || alt)
            return false;
        HWND f = GetFocus();
        if (IsButton(f)) {
            SendMessageW(f, BM_CLICK, 0, 0);
            return true;
        }
        int i = NumIndex(f);
        if (i >= 0) {
            CommitNum(i, false);
            SendMessageW(f, EM_SETSEL, 0, -1);
            return true;
        }
        return false;           // the text box takes a new line
    }
    }
    return false;
}

// ---------------------------------------------------------------------------
// The window

HMENU MakeMenu()
{
    HMENU bar = CreateMenu();
    HMENU file = CreatePopupMenu();
    AppendMenuW(file, MF_STRING, ID_OPEN_VOICE, L"&Open voice...\tCtrl+O");
    AppendMenuW(file, MF_STRING, ID_SAVE_VOICE, L"&Save voice...\tCtrl+Shift+S");
    AppendMenuW(file, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(file, MF_STRING, ID_SAVEWAV, L"Save speech as &WAV...\tCtrl+S");
    AppendMenuW(file, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(file, MF_STRING, ID_EXIT, L"E&xit\tAlt+F4");
    HMENU speech = CreatePopupMenu();
    AppendMenuW(speech, MF_STRING, ID_SPEAK, L"&Speak\tCtrl+Enter");
    AppendMenuW(speech, MF_STRING, ID_STOP, L"S&top\tEsc");
    AppendMenuW(speech, MF_STRING, ID_PHONEMES, L"Show &phonemes\tCtrl+P");
    AppendMenuW(speech, MF_STRING, ID_USEPHONES, L"&Use phonemes as text\tCtrl+U");
    AppendMenuW(speech, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(speech, MF_STRING, ID_RESET, L"&Reset voice to defaults\tCtrl+R");
    HMENU help = CreatePopupMenu();
    AppendMenuW(help, MF_STRING, ID_KEYS, L"&Keys\tF1");
    AppendMenuW(help, MF_STRING, ID_ABOUT, L"&About RSynth");
    AppendMenuW(bar, MF_POPUP, (UINT_PTR) file, L"&File");
    AppendMenuW(bar, MF_POPUP, (UINT_PTR) speech, L"Spee&ch");
    AppendMenuW(bar, MF_POPUP, (UINT_PTR) help, L"&Help");
    return bar;
}

HACCEL MakeAccelerators()
{
    ACCEL a[] = {
        { FCONTROL | FVIRTKEY, VK_RETURN, ID_SPEAK },
        { FCONTROL | FVIRTKEY, 'S', ID_SAVEWAV },
        { FCONTROL | FSHIFT | FVIRTKEY, 'S', ID_SAVE_VOICE },
        { FCONTROL | FVIRTKEY, 'O', ID_OPEN_VOICE },
        { FCONTROL | FVIRTKEY, 'P', ID_PHONEMES },
        { FCONTROL | FVIRTKEY, 'U', ID_USEPHONES },
        { FCONTROL | FVIRTKEY, 'R', ID_RESET },
        { FVIRTKEY, VK_F1, ID_KEYS },
    };
    return CreateAcceleratorTableW(a, (int) (sizeof a / sizeof a[0]));
}

LRESULT CALLBACK MainProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_COMMAND: {
        const int id = LOWORD(wp), code = HIWORD(wp);
        HWND ctl = (HWND) lp;
        if (!ctl) {                         // menu (0) or accelerator (1)
            Command(id);
            return 0;
        }
        if (id >= ID_NUM_EDIT && id < ID_NUM_EDIT + P_COUNT) {
            int i = id - ID_NUM_EDIT;
            if (code == EN_SETFOCUS) {
                HelpFor(ctl);
            } else if (code == EN_KILLFOCUS) {
                CommitNum(i, true);
            } else if (code == EN_CHANGE && !g_updating) {
                double v;
                if (ParseNum(WindowText(ctl), &v) && v >= g_spec[i].lo && v <= g_spec[i].hi)
                    g_set.num[i] = v;
            }
            return 0;
        }
        if (code == EN_SETFOCUS || code == CBN_SETFOCUS || code == BN_SETFOCUS) {
            HelpFor(ctl);
            return 0;
        }
        if (code == CBN_SELCHANGE) {
            int sel = (int) SendMessageW(ctl, CB_GETCURSEL, 0, 0);
            if (ctl == g_lexicon && sel >= 0)
                g_set.lexicon = sel;
            else if (ctl == g_rate && sel >= 0)
                g_set.rate = kRates[sel];
            return 0;
        }
        if (code == BN_CLICKED) {
            if (ctl == g_monotone)
                g_set.monotone = SendMessageW(ctl, BM_GETCHECK, 0, 0) == BST_CHECKED;
            else
                Command(id);
            return 0;
        }
        return 0;
    }
    case WM_NOTIFY: {
        auto *hdr = (NMHDR *) lp;
        if (hdr->code == UDN_DELTAPOS && hdr->idFrom >= ID_NUM_SPIN &&
            hdr->idFrom < (UINT_PTR) (ID_NUM_SPIN + P_COUNT)) {
            int i = (int) hdr->idFrom - ID_NUM_SPIN;
            StepNum(i, ((NMUPDOWN *) lp)->iDelta > 0 ? 1 : -1);
            if (GetFocus() != g_edit[i])
                SetFocus(g_edit[i]);
            return TRUE;                    // keep the up-down's own position
        }
        return 0;
    }
    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLORBTN:
        // What a dialog does: labels, group boxes, the check box and the
        // read-only output box on the face colour. DefWindowProc would give
        // group boxes and buttons the window colour instead. System colours,
        // so High Contrast themes apply.
        SetBkColor((HDC) wp, GetSysColor(COLOR_BTNFACE));
        SetTextColor((HDC) wp, GetSysColor(COLOR_BTNTEXT));
        return (LRESULT) GetSysColorBrush(COLOR_BTNFACE);
    case WM_APP_DONE:
        OnJobDone((Result *) lp);
        return 0;
    case MM_WOM_DONE:
        OnPlaybackBlockDone((HWAVEOUT) wp);
        return 0;
    case WM_SIZE:
        if (wp == SIZE_MINIMIZED)
            return 0;                       // a 0 x 0 client area; keep the layout
        SendMessageW(g_status, WM_SIZE, 0, 0);
        Layout();
        return 0;
    case WM_GETMINMAXINFO: {
        auto *mm = (MINMAXINFO *) lp;
        mm->ptMinTrackSize.x = S(800);
        mm->ptMinTrackSize.y = S(640);
        return 0;
    }
    case WM_DPICHANGED: {
        g_dpi = HIWORD(wp);
        ApplyFont();
        auto *r = (RECT *) lp;
        SetWindowPos(hwnd, nullptr, r->left, r->top, r->right - r->left,
                     r->bottom - r->top, SWP_NOZORDER | SWP_NOACTIVATE);
        Layout();
        return 0;
    }
    case WM_ACTIVATE:
        // Give the focus back to the control that had it, as a dialog does,
        // so that Alt+Tab and closing a file dialog land where the user was.
        if (LOWORD(wp) == WA_INACTIVE) {
            HWND f = GetFocus();
            if (f && IsChild(hwnd, f))
                g_lastFocus = f;
        } else {
            SetFocus(g_lastFocus ? g_lastFocus : g_text);
        }
        return 0;
    case WM_SETFOCUS:
        SetFocus(g_lastFocus ? g_lastFocus : g_text);
        return 0;
    case WM_CLOSE:
        StopAll();
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

} // namespace

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int show)
{
    g_inst = inst;
    INITCOMMONCONTROLSEX icc{ sizeof icc, ICC_STANDARD_CLASSES | ICC_UPDOWN_CLASS |
                                              ICC_BAR_CLASSES };
    InitCommonControlsEx(&icc);

    FillSpeakerSpecs();
    g_set = Defaults();

    WNDCLASSEXW wc{};
    wc.cbSize = sizeof wc;
    wc.lpfnWndProc = MainProc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    wc.hbrBackground = (HBRUSH) (COLOR_BTNFACE + 1);
    wc.lpszClassName = L"RSynthGui";
    RegisterClassExW(&wc);

    // No WS_CLIPCHILDREN: it would keep the window from painting inside the
    // group boxes, which draw only their frame, as a dialog would not.
    g_main = CreateWindowExW(0, wc.lpszClassName, L"RSynth",
                             WS_OVERLAPPEDWINDOW,
                             CW_USEDEFAULT, CW_USEDEFAULT, 800, 600, nullptr,
                             MakeMenu(), inst, nullptr);
    if (!g_main)
        return 1;
    g_dpi = GetDpiForWindow(g_main);
    CreateControls();
    ApplyFont();
    ShowSettings();
    // Show focus rectangles and underlined access keys from the start,
    // not only after Alt is pressed.
    SendMessageW(g_main, WM_CHANGEUISTATE, MAKEWPARAM(UIS_CLEAR, UISF_HIDEFOCUS | UISF_HIDEACCEL), 0);

    // 860 x 780 at 96 dpi, kept inside the work area.
    RECT work;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    int w = std::min(S(860), (int) (work.right - work.left));
    int h = std::min(S(780), (int) (work.bottom - work.top));
    SetWindowPos(g_main, nullptr, work.left + (work.right - work.left - w) / 2,
                 work.top + (work.bottom - work.top - h) / 2, w, h,
                 SWP_NOZORDER | SWP_NOACTIVATE);
    Layout();
    g_accel = MakeAccelerators();
    g_lastFocus = g_text;
    ShowWindow(g_main, show);
    UpdateWindow(g_main);
    SetFocus(g_text);
    Status(L"Ready. Ctrl+Enter speaks, Esc stops, F1 lists the keys.");

    MSG m;
    while (GetMessageW(&m, nullptr, 0, 0) > 0) {
        if (TranslateAcceleratorW(g_main, g_accel, &m))
            continue;
        if (HandleKey(m))
            continue;
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    if (g_font)
        DeleteObject(g_font);
    return (int) m.wParam;
}
