#ifndef SYNTH_STATE_H
#define SYNTH_STATE_H

#define _USE_MATH_DEFINES
#include <math.h>
#include <stdint.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define VOICE_IMPULSIVE 1
#define VOICE_NATURAL   2

#define PARAM_COUNT 18

/* Parameter indices (matching Python Param class) */
enum {
    PARAM_fn  = 0,
    PARAM_f1  = 1,
    PARAM_f2  = 2,
    PARAM_f3  = 3,
    PARAM_b1  = 4,
    PARAM_b2  = 5,
    PARAM_b3  = 6,
    PARAM_pn  = 7,
    PARAM_a2  = 8,
    PARAM_a3  = 9,
    PARAM_a4  = 10,
    PARAM_a5  = 11,
    PARAM_a6  = 12,
    PARAM_ab  = 13,
    PARAM_av  = 14,
    PARAM_avc = 15,
    PARAM_asp = 16,
    PARAM_af  = 17
};

typedef struct {
    double a, b, c;
    double p1, p2;
    double a_inc, b_inc, c_inc;
} Resonator;

typedef struct {
    int sample_rate;
    int samples_per_frame;

    /* Current frame parameters */
    double params[PARAM_COUNT];

    /* Voicing state */
    int nper;
    int T0;
    int nopen;
    double F0Hz;

    /* Amplitude values (converted from dB) */
    double amp_av;
    double amp_bypass;
    double amp_asp;
    double amp_af;
    double amp_avc;
    double amp_turb;

    /* Noise ramp */
    int noise_ramp_samples;
    int noise_ramp_length;
    int voiceless_started;

    /* RNG state */
    unsigned int seed;

    /* Sample counter */
    int ns;

    /* Voice quality */
    double jitter;
    double shimmer;
    int flutter;
    double flutter_t;

    /* Voice source type */
    int voice_source;
    double sample_pos;

    /* Voicing transition tracking */
    int was_voiced;

    /* DC blocker state */
    double dc_x1;
    double dc_y1;

    /* Smoothing */
    double smooth;
    double speed;

    /* Speaker params */
    double spk_F0Hz, spk_Gain0;
    double spk_F4hz, spk_B4hz, spk_F5hz, spk_B5hz, spk_F6hz, spk_B6hz;
    double spk_FNPhz, spk_BNhz;
    double spk_B4phz, spk_B5phz, spk_B6phz;
    double spk_F1_offset, spk_F1_scale;
    double spk_F2_offset, spk_F2_scale;
    double spk_F3_offset, spk_F3_scale;

    /* Cascade resonators */
    Resonator rgl;   /* Glottal low-pass */
    Resonator rnz;   /* Nasal zero (anti-resonator) */
    Resonator rnpc;  /* Nasal pole */
    Resonator r5c;   /* F5 cascade */
    Resonator rsc;   /* Special cascade (3500 Hz) */
    Resonator r4c;   /* F4 cascade */
    Resonator r3c;   /* F3 cascade */
    Resonator r2c;   /* F2 cascade */
    Resonator r1c;   /* F1 cascade */

    /* Parallel resonators */
    Resonator r6p;
    Resonator r5p;
    Resonator r4p;
    Resonator r3p;
    Resonator r2p;

    /* Output resonator */
    Resonator rout;

    /* Natural samples table */
    double natural_samples[100];
    int natural_samples_len;

    /* xorshift128+ state for improved noise gen */
    uint64_t rng_s0;
    uint64_t rng_s1;
} KlattState;

#endif /* SYNTH_STATE_H */
