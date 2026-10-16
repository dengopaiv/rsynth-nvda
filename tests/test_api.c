/*
    test_api - checks the library through its public API only.

      test_api golden.txt            check
      test_api golden.txt --update   rewrite golden.txt from this build

    Four kinds of check:

    1. Front end: rs_normalize() on inputs whose expected ASCII is known.
    2. Robustness: every byte value, malformed UTF-8 and every printable
       character spelt, none of which may crash (charset.c's deaccent()
       aborts on unknown high bytes; the front end must keep them out).
    3. Behaviour: a callback that cancels stops delivery; speaking the same
       text twice gives the same samples.
    4. Golden: a fixed corpus, each item's sample count and FNV-1a hash
       compared with golden.txt. These were recorded from this library and
       pin its output: any change to synthesis shows up here, and must be
       explained in docs/ before golden.txt is updated.

    Copyright (c) 2026 the rsynth-nvda contributors.
    Licensed under the GNU Library General Public License, version 2 or
    (at your option) any later version.
*/
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rsynth_api.h"

static int failures;

#define CHECK(cond, ...)                                        \
    do {                                                        \
        if (!(cond)) {                                          \
            failures++;                                         \
            fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__); \
            fprintf(stderr, __VA_ARGS__);                       \
            fputc('\n', stderr);                                \
        }                                                       \
    } while (0)

/* --- audio sinks -------------------------------------------------------- */

typedef struct {
    uint64_t hash;
    uint32_t samples;
    int calls;
    int cancel_after;   /* cancel on this call number (1-based); 0 never */
} sink_t;

static void
sink_init(sink_t *s)
{
    memset(s, 0, sizeof(*s));
    s->hash = 0xcbf29ce484222325ULL;
}

static int
on_audio(void *user, const int16_t *x, int n)
{
    sink_t *s = (sink_t *) user;
    int i;
    s->calls++;
    for (i = 0; i < n; i++) {
        uint16_t v = (uint16_t) x[i];
        s->hash = (s->hash ^ (v & 0xFF)) * 0x100000001b3ULL;
        s->hash = (s->hash ^ (v >> 8)) * 0x100000001b3ULL;
    }
    s->samples += (uint32_t) n;
    return s->cancel_after && s->calls >= s->cancel_after;
}

/* --- 1. front end ------------------------------------------------------- */

static void
expect_norm(rs_engine *e, const char *in, const char *want)
{
    char out[512];
    int n = rs_normalize(e, in, 0, out, sizeof out);
    CHECK(n >= 0 && !strcmp(out, want),
          "normalize(\"%s\") = \"%s\", want \"%s\"", in, out, want);
}

static void
test_frontend(rs_engine *e)
{
    char out[512];
    int n;

    expect_norm(e, "plain ascii", "plain ascii");
    expect_norm(e, "caf\xc3\xa9 na\xc3\xafve \xc5\x81\xc3\xb3" "d\xc5\xba",
                "cafe naive Lodz");
    expect_norm(e, "Stra\xc3\x9f" "e \xc3\x86sir \xc5\x93uvre", "Strasse AEsir oeuvre");
    expect_norm(e, "\xe2\x80\x9cquoted\xe2\x80\x9d \xe2\x80\x94 it\xe2\x80\x99s\xe2\x80\xa6",
                "\"quoted\" - it's...");
    expect_norm(e, "\xe6\x97\xa5\xe6\x9c\xac", "  ");
    expect_norm(e, "a\tb\nc\x01" "d", "a b c d");
    expect_norm(e, "bad \xff\xfe utf", "bad    utf");
    expect_norm(e, "a[i] = b[j]", "a i  = b j ");
    expect_norm(e, "1,234,567 people", "1234567 people");
    expect_norm(e, "999,999,999", "999999999");
    expect_norm(e, "1,000,000,000", "1 0 0 0 0 0 0 0 0 0");
    expect_norm(e, "12,34", "12,34");
    expect_norm(e, "1,2345", "1,2345");
    expect_norm(e, "123456789", "123456789");
    expect_norm(e, "1234567890", "1 2 3 4 5 6 7 8 9 0");
    expect_norm(e, "-12345678901", "-1 2 3 4 5 6 7 8 9 0 1");
    expect_norm(e, "3.14159265358979", "3.14159265358979");
    expect_norm(e, "abc12345678901", "abc1 2 3 4 5 6 7 8 9 0 1");
    expect_norm(e, "mp3", "mp3");

    n = rs_normalize(e, "the 21st of May", 0, out, sizeof out);
    CHECK(n > 0 && !strncmp(out, "the [", 5) && strstr(out, "] of May"),
          "ordinal not rewritten: \"%s\"", out);
    n = rs_normalize(e, "1st 2nd 3rd 4th", 0, out, sizeof out);
    {
        int brackets = 0;
        const char *p;
        for (p = out; *p; p++)
            brackets += (*p == '[');
        /* Not "no digits": '3' is a SAMPA vowel ("3`" in "first"). */
        CHECK(n > 0 && brackets == 4 && !strstr(out, "1st")
              && !strstr(out, "2nd") && !strstr(out, "3rd")
              && !strstr(out, "4th"),
              "ordinals not rewritten: \"%s\"", out);
    }
    expect_norm(e, "21stcentury", "21stcentury");

    /* Spelling keeps brackets: they have names. */
    n = rs_normalize(e, "[x]", RS_SPEAK_SPELL, out, sizeof out);
    CHECK(n == 3 && !strcmp(out, "[x]"), "spell normalize: \"%s\"", out);

    /* Short buffer: the full length comes back, the copy is truncated. */
    n = rs_normalize(e, "abcdef", 0, out, 4);
    CHECK(n == 6 && !strcmp(out, "abc"), "truncation: %d \"%s\"", n, out);
}

