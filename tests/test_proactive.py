from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


def test_proactive_config_defaults():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.proactive_enabled is False
    assert cfg.proactive_check_interval == 60
    assert cfg.proactive_distraction_threshold == 20
    assert cfg.proactive_checkin_interval == 120
    assert cfg.proactive_quiet_hours_start == 0
    assert cfg.proactive_quiet_hours_end == 7


def test_proactive_singleton():
    import core.proactive as pm
    pm._proactive = None
    s1 = pm.get_proactive()
    s2 = pm.get_proactive()
    assert s1 is s2
    pm._proactive = None


def test_proactive_not_running_by_default():
    import core.proactive as pm
    pm._proactive = None
    pro = pm.get_proactive()
    assert pro.is_running() is False
    assert pro.last_message_ts() is None
    assert pro.last_trigger_type() is None
    pm._proactive = None


@pytest.fixture
def pro():
    import core.proactive as pm
    pm._proactive = None
    svc = pm.get_proactive()
    yield svc
    pm._proactive = None


@pytest.mark.asyncio
async def test_start_stop(pro):
    with patch.object(pro, '_check_loop', new_callable=AsyncMock):
        await pro.start()
        assert pro.is_running() is True
        await pro.stop()
        assert pro.is_running() is False


@pytest.mark.asyncio
async def test_cloud_guard_skips(pro):
    mock_evaluate = AsyncMock(return_value=['checkin'])
    with patch('core.proactive.get_config') as mock_cfg:
        mock_cfg.return_value = MagicMock(fallback_provider='openai')
        with patch.object(pro, '_evaluate_triggers', mock_evaluate):
            await pro._run_check_once()
    mock_evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_observer_not_running_skips(pro):
    mock_obs = MagicMock(is_running=MagicMock(return_value=False))
    mock_evaluate = AsyncMock(return_value=['checkin'])
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        with patch.object(pro, '_evaluate_triggers', mock_evaluate):
            await pro._run_check_once()
    mock_evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_global_cooldown_blocks(pro):
    pro._last_message_ts = datetime.now(timezone.utc)
    mock_obs = MagicMock(is_running=MagicMock(return_value=True))
    mock_evaluate = AsyncMock(return_value=['checkin'])
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        with patch.object(pro, '_evaluate_triggers', mock_evaluate):
            await pro._run_check_once()
    mock_evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_per_trigger_cooldown_blocks(pro):
    now = datetime.now(timezone.utc)
    pro._last_fired['checkin'] = now
    mock_obs = MagicMock(is_running=MagicMock(return_value=True))
    mock_emit = AsyncMock()
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs), \
         patch.object(pro, '_evaluate_triggers', AsyncMock(return_value=['checkin'])), \
         patch.object(pro, '_generate_message', AsyncMock(return_value='hi')), \
         patch.object(pro, '_emit_message', mock_emit):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        await pro._run_check_once()
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_message_sent_updates_state(pro):
    now = datetime.now(timezone.utc)
    pro._last_message_ts = now - timedelta(seconds=400)  # past global cooldown
    mock_obs = MagicMock(is_running=MagicMock(return_value=True))
    mock_emit = AsyncMock()
    with patch('core.proactive.get_config') as mock_cfg, \
         patch('core.proactive.get_observer', return_value=mock_obs), \
         patch.object(pro, '_evaluate_triggers', AsyncMock(return_value=['checkin'])), \
         patch.object(pro, '_build_context', AsyncMock(return_value={'trigger': 'checkin', 'app': 'code', 'window': 'x', 'profile': ''})), \
         patch.object(pro, '_generate_message', AsyncMock(return_value='Time for a break!')), \
         patch.object(pro, '_emit_message', mock_emit):
        mock_cfg.return_value = MagicMock(fallback_provider='')
        await pro._run_check_once()
    mock_emit.assert_called_once()
    assert pro.last_trigger_type() == 'checkin'
    assert pro.last_message_ts() is not None


