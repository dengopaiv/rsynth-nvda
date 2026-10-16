/*
    dict_builtin.c - the CMU Pronouncing Dictionary, compiled in.

    Stands in for dict.c. dict.c opened a GDBM or Berkeley DB file built by
    mkdictdb and fetched a word's phone codes from it; here the same codes
    come from the table tools/mkdicttab.c generates at build time, found by
    binary search. What a lookup returns is unchanged: the word's phone
    codes, NUL-terminated, in a malloc'd buffer the caller frees (say.c's
    xlate_word does).

    dict_lookup() lower-cased the key with isupper/tolower before fetching;
    so does this. The table's keys are already lower case.

    Copyright (c) 1994,2001-2003 Nick Ing-Simmons (dict.c).
    Copyright (c) 2026 the rsynth-nvda contributors.
    Licensed under the GNU Library General Public License, version 2 or
    (at your option) any later version.
*/
#include "config.h"
#include <ctype.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "rs_internal.h"

/* Generated: cmudict_table.c in the build directory. */
extern const unsigned char rsynth_dict_blob[];
extern const uint32_t rsynth_dict_index[];
extern const uint32_t rsynth_dict_count;

/* Compare the n-byte key (already lower case) with a NUL-terminated
   table word, as strcmp would compare the key if it were terminated. */
static int
keycmp(const unsigned char *key, unsigned n, const unsigned char *word)
{
    unsigned i;
    for (i = 0; i < n; i++) {
        if (!word[i])
            return 1;
        if (key[i] != word[i])
            return key[i] < word[i] ? -1 : 1;
    }
    return word[n] ? -1 : 0;
}

unsigned char *
rs_dict_lookup(const char *s, unsigned n)
{
    unsigned char key[256];
    uint32_t lo = 0, hi = rsynth_dict_count;
    unsigned i;

    if (!n)
        n = (unsigned) strlen(s);
    /* No CMU word comes near this long; mkdicttab reads 4 KB lines. */
    if (n == 0 || n >= sizeof(key))
        return NULL;
    for (i = 0; i < n; i++) {
        unsigned char c = (unsigned char) s[i];
        key[i] = (unsigned char) (isupper(c) ? tolower(c) : c);
    }

    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        const unsigned char *word = rsynth_dict_blob + rsynth_dict_index[mid];
        int c = keycmp(key, n, word);
        if (c == 0) {
            const unsigned char *codes = word + n + 1;
            size_t len = strlen((const char *) codes);
            unsigned char *w = (unsigned char *) malloc(len + 1);
            if (w)
                memcpy(w, codes, len + 1);
            return w;
        }
        if (c < 0)
            hi = mid;
        else
            lo = mid + 1;
    }
    return NULL;
}

unsigned
rs_dict_size(void)
{
    return (unsigned) rsynth_dict_count;
}