/* --- 2. robustness ------------------------------------------------------ */

static void
test_bytes(rs_engine *e)
{
    char buf[4];
    int c;
    sink_t s;
    for (c = 1; c < 256; c++) {
        buf[0] = (char) c;
        buf[1] = 'a';
        buf[2] = (char) c;
        buf[3] = '\0';
        sink_init(&s);
        CHECK(rs_speak(e, buf, 0, on_audio, &s) >= 0, "byte %d", c);
        sink_init(&s);
        CHECK(rs_speak(e, buf, RS_SPEAK_SPELL, on_audio, &s) >= 0,
              "spell byte %d", c);
    }
    {
        char all[96];
        for (c = 32; c < 127; c++)
            all[c - 32] = (char) c;
        all[95] = '\0';
        sink_init(&s);
        CHECK(rs_speak(e, all, RS_SPEAK_SPELL, on_audio, &s) == 0,
              "spell printable");
        CHECK(s.samples > 0, "spelling printable ASCII made no sound");
        sink_init(&s);
        CHECK(rs_speak(e, all, 0, on_audio, &s) == 0, "speak printable");
    }
    sink_init(&s);
    CHECK(rs_speak(e, "", 0, on_audio, &s) == 0 && s.samples == 0, "empty");
    CHECK(rs_speak(e, NULL, 0, on_audio, &s) < 0, "NULL text accepted");
    CHECK(rs_speak(NULL, "x", 0, on_audio, &s) < 0, "NULL engine accepted");
    CHECK(rs_create(4000) == NULL, "sample rate 4000 accepted");
}

/* --- 3. behaviour ------------------------------------------------------- */

static const char *long_text =
    "This is a longer passage, with several clauses; it goes on for a while. "
    "The point is that cancelling must stop it quickly! Does it? We will see.";

static void
test_behaviour(rs_engine *e)
{
    sink_t a, b, c;

    sink_init(&a);
    CHECK(rs_speak(e, long_text, 0, on_audio, &a) == 0, "speak");
    sink_init(&b);
    CHECK(rs_speak(e, long_text, 0, on_audio, &b) == 0, "speak again");
    CHECK(a.samples == b.samples && a.hash == b.hash,
          "same text twice differs: %u/%u", a.samples, b.samples);

    sink_init(&c);
    c.cancel_after = 2;
    CHECK(rs_speak(e, long_text, 0, on_audio, &c) == 1, "cancel not reported");
    CHECK(c.calls == 2, "callback ran %d times after cancelling", c.calls);

    /* A cancelled call leaves nothing behind for the next one. */
    sink_init(&b);
    CHECK(rs_speak(e, long_text, 0, on_audio, &b) == 0, "speak after cancel");
    CHECK(a.samples == b.samples && a.hash == b.hash,
          "output after a cancel differs");

    /* Halving the frame length roughly halves the duration. */
    rs_set_frame_ms(e, 5);
    sink_init(&b);
    rs_speak(e, long_text, 0, on_audio, &b);
    rs_set_frame_ms(e, 10);
    CHECK(b.samples < a.samples * 0.6 && b.samples > a.samples * 0.4,
          "frame 5 ms gave %u samples against %u at 10 ms", b.samples,
          a.samples);
}

/* --- 4. golden ---------------------------------------------------------- */

typedef struct {
    const char *name;
    int rate;
    int lexicon;
    unsigned flags;
    double frame_ms, f0;
    int monotone;
    int phones;         /* text is SAMPA */
    const char *text;
} item_t;

