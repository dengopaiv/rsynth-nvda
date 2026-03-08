#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "synth_state.h"
#include "resonator.h"
#include "voice_gen.h"
#include "filter_chain.h"

/* ---- Python type wrapping KlattState ---- */

typedef struct {
    PyObject_HEAD
    KlattState st;
} KlattCSynthObject;

static void klatt_reset_all_resonators(KlattState *st) {
    resonator_reset(&st->rgl);
    resonator_reset(&st->rnz);
    resonator_reset(&st->rnpc);
    resonator_reset(&st->r5c);
    resonator_reset(&st->rsc);
    resonator_reset(&st->r4c);
    resonator_reset(&st->r3c);
    resonator_reset(&st->r2c);
    resonator_reset(&st->r1c);
    resonator_reset(&st->r6p);
    resonator_reset(&st->r5p);
    resonator_reset(&st->r4p);
    resonator_reset(&st->r3p);
    resonator_reset(&st->r2p);
    resonator_reset(&st->rout);
}

/* ---- Frame setup helpers ---- */

static void setup_frame(KlattState *st) {
    int sr = st->sample_rate;
    double Gain0 = st->spk_Gain0 - 3.0;
    double a, b, c;
    double f2_adj, f3_adj;

    /* Parallel resonators */
    f2_adj = st->params[PARAM_f2] * st->spk_F2_scale + st->spk_F2_offset;
    if (f2_adj < 700) f2_adj = 700;
    if (f2_adj > 2500) f2_adj = 2500;
    set_resonator_coeffs(sr, f2_adj, st->params[PARAM_b2], 0, &a, &b, &c);
    st->r2p.a = a * db_to_linear(st->params[PARAM_a2]);
    st->r2p.b = b; st->r2p.c = c;

    f3_adj = st->params[PARAM_f3] * st->spk_F3_scale + st->spk_F3_offset;
    if (f3_adj < 1500) f3_adj = 1500;
    if (f3_adj > 3500) f3_adj = 3500;
    set_resonator_coeffs(sr, f3_adj, st->params[PARAM_b3], 0, &a, &b, &c);
    st->r3p.a = a * db_to_linear(st->params[PARAM_a3]);
    st->r3p.b = b; st->r3p.c = c;

    set_resonator_coeffs(sr, st->spk_F4hz, st->spk_B4phz, 0, &a, &b, &c);
    st->r4p.a = a * db_to_linear(st->params[PARAM_a4]);
    st->r4p.b = b; st->r4p.c = c;

    set_resonator_coeffs(sr, st->spk_F5hz, st->spk_B5phz, 0, &a, &b, &c);
    st->r5p.a = a * db_to_linear(st->params[PARAM_a5]);
    st->r5p.b = b; st->r5p.c = c;

    set_resonator_coeffs(sr, st->spk_F6hz, st->spk_B6phz, 0, &a, &b, &c);
    st->r6p.a = a * db_to_linear(st->params[PARAM_a6]);
    st->r6p.b = b; st->r6p.c = c;

    /* Amplitudes */
    st->amp_bypass = db_to_linear(st->params[PARAM_ab]);
    st->amp_asp = db_to_linear(st->params[PARAM_asp]);
    st->amp_af = db_to_linear(st->params[PARAM_af]);

    /* Output low-pass filter */
    if (Gain0 <= 0) Gain0 = 57;
    set_resonator_coeffs(sr, 0, sr / 2.0, 1, &a, &b, &c);
    st->rout.a = a * db_to_linear(Gain0);
    st->rout.b = b; st->rout.c = c;
}

