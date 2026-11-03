"""One renderer for generated, uploaded and remotely supplied trajectory data."""
import hashlib
from pathlib import Path

import streamlit as st

from src.core.trajectory_playback import build_playback


@st.cache_data(show_spinner=False, max_entries=32)
def _playback(trajectory):
    return build_playback(trajectory)


@st.cache_resource
def _component(js):
    import streamlit.components.v2 as components
    version = hashlib.sha256(js.encode()).hexdigest()[:12]
    return components.component('trajectory_player_' + version, js=js)


def render_trajectory_player(trajectory, key):
    try:
        data = _playback(trajectory)
        data['instance'] = str(key)
        script = (Path(__file__).parent / 'components' / 'trajectory_player.js').read_text(encoding='utf-8')
        _component(script)(key='trajectory_player_' + str(key), data=data, height='content')
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        st.warning(f'无法模拟此轨迹：{exc}')