static const item_t corpus[] = {
    { "hello", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "Hello, world." },
    { "sentence", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "The quick brown fox jumps over the lazy dog." },
    { "question", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "Is this the right way to the station? Yes, it is." },
    { "british", 22050, RS_LEX_CMU_BRITISH, 0, 10, 133, 0, 0,
      "Schedule a tomato bath for the lot." },
    { "rules", 22050, RS_LEX_RULES, 0, 10, 133, 0, 0,
      "Schedule a tomato bath for the lot." },
    { "numbers", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "1,234,567 and -42 and 3.14 and 1234567890123, on the 21st." },
    { "spell", 22050, RS_LEX_CMU_AMERICAN, RS_SPEAK_SPELL, 10, 133, 0, 0,
      "NVDA 2026" },
    { "accents", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "Caf\xc3\xa9 cr\xc3\xa8me br\xc3\xbbl\xc3\xa9" "e \xe2\x80\x94 na\xc3\xafve." },
    { "unknown", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "Frobnicating xyzzy plugh grault." },
    { "rate8k", 8000, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "Eight kilohertz, as the original drivers ran." },
    { "rate11k", 11025, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 0,
      "Eleven kilohertz, the ALSA default." },
    { "fast", 22050, RS_LEX_CMU_AMERICAN, 0, 4, 133, 0, 0,
      "Speaking quickly by shortening the frame." },
    { "pitch", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 220, 0, 0,
      "A higher voice." },
    { "monotone", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 1, 0,
      "A flat voice, held on one pitch." },
    { "phones", 22050, RS_LEX_CMU_AMERICAN, 0, 10, 133, 0, 1,
      "h@'loU w'3`ld" },
};

#define NCORPUS (sizeof(corpus) / sizeof(corpus[0]))

static void
run_item(const item_t *it, sink_t *s)
{
    rs_engine *e = rs_create(it->rate);
    sink_init(s);
    if (!e) {
        CHECK(0, "%s: rs_create", it->name);
        return;
    }
    rs_set_lexicon(e, it->lexicon);
    rs_set_frame_ms(e, it->frame_ms);
    rs_set_f0(e, it->f0);
    rs_set_monotone(e, it->monotone);
    if (it->phones)
        rs_speak_phones(e, it->text, on_audio, s);
    else
        rs_speak(e, it->text, it->flags, on_audio, s);
    rs_destroy(e);
    CHECK(s->samples > 0, "%s: no audio", it->name);
}

static int
test_golden(const char *path, int update)
{
    size_t i;
    if (update) {
        FILE *f = fopen(path, "w");
        if (!f) {
            perror(path);
            return 1;
        }
        fprintf(f, "# name samples fnv1a64 -- written by test_api --update\n");
        for (i = 0; i < NCORPUS; i++) {
            sink_t s;
            run_item(&corpus[i], &s);
            fprintf(f, "%s %lu %016llx\n", corpus[i].name,
                    (unsigned long) s.samples, (unsigned long long) s.hash);
        }
        fclose(f);
        printf("wrote %s\n", path);
        return 0;
    }
    {
        FILE *f = fopen(path, "r");
        char line[256];
        size_t seen = 0;
        if (!f) {
            perror(path);
            failures++;
            return 1;
        }
        while (fgets(line, sizeof line, f)) {
            char name[64];
            unsigned long samples;
            unsigned long long hash;
            if (line[0] == '#')
                continue;
            if (sscanf(line, "%63s %lu %llx", name, &samples, &hash) != 3)
                continue;
            for (i = 0; i < NCORPUS; i++) {
                if (!strcmp(corpus[i].name, name)) {
                    sink_t s;
                    run_item(&corpus[i], &s);
                    CHECK(s.samples == samples && s.hash == hash,
                          "golden %s: %lu %016llx, want %lu %016llx", name,
                          (unsigned long) s.samples,
                          (unsigned long long) s.hash, samples, hash);
                    seen++;
                }
            }
        }
        fclose(f);
        CHECK(seen == NCORPUS, "golden.txt covers %u of %u items",
              (unsigned) seen, (unsigned) NCORPUS);
    }
    return 0;
}

int
main(int argc, char **argv)
{
    rs_engine *e;
    int update = argc > 2 && !strcmp(argv[2], "--update");
    if (argc < 2) {
        fprintf(stderr, "usage: test_api golden.txt [--update]\n");
        return 2;
    }
    CHECK(rs_api_version() == RS_API_VERSION, "API version");
    e = rs_create(22050);
    CHECK(e != NULL, "rs_create");
    if (!e)
        return 1;
    if (!update) {
        test_frontend(e);
        test_bytes(e);
        test_behaviour(e);
    }
    rs_destroy(e);
    test_golden(argv[1], update);
    if (failures) {
        fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    printf("all passed\n");
    return 0;
}
