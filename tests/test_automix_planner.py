"""Calage de l'AutoMix iPhone : où commencer, sur quel temps entrer, à quelle vitesse jouer le
suivant, quelle courbe de fondu. Teste `tests/automix_reference.py`, copie fidèle de
`MixPlanner.swift` (le projet iOS n'a pas de cible de tests : voir le module de référence)."""

from __future__ import annotations

import math
import random

import pytest

from tests import automix_reference as m

# Mesure d'un titre à 128 BPM : 4 temps de 0,46875 s.
BAR_128 = 4 * 60 / 128


def track(bpm=128.0, downbeat=0.3, out_downbeat=None, **kw) -> m.Analysis:
    return m.Analysis(
        start=kw.pop("start", 0.5), mix_out=kw.pop("mix_out", 180.0), end=kw.pop("end", 198.0), bpm=bpm,
        beat_offset=downbeat, downbeat=downbeat, tempo_confidence=0.8, key=kw.pop("key", "8A"), key_confidence=0.7,
        out_downbeat=out_downbeat if out_downbeat is not None else downbeat + 90 * 4 * 60 / bpm,
        downbeat_confidence=kw.pop("downbeat_confidence", 0.7), **kw,
    )


def inputs(a, b, position=150.0, **kw) -> m.MixInputs:
    return m.MixInputs(a_end=a.end, a_base=max(a.mix_out, a.end - 16), position=position, a=a, b=b, **kw)


def on_grid(value: float, origin: float, step: float, tolerance=1e-6) -> bool:
    k = (value - origin) / step
    return abs(k - round(k)) * step < tolerance


# -- briques ---------------------------------------------------------------------------------

def test_first_boundary():
    assert m.first_boundary(10.0, 0.3, 1.875) == pytest.approx(0.3 + 6 * 1.875)  # 11,55
    assert m.first_boundary(0.3, 0.3, 1.875) == pytest.approx(0.3)  # déjà sur le temps
    assert m.first_boundary(-1.0, 0.3, 1.875) == pytest.approx(0.3)


@pytest.mark.parametrize("a,b", [(128, 128), (128, 124), (128, 135), (70, 140), (140, 70)])
def test_tempo_ratio_one_beat_double_half(a, b):
    ratio = m.tempo_ratio(a, b, m.TEMPO_TOLERANCE)
    assert ratio is not None and abs(ratio - 1) <= m.TEMPO_TOLERANCE
    # Le tempo de B ainsi calé tombe sur celui de A, à un facteur 1, 2 ou 1/2 près.
    assert min(abs(b * ratio / a - f) for f in (1, 2, 0.5)) < 1e-9


def test_tempo_ratio_is_bounded_to_six_percent():
    assert m.tempo_ratio(128, 128 * 1.07, 0.06) is None
    assert m.tempo_ratio(128, 128 * 1.059, 0.06) is not None
    assert m.tempo_ratio(100, 128, 0.06) is None
    assert m.tempo_ratio(0, 128, 0.06) is None


def test_equal_power_never_dips():
    for step in range(101):
        a, b = m.equal_power(step / 100)
        assert a * a + b * b == pytest.approx(1.0)
    assert m.equal_power(-1) == (1.0, 0.0)
    assert m.equal_power(2)[0] == pytest.approx(0.0, abs=1e-12)


def test_key_match_camelot():
    assert m.key_match("8A", "8A") == "same"
    assert m.key_match("8A", "8B") == "relative"
    assert m.key_match("8A", "9A") == "adjacent"
    assert m.key_match("12A", "1A") == "adjacent"
    assert m.key_match("8A", "3B") == "clash"
    assert m.key_match(None, "8A") == "unknown"


# -- calage : deux titres proches ------------------------------------------------------------

def test_aligned_plan_starts_on_a_bar_and_enters_b_on_a_bar():
    a, b = track(128, 0.3), track(124, 0.6, start=0.9)
    plan = m.plan(inputs(a, b))
    assert plan.aligned and plan.style == "blend"
    assert plan.rate == pytest.approx(128 / 124)
    # A part d'un premier temps de mesure (de la grille de sa fin), B entre sur le sien.
    assert on_grid(plan.a_start, a.out_downbeat, BAR_128)
    assert on_grid(plan.b_start, b.downbeat, 4 * 60 / 124)
    assert plan.b_start >= b.start - 0.15
    # La durée est un nombre entier de mesures, et le fondu finit avec A.
    assert on_grid(plan.length, 0.0, BAR_128)
    assert plan.a_start + plan.length <= a.end + 0.4
    assert plan.a_start >= 150.0 + 0.8 - 0.05


