#ifndef RESONATOR_H
#define RESONATOR_H

#include "synth_state.h"

/* Process one sample through a resonator */
static inline double resonator_process(Resonator *r, double input) {
    double x = r->a * input + r->b * r->p1 + r->c * r->p2;
    r->p2 = r->p1;
    r->p1 = x;
    return x;
}

/* Process through anti-resonator (saves input, not output) */
static inline double antiresonator_process(Resonator *r, double input) {
    double x = r->a * input + r->b * r->p1 + r->c * r->p2;
    r->p2 = r->p1;
    r->p1 = input;
    return x;
}

/* Apply one step of coefficient interpolation */
static inline void resonator_interpolate(Resonator *r) {
    r->a += r->a_inc;
    r->b += r->b_inc;
    r->c += r->c_inc;
}

/* Set target coefficients with interpolation */
void resonator_set_target(Resonator *r, double a, double b, double c, int steps);

/* Reset filter state */
void resonator_reset(Resonator *r);

/* Calculate resonator coefficients with pre-warping */
void set_resonator_coeffs(int sample_rate, double freq, double bandwidth,
                          int is_cascade, double *a, double *b, double *c);

/* Calculate anti-resonator coefficients */
void set_antiresonator_coeffs(int sample_rate, double freq, double bandwidth,
                              double *a, double *b, double *c);

/* Convert dB to linear amplitude */
double db_to_linear(double dB);

#endif /* RESONATOR_H */
