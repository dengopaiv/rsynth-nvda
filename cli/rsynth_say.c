/*
    rsynth_say - speak text to a WAV file through the public API.

    The successor to the original `say` for this tree: same option letters
    where the meaning is the same (-m -F -S -K -M -G), but output goes to a
    WAV file, because the library has no sound card driver.

      rsynth_say [options] [words ...]      (or text on standard input)

      -o FILE   WAV file to write (default rsynth.wav)
      -r HZ     sample rate, 8000..48000 (default 22050)
      -m MS     frame length in ms, i.e. rate (default 10)
      -F HZ     base F0 (default 133)
      -S X      element duration multiplier (default 1.0)
      -K X      parameter smoothing fraction (default 0.5)
      -G DB     overall gain in dB (default 57)
      -V X      output volume scale, 0..2 (default 1)
      -M        monotone
      -L LEX    am | br | rules  (default am)
      -s        spell: name each character
      -P        input is SAMPA phones, not text
      -p        print the phones instead of synthesizing
      -n        print the normalized text instead of synthesizing

    Copyright (c) 2026 the rsynth-nvda contributors.
    Licensed under the GNU General Public License, version 2 or (at your
    option) any later version, as saymain.c was.
*/
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rsynth_api.h"

typedef struct {
    FILE *f;
    uint32_t samples;
    int32_t peak;
} wav_t;

static void
le16(FILE *f, unsigned v)
{
    fputc(v & 0xFF, f);
    fputc((v >> 8) & 0xFF, f);
}

static void
le32(FILE *f, uint32_t v)
{
    le16(f, v & 0xFFFF);
    le16(f, v >> 16);
}

static void
wav_header(FILE *f, int rate, uint32_t samples)
{
    fwrite("RIFF", 1, 4, f);
    le32(f, 36 + samples * 2);
    fwrite("WAVEfmt ", 1, 8, f);
    le32(f, 16);
    le16(f, 1);             /* PCM */
    le16(f, 1);             /* mono */
    le32(f, (uint32_t) rate);
    le32(f, (uint32_t) rate * 2);
    le16(f, 2);
    le16(f, 16);
    fwrite("data", 1, 4, f);
    le32(f, samples * 2);
}

static int
on_audio(void *user, const int16_t *s, int n)
{
    wav_t *w = (wav_t *) user;
    int i;
    for (i = 0; i < n; i++) {
        int v = s[i] < 0 ? -s[i] : s[i];
        if (v > w->peak)
            w->peak = v;
        le16(w->f, (uint16_t) s[i]);
    }
    w->samples += (uint32_t) n;
    return 0;
}

static char *
read_all(FILE *f)
{
    size_t n = 0, cap = 4096;
    char *p = (char *) malloc(cap);
    int c;
    if (!p)
        return NULL;
    while ((c = fgetc(f)) != EOF) {
        if (n + 1 >= cap) {
            char *q = (char *) realloc(p, cap *= 2);
            if (!q) {
                free(p);
                return NULL;
            }
            p = q;
        }
        p[n++] = (char) c;
    }
    p[n] = '\0';
    return p;
}

static char *
join(int argc, char **argv)
{
    size_t len = 1;
    int i;
    char *p;
    for (i = 0; i < argc; i++)
        len += strlen(argv[i]) + 1;
    p = (char *) malloc(len);
    if (!p)
        return NULL;
    p[0] = '\0';
    for (i = 0; i < argc; i++) {
        if (i)
            strcat(p, " ");
        strcat(p, argv[i]);
    }
    return p;
}

static void
usage(void)
{
    fprintf(stderr,
        "usage: rsynth_say [-o out.wav] [-r rate] [-m ms] [-F f0] [-S speed]\n"
        "                  [-K smooth] [-G gain] [-V volume] [-M]\n"
        "                  [-L am|br|rules] [-s] [-P] [-p] [-n] [words...]\n");
}

