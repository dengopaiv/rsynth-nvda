#include "filter_chain.h"
#include "resonator.h"

double filter_sample(KlattState *st, double voice, double noise) {
    /* Cascade path: voice through nasal and formant resonators */
    voice = resonator_process(&st->rnpc, voice);
    voice = antiresonator_process(&st->rnz, voice);
    voice = resonator_process(&st->r1c, voice);
    voice = resonator_process(&st->r2c, voice);
    voice = resonator_process(&st->r3c, voice);
    voice = resonator_process(&st->r4c, voice);
    voice = resonator_process(&st->rsc, voice);

    if (st->sample_rate > 8000) {
        voice = resonator_process(&st->r5c, voice);
    }

    /* Parallel path: frication noise through parallel resonators */
    /* Scale by 0.5 to compensate for additive energy vs cascade attenuation */
    double parallel = (
        resonator_process(&st->r2p, noise) +
        resonator_process(&st->r3p, noise) +
        resonator_process(&st->r4p, noise) +
        resonator_process(&st->r5p, noise) +
        resonator_process(&st->r6p, noise) +
        st->amp_bypass * noise
    ) * 0.5;

    /* Combine cascade and parallel paths */
    voice = voice + parallel;

    /* Final low-pass and gain */
    voice = resonator_process(&st->rout, voice);

    /* Remove DC offset */
    voice = dc_block(st, voice);

    return voice;
}

double dc_block(KlattState *st, double sample) {
    double DC_R = 0.99;
    double y = sample - st->dc_x1 + DC_R * st->dc_y1;
    st->dc_x1 = sample;
    st->dc_y1 = y;
    return y;
}
