#include "voice_gen.h"
#include "resonator.h"
#include <stdlib.h>

double gen_noise(KlattState *st) {
    /*
     * Box-Muller transform for true Gaussian noise.
     * Much faster than the original 16-iteration LCG central limit approach.
     * Generates two values; we use both by caching.
     */
    double u1 = uniform_random(st);
    double u2 = uniform_random(st);

    /* Avoid log(0) */
    if (u1 < 1e-15) u1 = 1e-15;

    /* Box-Muller: generate standard normal, scale to match original range.
     * Original: sum of 16 uniform [-8192, 8192] / 2 ≈ std dev ~9400
     * We scale to match approximately. */
    double noise = sqrt(-2.0 * log(u1)) * cos(2.0 * M_PI * u2);
    return noise * 9400.0;
}

/* --- PolyBLEP anti-aliasing --- */

/*
 * PolyBLEP correction for waveform discontinuities.
 * t is the fractional phase position (0 to 1) relative to the period.
 * dt is the phase increment per sample (1/period).
 * Returns correction to add to the naive waveform.
 */
static inline double polyblep(double t, double dt) {
    if (t < dt) {
        /* Just after discontinuity */
        double tn = t / dt;
        return tn + tn - tn * tn - 1.0;
    } else if (t > 1.0 - dt) {
        /* Just before discontinuity */
        double tn = (t - 1.0) / dt;
        return tn * tn + tn + tn + 1.0;
    }
    return 0.0;
}

/* --- Pitch sync --- */

void pitch_sync(KlattState *st) {
    double F0Hz = st->F0Hz;

    if (st->params[PARAM_av] > 0 || st->params[PARAM_avc] > 0) {
        int base_T0 = (int)((4 * st->sample_rate) / F0Hz);

        if (st->jitter > 0) {
            double jitter_amount = base_T0 * st->jitter * (uniform_random(st) * 2.0 - 1.0);
            st->T0 = (int)(base_T0 + jitter_amount);
            if (st->T0 < 4) st->T0 = 4;
        } else {
            st->T0 = base_T0;
        }

        st->amp_av = db_to_linear(st->params[PARAM_av]);
        st->amp_avc = db_to_linear(st->params[PARAM_avc]);
        st->amp_turb = st->amp_avc * 0.05;
        st->nopen = st->T0 / 3;
    } else {
        st->T0 = 4;
        st->nopen = st->T0;
        st->amp_av = 0.0;
        st->amp_avc = 0.0;
    }

    if (st->T0 != 4 || st->ns == 0) {
        double a, b, c;
        set_resonator_coeffs(st->sample_rate, 0, 2 * F0Hz, 1, &a, &b, &c);
        st->rgl.a = a;
        st->rgl.b = b;
        st->rgl.c = c;
    }
}

/* --- Voice generation with PolyBLEP --- */

double gen_voice(KlattState *st, double noise) {
    double voice = 0.0;
    double amp = 4096.0;
    int i;

    for (i = 0; i < 4; i++) {
        if (st->nper >= st->T0) {
            st->nper = 0;
            pitch_sync(st);
        }

        if (st->voice_source == VOICE_NATURAL) {
            int num_samples = st->natural_samples_len;
            double alpha = (st->T0 > 0) ? (double)st->nper / st->T0 : 0.0;
            double pos = alpha * num_samples;
            int idx = (int)pos;
            double frac = pos - idx;

            if (idx < num_samples - 1) {
                voice = st->natural_samples[idx] * (1.0 - frac)
                      + st->natural_samples[idx + 1] * frac;
            } else if (idx < num_samples) {
                voice = st->natural_samples[idx];
            } else {
                voice = 0.0;
            }
            voice *= (amp / 2500.0);

            /* PolyBLEP at glottal closure (table wraparound).
             * The discontinuity occurs near the end of the natural samples
             * table where the waveform drops sharply. */
            if (st->T0 > 0) {
                double dt = 1.0 / st->T0;
                double blep = polyblep(alpha, dt);
                /* Scale correction by the discontinuity magnitude */
                voice += blep * (amp / 2500.0) * 300.0;
            }
        } else {
            /* Impulsive source */
            double alpha = (st->T0 > 0) ? (double)st->nper / st->T0 : 0.0;

            if (alpha <= 1.0 / 3.0) {
                voice = 3.0 * amp * alpha;
            } else {
                voice = amp * ((9.0 * alpha - 12.0) * alpha + 3.0);
            }

            /* PolyBLEP at glottal closure (alpha wraps from ~1 to 0).
             * The discontinuity is the jump from the end of the parabolic
             * decay back to zero at the start of the linear ramp. */
            if (st->T0 > 0) {
                double dt = 1.0 / st->T0;
                double blep = polyblep(alpha, dt);
                /* The discontinuity magnitude is approximately -amp
                 * (parabola ends near -amp, ramp starts at 0) */
                voice += blep * amp;
            }
        }

        st->nper++;
    }

    return voice;
}

/* --- Flutter --- */

double apply_flutter(KlattState *st, double f0_hz) {
    double fla, flb, flc, fld, fle, delta_f0;

    if (st->flutter <= 0)
        return f0_hz;

    fla = st->flutter / 50.0;
    flb = f0_hz / 100.0;
    flc = sin(M_PI * 12.7 * st->flutter_t);
    fld = sin(M_PI * 7.1 * st->flutter_t);
    fle = sin(M_PI * 4.7 * st->flutter_t);

    delta_f0 = fla * flb * (flc + fld + fle) * 10.0;

    st->flutter_t += 0.001;
    if (st->flutter_t > 1000.0)
        st->flutter_t = 0.0;

    return f0_hz + delta_f0;
}