def test_aligned_beats_fall_together():
    """Après le calage, chaque temps de B (joué à `rate`) tombe sur un temps de A."""
    a, b = track(128, 0.3), track(124, 0.6)
    plan = m.plan(inputs(a, b))
    period_a, period_b = 60 / a.bpm, 60 / b.bpm
    for n in range(0, 17):
        a_time = plan.a_start + n * period_b / plan.rate  # n-ième temps de B, en temps de A
        assert on_grid(a_time, a.out_downbeat, period_a)


def test_half_and_double_tempo_still_lock():
    a, b = track(140, 0.2), track(70, 0.4)
    plan = m.plan(inputs(a, b))
    assert plan.aligned and plan.rate == pytest.approx(1.0)
    assert on_grid(plan.a_start, a.out_downbeat, 4 * 60 / 140)


def test_too_far_tempos_fall_back_to_a_plain_fade():
    plan = m.plan(inputs(track(128), track(100)))
    assert not plan.aligned and plan.style == "plain" and plan.rate == 1.0 and not plan.bass_swap
    assert plan.length <= 12


def test_harmonic_blend_is_longer_than_a_clash():
    a = track(128, key="8A")
    harmonic = m.plan(inputs(a, track(128, key="9A")))
    clash = m.plan(inputs(a, track(128, key="3B")))
    assert harmonic.length > clash.length
    assert harmonic.bass_swap and not clash.bass_swap
    assert clash.length <= 6.01


def test_untrusted_downbeat_keeps_the_blend_short():
    sure = m.plan(inputs(track(128), track(128)))
    unsure = m.plan(inputs(track(128, downbeat_confidence=0.1), track(128)))
    assert sure.length > 8 and unsure.length <= 8.01
    assert unsure.aligned  # les temps restent calés : seules les phrases sont incertaines


def test_effects_off_means_no_bass_swap():
    assert not m.plan(inputs(track(128), track(128), effects=False)).bass_swap


# -- repli -----------------------------------------------------------------------------------

def test_without_analysis_a_simple_fade_before_the_end():
    plan = m.plan(m.MixInputs(a_end=200.0, a_base=192.0, position=150.0))
    assert plan.style == "plain" and plan.rate == 1.0 and not plan.aligned
    assert plan.b_start == 0.0
    assert plan.a_start >= 150.8 and plan.a_start + plan.length <= 200.0 + 0.4
    assert plan.length == pytest.approx(8.0)


def test_album_break_lengthens_a_plain_fade():
    base = m.MixInputs(a_end=200.0, a_base=180.0, position=150.0)
    assert m.plan(base).length == pytest.approx(8.0)
    base.album_break = True
    assert m.plan(base).length == pytest.approx(12.0)


def test_fixed_length_from_the_settings_is_kept():
    a, b = track(128), track(128)
    plan = m.plan(inputs(a, b, fixed_length=6.0))
    assert plan.length == pytest.approx(6.0)
    assert on_grid(plan.a_start, a.out_downbeat, BAR_128)
    plain = m.plan(m.MixInputs(a_end=200.0, a_base=190.0, position=150.0, fixed_length=10.0))  # base = fin - durée
    assert plain.length == pytest.approx(10.0)


def test_force_plain_ignores_the_grids_but_keeps_b_entry():
    a, b = track(128), track(128, 0.6)
    aligned, late = m.plan(inputs(a, b)), m.plan(inputs(a, b, force_plain=True, lead=1.6))
    assert aligned.aligned and not late.aligned and late.rate == 1.0
    # Même entrée pour B : le repli ne la fait pas refaire (le lecteur la garde en tampon).
    assert late.b_start == aligned.b_start


def test_late_start_shrinks_the_fade_instead_of_overrunning():
    a, b = track(128), track(128)
    plan = m.plan(inputs(a, b, position=194.0, force_plain=True, lead=1.6))
    assert plan.a_start >= 194.0 + 1.6 - 0.05
    assert plan.a_start + plan.length <= a.end + 0.5 or plan.length == 1.5


def test_b_with_a_far_grid_keeps_its_real_start():
    # Mesure de 4 s (60 BPM) dont le premier temps tombe à plus de 6 s du début du son.
    far = track(60, 0.0, start=0.5)
    far.downbeat = far.beat_offset = 0.5 + 3.0 + 4.0 - 4.0 + 3.3  # -> premier temps de mesure à ~6,8 s
    plan = m.plan(inputs(track(60), far))
    assert plan.b_start <= far.start + 6.0 + 1e-9