static void set_cascade_resonators(KlattState *st, int interpolate) {
    int sr = st->sample_rate;
    int steps = interpolate ? st->samples_per_frame : 0;
    double a, b, c;

    /* Nasal pole (fixed) */
    set_resonator_coeffs(sr, st->spk_FNPhz, st->spk_BNhz, 1, &a, &b, &c);
    st->rnpc.a = a; st->rnpc.b = b; st->rnpc.c = c;

    /* Nasal zero */
    set_antiresonator_coeffs(sr, st->params[PARAM_fn], st->spk_BNhz, &a, &b, &c);
    st->rnz.a = a; st->rnz.b = b; st->rnz.c = c;

    /* Special 3500 Hz */
    set_resonator_coeffs(sr, 3500, 1800, 1, &a, &b, &c);
    st->rsc.a = a; st->rsc.b = b; st->rsc.c = c;

    /* F5, F4 (from speaker) */
    set_resonator_coeffs(sr, st->spk_F5hz, st->spk_B5hz, 1, &a, &b, &c);
    st->r5c.a = a; st->r5c.b = b; st->r5c.c = c;

    set_resonator_coeffs(sr, st->spk_F4hz, st->spk_B4hz, 1, &a, &b, &c);
    st->r4c.a = a; st->r4c.b = b; st->r4c.c = c;

    /* F3 with speaker offset/scale */
    {
        double f3 = st->params[PARAM_f3] * st->spk_F3_scale + st->spk_F3_offset;
        if (f3 < 1500) f3 = 1500;
        if (f3 > 3500) f3 = 3500;
        set_resonator_coeffs(sr, f3, st->params[PARAM_b3], 1, &a, &b, &c);
        if (interpolate)
            resonator_set_target(&st->r3c, a, b, c, steps);
        else {
            st->r3c.a = a; st->r3c.b = b; st->r3c.c = c;
        }
    }

    /* F2 with speaker offset/scale */
    {
        double f2 = st->params[PARAM_f2] * st->spk_F2_scale + st->spk_F2_offset;
        if (f2 < 700) f2 = 700;
        if (f2 > 2500) f2 = 2500;
        set_resonator_coeffs(sr, f2, st->params[PARAM_b2], 1, &a, &b, &c);
        if (interpolate)
            resonator_set_target(&st->r2c, a, b, c, steps);
        else {
            st->r2c.a = a; st->r2c.b = b; st->r2c.c = c;
        }
    }

    /* F1 with speaker offset/scale */
    {
        double f1 = st->params[PARAM_f1] * st->spk_F1_scale + st->spk_F1_offset;
        if (f1 < 200) f1 = 200;
        if (f1 > 1000) f1 = 1000;
        set_resonator_coeffs(sr, f1, st->params[PARAM_b1], 1, &a, &b, &c);
        if (interpolate)
            resonator_set_target(&st->r1c, a, b, c, steps);
        else {
            st->r1c.a = a; st->r1c.b = b; st->r1c.c = c;
        }
    }
}

/* ---- generate_frame ---- */

