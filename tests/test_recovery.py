"""Regression tests for durable delivery, not just successful polling."""
import json
import pytest
from vfkit.core import CompetingWatcher

from test_core import FakeAPI, FakeWaker, ev, make, conditions_watcher, Routed


def test_gap_wakes_even_without_retained_events(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [], 'cursor': 'e_20', 'gap': True}))
    w.step()
    assert 'reconcile' in w.waker.prompts[0]


def test_post_wake_completion_is_delivered(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI(
        {'events': [ev('trade.offered')], 'cursor': 'e_2'},
        {'events': [ev('plan.completed', plan_id='pl_new')], 'cursor': 'e_3'}))
    w.step()
    w.step()
    assert len(w.waker.prompts) == 2
    assert 'pl_new' in w.waker.prompts[1]


def test_failed_decision_is_reconciled_after_probe_recovers(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [ev('plan.completed')], 'cursor': 'e_2'}),
                   waker=FakeWaker((False, 'exit 1', 'unavailable')))
    w.step()
    w.step()
    assert len(w.waker.prompts) == 2
    assert 'reconcile' in w.waker.prompts[1]


def test_startup_does_not_drop_backlog(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [ev('plan.completed')], 'cursor': 'e_2'}))
    del w.state['cursor']
    w.step()
    assert 'plan.completed' in w.waker.prompts[0]


def test_old_hold_does_not_drop_completion(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [ev('agent.held'), ev('plan.completed')], 'cursor': 'e_2'}))
    w.step()
    assert 'plan.completed' in w.waker.prompts[0]


def test_pending_decision_survives_restart(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [ev('plan.completed')], 'cursor': 'e_2'}), min_wake_gap_s=600)
    w.step()
    restored, _, clock = make(tmp_path, FakeAPI(), min_wake_gap_s=600)
    clock.t += 601
    restored.step()
    assert 'plan.completed' in restored.waker.prompts[0]


def test_condition_fired_during_wake_is_delivered(tmp_path):
    api = Routed(batches=[{'events': [ev('trade.offered')], 'cursor': 'e_2'},
                          {'events': [ev('skill.level_up', 'info', skill='mining', level=40)], 'cursor': 'e_3'}])
    w, _, _ = conditions_watcher(tmp_path, api, 'mining>=40')
    w.step()
    w.step()
    assert 'your condition fired: mining>=40' in w.waker.prompts[1]
    assert api.polls()[1]['min_importance'] == 'info'


def test_corrupt_state_shape_recovers(tmp_path):
    (tmp_path / 'watcher-state.json').write_text('[]')
    w, _, _ = make(tmp_path, FakeAPI())
    assert isinstance(w.state, dict)


def test_failed_condition_delivery_remains_pending(tmp_path):
    w, _, _ = conditions_watcher(tmp_path, Routed(), 't>=500', status=lambda: {'tick': 600},
                                 waker=FakeWaker((False, 'exit 1', 'unavailable')))
    w.step()
    w.step()
    assert 'your condition fired: t>=500' in w.waker.prompts[1]


def test_urgent_attack_bypasses_minimum_gap(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [ev('combat.attacked', 'urgent')], 'cursor': 'e_2'}), min_wake_gap_s=600)
    w.step()
    assert 'combat.attacked' in w.waker.prompts[0]


def test_replaced_poller_stops_without_acknowledging_cursor(tmp_path):
    w, _, _ = make(tmp_path, FakeAPI({'events': [], 'cursor': 'e_20', 'replaced': True}))
    with pytest.raises(CompetingWatcher):
        w.run_once()
    assert w.state['cursor'] == 'e_1'
    assert w.state['pending']


def test_capped_challenge_survives_restart_and_is_delivered(tmp_path):
    w, _, clock = make(tmp_path, FakeAPI({'events': [ev('challenge.issued', 'urgent', challenge={'id':'ch_1'})], 'cursor': 'e_2'}))
    w.policy.challenges = [clock()] * 5
    w.step()
    assert not w.waker.prompts
    restored, _, later = make(tmp_path, FakeAPI())
    assert len(restored.policy.challenges) == 5
    later.t += 3601
    restored.step()
    assert 'challenge.issued' in restored.waker.prompts[0]


def test_feature_change_is_flagged_without_rule_version_change(tmp_path):
    (tmp_path / 'intents.md').write_text('rules_version `abc`')
    w, _, _ = make(tmp_path, FakeAPI())
    w.state['features'] = ['old']
    w.status = lambda: {'rules_version':'abc', 'features':['old','new']}
    w.check_rules()
    assert (tmp_path / 'reference-stale.flag').exists()


def test_failed_rebuild_cannot_make_active_reference_look_current(tmp_path):
    (tmp_path / 'intents.md').write_text('rules_version `abc`')
    (tmp_path / 'CLAUDE.md').write_text('rules_version `old`')
    (tmp_path / 'reference-stale.flag').write_text('abc')
    w, _, _ = make(tmp_path, FakeAPI())
    w.check_rules()
    assert (tmp_path / 'reference-stale.flag').exists()
