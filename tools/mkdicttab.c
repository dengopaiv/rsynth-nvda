/*
    mkdicttab - compile a pronouncing dictionary into a C table.

    This is mkdictdb.c with the database taken out. mkdictdb read the CMU
    Pronouncing Dictionary (or BEEP) and stored each word, as a string of
    phone codes from phones.def, in a GDBM or Berkeley DB file that dict.c
    opened at run time. mkdicttab reads the same input with the same rules
    and writes the same key/code pairs as a sorted C array instead, so the
    dictionary is compiled into the library and nothing is opened at run time.

    The parsing loop in enter_words() is mkdictdb.c's, kept line for line so
    the two can be compared; the differences are marked "mkdicttab:". See
    docs/03-dictionary.md for what was checked.

    Copyright (c) 1994,2001-2002 Nick Ing-Simmons. All rights reserved.
    Changes for rsynth-nvda copyright (c) 2026 the rsynth-nvda contributors.

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program; if not, write to the Free Software
    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
*/
#include "config.h"
#include <stdio.h>
#include <stdint.h>
#include <ctype.h>
#include "useconfig.h"
#include "trie.h"
#include "phones.h"

static trie_ptr phones;

static void
enter_phones(void)
{
 int i;
 char *s;
 for (i = 1; (s = ph_name[i]); i++)
  trie_insert(&phones, s, (void *) (intptr_t) i);   /* mkdicttab: intptr_t, for 64-bit */
}

/* mkdicttab: what DB_STORE did, into memory. */
typedef struct
 {
  char *word;           /* lower-case key, NUL-terminated */
  unsigned char *codes; /* phone codes, NUL-terminated */
  unsigned line;        /* source line, so first-wins is well defined */
 } entry_t;

static entry_t *entries;
static size_t nentries, aentries;
static unsigned bad_codes, ignored;

static void
store(const char *key, size_t klen, const char *codes, size_t clen, unsigned line)
{
 entry_t *e;
 if (nentries == aentries)
  {
   aentries = aentries ? 2 * aentries : 65536;
   entries = (entry_t *) realloc(entries, aentries * sizeof(*entries));
   if (!entries)
    {
     perror("mkdicttab");
     exit(1);
    }
  }
 e = &entries[nentries++];
 e->word = (char *) malloc(klen + 1);
 e->codes = (unsigned char *) malloc(clen + 1);
 if (!e->word || !e->codes)
  {
   perror("mkdicttab");
   exit(1);
  }
 memcpy(e->word, key, klen);
 e->word[klen] = '\0';
 memcpy(e->codes, codes, clen);
 e->codes[clen] = '\0';
 e->line = line;
}

static void
enter_words(FILE * f)
{
 char buf[4096];
 unsigned line = 0;
 while (fgets(buf, sizeof(buf), f))
  {
   char *s = buf;
   char *h = strchr(s, '#');
   line++;
   if (h)
    *h = '\0';
   while (isspace((unsigned char)*s))
    s++;
   if (*s)
    {
     unsigned char *p = (unsigned char *) s;
     /* mkdicttab: the accent escapes ('"', '~', '<', '\\') that mkdictdb
        folded into ISO-8859-1 letters are BEEP conventions; CMU has none.
        A word holding one is refused rather than folded, so the table, and
        so the library, stays pure ASCII. */
     while (!isspace(*p))
      {
       if (isupper(*p))
        *p = (unsigned char) tolower(*p);
       else if (!isalpha(*p) && *p != '\'' && *p != '-' && *p != '_' && *p != '.')
        break;
       p++;
      }
     if (isspace(*p))
      {
       char codes[4096];
       char *d = codes;
       int ok = 1;
       char *key = s;
       size_t klen = (char *) p - s;
       while (*p && ok)
        {
         unsigned code;
         while (isspace(*p))
          p++;
         if (*p)
          {
           unsigned char *e = p;
           while (isalpha(*e) || *e == '1' || *e == '2')
            {
             if (islower(*e))
              *e = (unsigned char) toupper(*e);
             e++;
            }
           if (*e == '0')
            *e++ = ' ';
           if (e > p && (code = (unsigned) (intptr_t) trie_lookup(&phones, (char **) &p)))
            *d++ = (char) code;
           else
            {
             fprintf(stderr, "Bad code %.*s>%s", (int)((char *) p - s), s, p);
             bad_codes++;
             ok = 0;
             break;
            }
          }
        }
       if (ok)
        store(key, klen, codes, d - codes, line);
      }
     else
      {
       /* mkdicttab: alternative pronunciations "word(2)" end here, as in
          mkdictdb; only the first pronunciation of a word is kept. */
       if (*p != '(')
        fprintf(stderr, "Ignore (%c) %s", *p, s);
       ignored++;
      }
    }
  }
}