static PyObject *
KlattCSynth_generate_frame(KlattCSynthObject *self, PyObject *args) {
    double F0Hz;
    PyObject *params_list;
    KlattState *st = &self->st;
    int i;

    if (!PyArg_ParseTuple(args, "dO", &F0Hz, &params_list))
        return NULL;

    if (!PyList_Check(params_list)) {
        PyErr_SetString(PyExc_TypeError, "params must be a list");
        return NULL;
    }
    if (PyList_Size(params_list) != PARAM_COUNT) {
        PyErr_Format(PyExc_ValueError, "params must have %d elements", PARAM_COUNT);
        return NULL;
    }

    /* Copy params from Python list */
    for (i = 0; i < PARAM_COUNT; i++) {
        PyObject *item = PyList_GET_ITEM(params_list, i);
        st->params[i] = PyFloat_AsDouble(item);
        if (PyErr_Occurred()) return NULL;
    }

    /* Voicing transition detection */
    int is_voiced = st->params[PARAM_av] > 0 || st->params[PARAM_avc] > 0;
    if (!is_voiced) {
        if (st->was_voiced || !st->voiceless_started) {
            /* Reset all resonators on voiced→voiceless or cold start */
            resonator_reset(&st->rnpc);
            resonator_reset(&st->rnz);
            resonator_reset(&st->r1c);
            resonator_reset(&st->r2c);
            resonator_reset(&st->r3c);
            resonator_reset(&st->r4c);
            resonator_reset(&st->r5c);
            resonator_reset(&st->rsc);
            resonator_reset(&st->rgl);
            resonator_reset(&st->r2p);
            resonator_reset(&st->r3p);
            resonator_reset(&st->r4p);
            resonator_reset(&st->r5p);
            resonator_reset(&st->r6p);
            resonator_reset(&st->rout);
            st->noise_ramp_samples = 0;
        }
        st->voiceless_started = 1;
        st->amp_av = 0.0;
        st->amp_avc = 0.0;
        st->amp_turb = 0.0;
    } else {
        st->voiceless_started = 0;
    }
    st->was_voiced = is_voiced;

    /* Flutter */
    st->F0Hz = apply_flutter(st, F0Hz);
    setup_frame(st);
    set_cascade_resonators(st, 1);

    /* Allocate output list */
    PyObject *result = PyList_New(st->samples_per_frame);
    if (!result) return NULL;

    /* Main synthesis loop */
    for (i = 0; i < st->samples_per_frame; i++) {
        double noise = gen_noise(st);
        double voice, lpvoice;

        if (st->params[PARAM_av] > 0 || st->params[PARAM_avc] > 0) {
            voice = gen_voice(st, noise);
            lpvoice = resonator_process(&st->rgl, voice);
        } else {
            voice = 0.0;
            lpvoice = 0.0;
        }

        /* Breathiness during glottal open phase */
        if (st->nper < st->nopen) {
            voice += st->amp_turb * noise;
        }

        /* Reduce noise in glottal open phase */
        if (st->nper < st->nopen) {
            noise *= 0.5;
        }

        /* Voicing amplitude with shimmer */
        voice *= st->amp_av;
        if (st->shimmer > 0 && st->amp_av > 0) {
            double shimmer_factor = 1.0 + st->shimmer * (uniform_random(st) * 2.0 - 1.0);
            voice *= shimmer_factor;
        }

        /* Noise ramp */
        double noise_ramp;
        if (st->noise_ramp_samples < st->noise_ramp_length) {
            noise_ramp = (double)st->noise_ramp_samples / st->noise_ramp_length;
            st->noise_ramp_samples++;
        } else {
            noise_ramp = 1.0;
        }

        /* Aspiration */
        voice += st->amp_asp * noise_ramp * noise;

        /* Voice-bar */
        voice += st->amp_avc * lpvoice;

        /* Frication */
        noise *= st->amp_af * noise_ramp;

        /* Filters */
        double sample = filter_sample(st, voice, noise);

        /* Clip */
        if (sample > 32767.0) sample = 32767.0;
        if (sample < -32767.0) sample = -32767.0;

        PyList_SET_ITEM(result, i, PyFloat_FromDouble(sample));

        /* Coefficient interpolation for F1, F2, F3 */
        resonator_interpolate(&st->r1c);
        resonator_interpolate(&st->r2c);
        resonator_interpolate(&st->r3c);

        st->ns++;
    }

    return result;
}

/* ---- set_speaker ---- */

static PyObject *
KlattCSynth_set_speaker(KlattCSynthObject *self, PyObject *args) {
    KlattState *st = &self->st;

    if (!PyArg_ParseTuple(args, "ddddddddddddddddddd",
            &st->spk_F0Hz, &st->spk_Gain0,
            &st->spk_F4hz, &st->spk_B4hz,
            &st->spk_F5hz, &st->spk_B5hz,
            &st->spk_F6hz, &st->spk_B6hz,
            &st->spk_FNPhz, &st->spk_BNhz,
            &st->spk_B4phz, &st->spk_B5phz, &st->spk_B6phz,
            &st->spk_F1_offset, &st->spk_F1_scale,
            &st->spk_F2_offset, &st->spk_F2_scale,
            &st->spk_F3_offset, &st->spk_F3_scale))
        return NULL;

    Py_RETURN_NONE;
}

/* ---- set_voice_params ---- */

static PyObject *
KlattCSynth_set_voice_params(KlattCSynthObject *self, PyObject *args) {
    KlattState *st = &self->st;

    if (!PyArg_ParseTuple(args, "ddiidd",
            &st->jitter, &st->shimmer,
            &st->flutter, &st->voice_source,
            &st->smooth, &st->speed))
        return NULL;

    Py_RETURN_NONE;
}

/* ---- reset ---- */

static PyObject *
KlattCSynth_reset(KlattCSynthObject *self, PyObject *Py_UNUSED(args)) {
    KlattState *st = &self->st;

    st->nper = 0;
    st->ns = 0;
    st->flutter_t = 0;
    st->sample_pos = 0.0;
    st->was_voiced = 0;
    st->noise_ramp_samples = 0;
    st->voiceless_started = 0;
    st->dc_x1 = 0.0;
    st->dc_y1 = 0.0;

    /* Re-seed RNG */
    st->rng_s0 = 12345678901234ULL;
    st->rng_s1 = 98765432109876ULL;

    klatt_reset_all_resonators(st);

    Py_RETURN_NONE;
}