# -- fondu : jamais de creux -----------------------------------------------------------------

def test_a_stays_at_full_volume_until_b_really_plays():
    plan = m.plan(inputs(track(128), track(128)))
    # B ne joue pas encore (réseau) alors que A a dépassé son point de départ : A reste plein.
    t = m.fade_progress(plan.a_start + 3.0, plan.b_start, plan, plan.a_start, b_running=False)
    assert t == 0.0 and m.frame(plan, t).volume_a == pytest.approx(1.0)


def test_late_b_slows_the_fade_instead_of_leaving_a_hole():
    plan = m.plan(inputs(track(128), track(128)))
    # B est parti 1 s trop tard : le fondu suit B, A reste plus fort que si on suivait sa propre horloge.
    t = m.fade_progress(plan.a_start + 4.0, plan.b_start + 3.0, plan, plan.a_start, b_running=True)
    assert t == pytest.approx(3.0 / plan.length)
    assert t < 4.0 / plan.length
    f = m.frame(plan, t)
    assert f.volume_a ** 2 + f.volume_b ** 2 == pytest.approx(1.0)


def test_power_is_constant_over_the_whole_fade_for_any_plan():
    for plan in (m.plan(inputs(track(128), track(126))), m.plan(inputs(track(128), track(90)))):
        for i in range(201):
            f = m.frame(plan, i / 200)
            assert f.volume_a ** 2 + f.volume_b ** 2 == pytest.approx(1.0)


def test_bass_swap_filters_are_continuous():
    plan = m.plan(inputs(track(128), track(128)))
    assert plan.bass_swap
    previous = m.frame(plan, 0.0)
    for i in range(1, 1001):
        f = m.frame(plan, i / 1000)
        # Les fréquences de coupure glissent (pas de saut d'une octave en 1 ‰ du fondu) ; en dessous
        # de 25 Hz le filtre n'agit plus (inaudible) : l'entrée et la sortie à 25 Hz ne comptent pas.
        for before, after in ((previous.highpass_a, f.highpass_a), (previous.highpass_b, f.highpass_b)):
            if min(before, after) > 25.0 and not (0.499 <= i / 1000 <= 0.501):
                assert abs(after - before) <= 15.0
        previous = f
    assert m.frame(plan, 1.0).highpass_b == 0.0


# -- propriétés ------------------------------------------------------------------------------

def test_invariants_on_random_inputs():
    rng = random.Random(7)
    for _ in range(3000):
        bpm_a, bpm_b = rng.uniform(70, 180), rng.uniform(70, 180)
        if rng.random() < 0.4:
            bpm_b = bpm_a * rng.uniform(0.9, 1.1)
        end = rng.uniform(40, 400)
        a = track(bpm_a, rng.uniform(0, 3), start=rng.uniform(0, 5), mix_out=end - rng.uniform(3, 40), end=end,
                  key=rng.choice(["8A", "9A", "3B", "8B"]), downbeat_confidence=rng.random())
        a.out_downbeat = rng.uniform(end - 60, end - 10) if rng.random() < 0.8 else None
        b = track(bpm_b, rng.uniform(0, 3), start=rng.uniform(0, 15))
        position = rng.uniform(0, end - 1)
        i = m.MixInputs(
            a_end=end, a_base=max(a.mix_out, end - 16), position=position, a=a if rng.random() < 0.9 else None,
            b=b if rng.random() < 0.9 else None, fixed_length=rng.choice([None, None, 4.0, 8.0, 12.0]),
            album_break=rng.random() < 0.5, force_plain=rng.random() < 0.2, lead=rng.choice([0.8, 1.6, 3.0]),
        )
        p = m.plan(i)
        assert p.length >= 1.0 and p.a_start >= 0 and p.b_start >= 0
        assert not math.isnan(p.a_start + p.b_start + p.length)
        if p.aligned:
            assert p.style == "blend"
            assert abs(p.rate - 1) <= m.TEMPO_TOLERANCE + 1e-9  # jamais plus de 6 % de déformation
        else:
            assert p.rate == 1.0 and not p.bass_swap and p.style == "plain"
        if end - (position + i.lead) >= 3.0 and i.fixed_length is None:
            # Le fondu ne commence pas avant `position + lead` (à un petit écart près) et finit avec A.
            assert p.a_start >= position + i.lead - 0.06
            assert p.a_start + p.length <= end + 0.5