@pytest.mark.asyncio
async def test_quiet_hours_suppresses_voice(pro):
    pro._quiet_start = 0
    pro._quiet_end = 23  # essentially always quiet
    emitted = []
    async def fake_emit(type_, payload):
        emitted.append(payload)
    with patch('core.proactive.events.emit', side_effect=fake_emit):
        await pro._emit_message('hello', 'checkin')
    assert len(emitted) == 1
    assert emitted[0]['voice'] is False
    assert emitted[0]['text'] == 'hello'


@pytest.mark.asyncio
async def test_non_quiet_hours_voice_on(pro):
    pro._quiet_start = 0
    pro._quiet_end = 0  # zero-length window, never quiet
    emitted = []
    async def fake_emit(type_, payload):
        emitted.append(payload)
    with patch('core.proactive.events.emit', side_effect=fake_emit):
        await pro._emit_message('hello', 'checkin')
    assert emitted[0]['voice'] is True


@pytest.mark.asyncio
async def test_midnight_wrap_quiet_hours(pro):
    # quiet from 22:00 to 07:00
    pro._quiet_start = 22
    pro._quiet_end = 7
    emitted = []
    async def fake_emit(type_, payload):
        emitted.append(payload)
    # patch datetime.now to return hour=23 (inside quiet window)
    fake_now = MagicMock()
    fake_now.hour = 23
    with patch('core.proactive.datetime') as mock_dt, \
         patch('core.proactive.events.emit', side_effect=fake_emit):
        mock_dt.now.return_value = fake_now
        await pro._emit_message('hello', 'checkin')
    assert emitted[0]['voice'] is False


@pytest.mark.asyncio
async def test_distraction_cache_llm_called_once(pro):
    call_count = 0
    async def fake_llm(messages, **_):
        nonlocal call_count
        call_count += 1
        return {'content': 'yes'}
    with patch('agents.llm.call_llm', side_effect=fake_llm):
        await pro._classify_distraction('reddit')
        await pro._classify_distraction('reddit')
    assert call_count == 1
    assert pro._distraction_cache['reddit'] is True


@pytest.mark.asyncio
async def test_distraction_cache_non_distracting(pro):
    async def fake_llm(messages, **_):
        return {'content': 'no'}
    with patch('agents.llm.call_llm', side_effect=fake_llm):
        result = await pro._classify_distraction('code')
    assert result is False
    assert pro._distraction_cache['code'] is False


@pytest.mark.asyncio
async def test_generate_message_returns_llm_content(pro):
    async def fake_llm(messages, **_):
        return {'content': 'You have been on Reddit for 20 minutes.'}
    with patch('agents.llm.call_llm', side_effect=fake_llm):
        text = await pro._generate_message('distraction', {'trigger': 'distraction', 'app': 'reddit', 'window': 'Reddit', 'profile': ''})
    assert text == 'You have been on Reddit for 20 minutes.'


@pytest.mark.asyncio
async def test_generate_message_returns_empty_on_error(pro):
    async def fail_llm(messages, **_):
        raise RuntimeError("LLM down")
    with patch('agents.llm.call_llm', side_effect=fail_llm):
        text = await pro._generate_message('checkin', {'trigger': 'checkin', 'app': 'code', 'window': 'x', 'profile': ''})
    assert text == ''


@pytest.mark.asyncio
async def test_pipeline_enqueues_proactive_voice():
    import asyncio
    from voice.pipeline import VoicePipeline
    vp = VoicePipeline.__new__(VoicePipeline)
    vp._announcement_queue = asyncio.Queue(maxsize=50)
    await vp._on_event({'type': 'proactive_message', 'text': 'hello', 'voice': True})
    assert not vp._announcement_queue.empty()
    msg = vp._announcement_queue.get_nowait()
    assert msg == 'hello'


@pytest.mark.asyncio
async def test_pipeline_skips_proactive_when_voice_false():
    import asyncio
    from voice.pipeline import VoicePipeline
    vp = VoicePipeline.__new__(VoicePipeline)
    vp._announcement_queue = asyncio.Queue(maxsize=50)
    await vp._on_event({'type': 'proactive_message', 'text': 'hello', 'voice': False})
    assert vp._announcement_queue.empty()