/* ---- __init__ ---- */

static int
KlattCSynth_init(KlattCSynthObject *self, PyObject *args, PyObject *kwds) {
    int sample_rate, samples_per_frame;
    PyObject *natural_samples_list;
    KlattState *st = &self->st;

    static char *kwlist[] = {"sample_rate", "samples_per_frame", "natural_samples", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "iiO", kwlist,
            &sample_rate, &samples_per_frame, &natural_samples_list))
        return -1;

    /* Zero-initialize state */
    memset(st, 0, sizeof(KlattState));

    st->sample_rate = sample_rate;
    st->samples_per_frame = samples_per_frame;

    /* Defaults */
    st->T0 = 4;
    st->noise_ramp_length = 80;
    st->smooth = 0.5;
    st->speed = 1.0;
    st->jitter = 0.015;
    st->shimmer = 0.04;
    st->flutter = 20;
    st->voice_source = VOICE_IMPULSIVE;

    /* Default speaker params */
    st->spk_F0Hz = 120.0;
    st->spk_Gain0 = 57.0;
    st->spk_F4hz = 3900.0;  st->spk_B4hz = 400.0;
    st->spk_F5hz = 4700.0;  st->spk_B5hz = 150.0;
    st->spk_F6hz = 4900.0;  st->spk_B6hz = 150.0;
    st->spk_FNPhz = 270.0;  st->spk_BNhz = 500.0;
    st->spk_B4phz = 500.0;  st->spk_B5phz = 600.0;  st->spk_B6phz = 800.0;
    st->spk_F1_scale = 1.0; st->spk_F2_scale = 1.0; st->spk_F3_scale = 1.0;

    /* RNG initial state */
    st->rng_s0 = 12345678901234ULL;
    st->rng_s1 = 98765432109876ULL;

    /* Copy natural samples */
    if (!PyList_Check(natural_samples_list)) {
        PyErr_SetString(PyExc_TypeError, "natural_samples must be a list");
        return -1;
    }
    Py_ssize_t nsamp = PyList_Size(natural_samples_list);
    if (nsamp > 100) nsamp = 100;
    st->natural_samples_len = (int)nsamp;

    for (Py_ssize_t j = 0; j < nsamp; j++) {
        st->natural_samples[j] = PyFloat_AsDouble(PyList_GET_ITEM(natural_samples_list, j));
        if (PyErr_Occurred()) return -1;
    }

    return 0;
}

/* ---- Type definition ---- */

static PyMethodDef KlattCSynth_methods[] = {
    {"generate_frame", (PyCFunction)KlattCSynth_generate_frame, METH_VARARGS,
     "Generate one frame of audio samples."},
    {"set_speaker", (PyCFunction)KlattCSynth_set_speaker, METH_VARARGS,
     "Set speaker parameters."},
    {"set_voice_params", (PyCFunction)KlattCSynth_set_voice_params, METH_VARARGS,
     "Set voice quality parameters."},
    {"reset", (PyCFunction)KlattCSynth_reset, METH_NOARGS,
     "Reset synthesizer state."},
    {NULL}
};

static PyTypeObject KlattCSynthType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_klatt_c._KlattCSynth",
    .tp_doc = "C-accelerated Klatt synthesizer",
    .tp_basicsize = sizeof(KlattCSynthObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,
    .tp_init = (initproc)KlattCSynth_init,
    .tp_methods = KlattCSynth_methods,
};

/* ---- Module definition ---- */

static PyModuleDef klatt_module = {
    PyModuleDef_HEAD_INIT,
    "_klatt_c",
    "C-accelerated Klatt formant synthesizer",
    -1,
    NULL
};

PyMODINIT_FUNC
PyInit__klatt_c(void) {
    PyObject *m;

    if (PyType_Ready(&KlattCSynthType) < 0)
        return NULL;

    m = PyModule_Create(&klatt_module);
    if (m == NULL)
        return NULL;

    Py_INCREF(&KlattCSynthType);
    if (PyModule_AddObject(m, "_KlattCSynth", (PyObject *)&KlattCSynthType) < 0) {
        Py_DECREF(&KlattCSynthType);
        Py_DECREF(m);
        return NULL;
    }

    return m;
}
