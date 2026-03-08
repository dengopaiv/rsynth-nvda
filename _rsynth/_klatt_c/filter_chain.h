#ifndef FILTER_CHAIN_H
#define FILTER_CHAIN_H

#include "synth_state.h"

/* Apply cascade and parallel filters to produce output sample */
double filter_sample(KlattState *st, double voice, double noise);

/* DC blocking high-pass filter */
double dc_block(KlattState *st, double sample);

#endif /* FILTER_CHAIN_H */