static int
by_word_then_line(const void *a, const void *b)
{
 const entry_t *x = (const entry_t *) a;
 const entry_t *y = (const entry_t *) b;
 int c = strcmp(x->word, y->word);
 if (c)
  return c;
 return (x->line > y->line) - (x->line < y->line);
}

/* Emit bytes as a numeric initializer: MSVC caps a string literal at 64 KB,
   and the table is about two megabytes. */
static void
emit_bytes(FILE * out, const unsigned char *s, size_t n, unsigned *col)
{
 size_t i;
 for (i = 0; i < n; i++)
  {
   *col += (unsigned) fprintf(out, "%u,", s[i]);
   if (*col > 72)
    {
     fputc('\n', out);
     *col = 0;
    }
  }
}

int
main(int argc, char **argv)
{
 FILE *f, *out;
 size_t i, kept = 0, dups = 0;
 uint32_t offset = 0;
 unsigned col = 0;

 if (argc != 3)
  {
   fprintf(stderr, "usage: mkdicttab cmudict.dict out.c\n");
   return 2;
  }
 f = fopen(argv[1], "r");
 if (!f)
  {
   perror(argv[1]);
   return 1;
  }
 enter_phones();
 enter_words(f);
 fclose(f);

 /* GDBM_INSERT, the store mkdictdb's GDBM build used, keeps the first
    entry for a key; sorting by (word, line) and keeping the first of each
    run does the same. */
 qsort(entries, nentries, sizeof(*entries), by_word_then_line);

 out = fopen(argv[2], "w");
 if (!out)
  {
   perror(argv[2]);
   return 1;
  }
 fprintf(out,
  "/* GENERATED by tools/mkdicttab.c from %s. Do not edit. */\n"
  "/* CMU Pronouncing Dictionary, Copyright (C) 1993-2015 Carnegie Mellon\n"
  "   University; see dict/cmudict/LICENSE. */\n"
  "#include <stdint.h>\n\n"
  "/* Each entry: the lower-case word, NUL, its phone codes (phones.def\n"
  "   order, 1-based), NUL. */\n"
  "const unsigned char rsynth_dict_blob[] = {\n", "cmudict.dict");
 for (i = 0; i < nentries; i++)
  {
   entry_t *e = &entries[i];
   if (i && !strcmp(e->word, entries[i - 1].word))
    {
     dups++;
     continue;
    }
   emit_bytes(out, (unsigned char *) e->word, strlen(e->word) + 1, &col);
   emit_bytes(out, e->codes, strlen((char *) e->codes) + 1, &col);
   kept++;
  }
 fprintf(out, "0};\n\n");

 fprintf(out, "const uint32_t rsynth_dict_index[] = {\n");
 col = 0;
 for (i = 0; i < nentries; i++)
  {
   entry_t *e = &entries[i];
   if (i && !strcmp(e->word, entries[i - 1].word))
    continue;
   col += (unsigned) fprintf(out, "%lu,", (unsigned long) offset);
   if (col > 72)
    {
     fputc('\n', out);
     col = 0;
    }
   offset += (uint32_t) (strlen(e->word) + 1 + strlen((char *) e->codes) + 1);
  }
 fprintf(out, "0};\n\n");
 fprintf(out, "const uint32_t rsynth_dict_count = %lu;\n", (unsigned long) kept);
 fclose(out);

 fprintf(stderr, "mkdicttab: %lu words, %lu duplicate keys dropped, "
         "%u lines ignored, %u with bad codes, %lu bytes\n",
         (unsigned long) kept, (unsigned long) dups, ignored, bad_codes,
         (unsigned long) offset);
 trie_free(&phones, NULL);
 return 0;
}
