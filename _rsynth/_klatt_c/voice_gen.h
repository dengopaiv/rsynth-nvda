#ifndef VOICE_GEN_H
#define VOICE_GEN_H

#include "synth_state.h"

/* xorshift128+ RNG - uniform [0,1) */
static inline double uniform_random(KlattState *st) {
    uint64_t x = st->rng_s0;
    uint64_t y = st->rng_s1;
    st->rng_s0 = y;
    x ^= x << 23;
    st->rng_s1 = x ^ y ^ (x >> 17) ^ (y >> 26);
    uint64_t result = st->rng_s1 + y;
    return (result >> 11) * (1.0 / 9007199254740992.0);
}

/* Generate Gaussian-distributed noise (improved xorshift128+ / Box-Muller) */
double gen_noise(KlattState *st);

/* Generate voice waveform at 4x sample rate with PolyBLEP anti-aliasing */
double gen_voice(KlattState *st, double noise);

/* Update pitch-synchronous parameters */
void pitch_sync(KlattState *st);

/* Apply 3-sine flutter for natural pitch variation */
double apply_flutter(KlattState *st, double f0_hz);

#endif /* VOICE_GEN_H */
