#include "resonator.h"

void resonator_set_target(Resonator *r, double a, double b, double c, int steps) {
    if (steps > 0) {
        r->a_inc = (a - r->a) / steps;
        r->b_inc = (b - r->b) / steps;
        r->c_inc = (c - r->c) / steps;
    } else {
        r->a = a;
        r->b = b;
        r->c = c;
        r->a_inc = r->b_inc = r->c_inc = 0.0;
    }
}

void resonator_reset(Resonator *r) {
    r->p1 = 0.0;
    r->p2 = 0.0;
}

void set_resonator_coeffs(int sample_rate, double freq, double bandwidth,
                          int is_cascade, double *out_a, double *out_b, double *out_c) {
    double minus_pi_t = -M_PI / sample_rate;
    double two_pi_t = -2.0 * minus_pi_t;

    if (2 * freq - bandwidth <= sample_rate) {
        /* Adjust if upper skirt exceeds Nyquist */
        if (2 * (freq + bandwidth) > sample_rate) {
            double low = freq - bandwidth;
            freq = (sample_rate / 2.0 + low) / 2.0;
            bandwidth = freq - low;
        }

        /* Pre-warp frequency to compensate for IIR frequency shift.
         * At 16 kHz, this fixes ~7% error at F3 (2500 Hz) and
         * ~14% error at F4 (3500 Hz). Zero per-sample cost. */
        double freq_warped = (sample_rate / M_PI) * tan(M_PI * freq / sample_rate);

        double r = exp(minus_pi_t * bandwidth);
        *out_c = -(r * r);
        *out_b = r * cos(two_pi_t * freq_warped) * 2.0;
        *out_a = 1.0 - *out_b - *out_c;
    } else {
        *out_a = is_cascade ? 1.0 : 0.0;
        *out_b = 0.0;
        *out_c = 0.0;
    }
}

void set_antiresonator_coeffs(int sample_rate, double freq, double bandwidth,
                              double *out_a, double *out_b, double *out_c) {
    double a, b, c;
    set_resonator_coeffs(sample_rate, freq, bandwidth, 1, &a, &b, &c);

    if (a != 0.0) {
        double a_inv = 1.0 / a;
        *out_a = a_inv;
        *out_b = -b * a_inv;
        *out_c = -c * a_inv;
    } else {
        *out_a = 1.0;
        *out_b = 0.0;
        *out_c = 0.0;
    }
}

double db_to_linear(double dB) {
    if (dB > 0.0) {
        return 32768.0 * pow(10.0, (dB - 87.0) / 20.0 - 3.0);
    }
    return 0.0;
}