int
main(int argc, char **argv)
{
    const char *out = "rsynth.wav";
    int rate = 22050, spell = 0, phones_in = 0, print_phones = 0;
    int print_norm = 0, monotone = 0, lexicon = RS_LEX_CMU_AMERICAN;
    double frame_ms = 10, f0 = 133, speed = 1, smooth = 0.5, gain = 57;
    double volume = 1;
    int i;
    char *text;
    rs_engine *e;
    int rc = 0;

    for (i = 1; i < argc && argv[i][0] == '-' && argv[i][1]; i++) {
        const char *o = argv[i];
        const char *v = (i + 1 < argc) ? argv[i + 1] : NULL;
        if (!strcmp(o, "--")) {
            i++;
            break;
        }
        switch (o[1]) {
        case 'M': monotone = 1; continue;
        case 's': spell = 1; continue;
        case 'P': phones_in = 1; continue;
        case 'p': print_phones = 1; continue;
        case 'n': print_norm = 1; continue;
        case 'h': usage(); return 0;
        }
        if (!v) {
            usage();
            return 2;
        }
        i++;
        switch (o[1]) {
        case 'o': out = v; break;
        case 'r': rate = atoi(v); break;
        case 'm': frame_ms = atof(v); break;
        case 'F': f0 = atof(v); break;
        case 'S': speed = atof(v); break;
        case 'K': smooth = atof(v); break;
        case 'G': gain = atof(v); break;
        case 'V': volume = atof(v); break;
        case 'L':
            if (!strcmp(v, "am")) lexicon = RS_LEX_CMU_AMERICAN;
            else if (!strcmp(v, "br")) lexicon = RS_LEX_CMU_BRITISH;
            else if (!strcmp(v, "rules")) lexicon = RS_LEX_RULES;
            else { usage(); return 2; }
            break;
        default:
            usage();
            return 2;
        }
    }

    text = (i < argc) ? join(argc - i, argv + i) : read_all(stdin);
    if (!text) {
        fprintf(stderr, "rsynth_say: out of memory\n");
        return 1;
    }
    e = rs_create(rate);
    if (!e) {
        fprintf(stderr, "rsynth_say: bad sample rate %d\n", rate);
        free(text);
        return 2;
    }
    rs_set_frame_ms(e, frame_ms);
    rs_set_f0(e, f0);
    rs_set_speed(e, speed);
    rs_set_smooth(e, smooth);
    rs_set_gain_db(e, gain);
    rs_set_volume(e, volume);
    rs_set_monotone(e, monotone);
    rs_set_lexicon(e, lexicon);

    if (print_phones || print_norm) {
        int n = print_norm
            ? rs_normalize(e, text, spell ? RS_SPEAK_SPELL : 0, NULL, 0)
            : rs_text_to_phones(e, text, spell ? RS_SPEAK_SPELL : 0, NULL, 0);
        char *buf = (n >= 0) ? (char *) malloc((size_t) n + 1) : NULL;
        if (buf) {
            if (print_norm)
                rs_normalize(e, text, spell ? RS_SPEAK_SPELL : 0, buf, n + 1);
            else
                rs_text_to_phones(e, text, spell ? RS_SPEAK_SPELL : 0, buf, n + 1);
            printf("%s\n", buf);
            free(buf);
        } else {
            rc = 1;
        }
    } else {
        wav_t w = { 0 };
        w.f = fopen(out, "wb");
        if (!w.f) {
            perror(out);
            rc = 1;
        } else {
            wav_header(w.f, rate, 0);
            if (phones_in)
                rc = rs_speak_phones(e, text, on_audio, &w);
            else
                rc = rs_speak(e, text, spell ? RS_SPEAK_SPELL : 0, on_audio, &w);
            fseek(w.f, 0, SEEK_SET);
            wav_header(w.f, rate, w.samples);
            fclose(w.f);
            fprintf(stderr, "%s: %lu samples, %.2f s, peak %ld\n", out,
                    (unsigned long) w.samples, w.samples / (double) rate,
                    (long) w.peak);
        }
    }
    rs_destroy(e);
    free(text);
    return rc < 0 ? 1 : rc;
}
