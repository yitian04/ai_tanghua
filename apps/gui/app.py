from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

import streamlit as st
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from apps.gui.views import direct_curve_page, export_page, planning_page, robot_page, vector_page
from apps.gui.views import composition_page, text_trajectory_page, svg_generation_page, shop_whitebox_page
from apps.gui.asset_library import request as request_assets, show_pending
from apps.gui import workspace
from apps.gui.parameter_ui import parameter_scope,render_current_actions
from apps.gui.accessibility import render_form_accessibility_patch
from apps.gui.plot_fonts import configure_matplotlib_chinese_font


CONFIG_PATH = os.path.join(ROOT_DIR, "config", "settings.yaml")


WORKFLOW_STATE_KEYS = [
    "job_name",
    "latest_image_path",
    "vector_image_path",
    "design_prompt",
    "ai_sugar_task_id",
    "pending_navigation",
    "latest_curves_path",
    "latest_trajectory_path",
    "one_click_upload",
    "realtime_state",
    "connection_test",
    "robot_status",
    "robot_log",
    ]


def load_config() -> Dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
    except Exception:
        return {}


def clear_workflow_state() -> None:
    for key in WORKFLOW_STATE_KEYS:
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith(("text_trajectory_", "composition_")):
            st.session_state.pop(key, None)


def clear_generated_files(root_dir: str) -> int:
    deleted = 0
    for folder in ("images", "ai_generation", "curves", "trajectories", "exports", "jobs", "text_trajectories", "compositions"):
        data_dir = Path(root_dir) / "data" / folder
        if not data_dir.exists():
            continue
        for item in data_dir.rglob("*"):
            if item.is_file():
                item.unlink()
                deleted += 1
    return deleted


def apply_dense_layout() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.05rem;
            padding-bottom: 0.65rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
        }
        section[data-testid="stSidebar"] {
            width: 13.5rem !important;
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 1rem;
            padding-left: 0.75rem;
            padding-right: 0.75rem;
        }
        h1 {
            font-size: 1.25rem !important;
            line-height: 1.6 !important;
            margin-top: 0 !important;
            margin-bottom: 1rem !important;
            padding-top: 0.15rem !important;
            padding-bottom: 0.2rem !important;
            overflow: visible !important;
        }
        .app-title {
            display: flex;
            align-items: center;
            min-height: 2rem;
            font-size: 1.05rem !important;
            line-height: 1.2 !important;
            font-weight: 700;
            margin: 0 0 1rem 0;
            padding: 0.25rem 0 0.2rem 0;
            overflow: visible;
            white-space: normal;
        }
        .sidebar-title {
            display: block;
            font-size: 1rem !important;
            line-height: 1.55 !important;
            font-weight: 700;
            margin: 0 0 1rem 0;
            padding: 0.1rem 0;
            overflow: visible;
        }
        h2, h3 {
            font-size: 0.95rem !important;
            line-height: 1.25 !important;
            margin-top: 0.2rem !important;
            margin-bottom: 1rem !important;
        }
        h4 {
            font-size: 0.95rem !important;
            margin-top: 0.25rem !important;
            margin-bottom: 1rem !important;
        }
        p, label, span, div, button, input, textarea {
            font-size: 0.8rem !important;
        }
        /* Keep native Markdown margins: Streamlit compensates for their final
           1rem internally. Shrinking them makes the measured block shorter
           than its visible text and causes the next widget to overlap. */
        div[data-testid="stVerticalBlock"] {
            gap: 0.25rem !important;
        }
        div[data-testid="stHorizontalBlock"] {
            gap: 0.35rem !important;
        }
        div[data-testid="stMetric"] {
            padding: 0.25rem 0.35rem !important;
        }
        div[data-testid="stMetricValue"] {
            font-size: 0.88rem !important;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.78rem !important;
        }
        .stButton button {
            min-height: 1.75rem !important;
            padding: 0.18rem 0.45rem !important;
        }
        /* Shared asset inputs need room to wrap inside narrow control panels. */
        div[class*="st-key-asset_input_"][data-testid="stVerticalBlock"],
        div[class*="st-key-asset_input_"] div[data-testid="stVerticalBlock"] {
            gap: 0.625rem !important;
        }
        div[class*="st-key-asset_input_"] div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
            gap: 0.5rem !important;
        }
        div[class*="st-key-asset_input_"] button {
            min-height: 2.25rem !important;
            height: auto !important;
            padding: 0.4rem 0.65rem !important;
        }
        div[class*="st-key-asset_input_"] [data-testid="stMarkdownContainer"] p {
            line-height: 1.5 !important;
            overflow-wrap: anywhere;
        }
        div[class*="st-key-asset_input_"] [data-testid="stCaptionContainer"] {
            overflow-wrap: anywhere;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        textarea {
            min-height: 2rem !important;
            padding-top: 0.2rem !important;
            padding-bottom: 0.2rem !important;
        }
        div[data-testid="stSlider"] {
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }
        hr {
            margin-top: 0.45rem !important;
            margin-bottom: 0.45rem !important;
        }
        div[data-testid="stExpander"] details {
            padding-top: 0.1rem !important;
            padding-bottom: 0.1rem !important;
        }
        div[data-testid="stDataFrame"] {
            font-size: 0.78rem !important;
        }
        code {
            font-size: 0.78rem !important;
        }
        img {
            max-height: 420px;
            object-fit: contain;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="糖画机械臂控制系统",
        page_icon="TH",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    config = load_config()
    configure_matplotlib_chinese_font()

    apply_dense_layout()
    render_form_accessibility_patch()
    st.markdown('<div class="app-title">糖画机械臂控制系统</div>', unsafe_allow_html=True)
    pages = {
        "理想小店（白盒）": shop_whitebox_page.render,
        "AI糖画线稿": direct_curve_page.render,
        "图像转曲线": vector_page.render,
        "AI SVG 曲线": svg_generation_page.render,
        "轨迹规划": planning_page.render,
        "文字轨迹": text_trajectory_page.render,
        "轨迹合成": composition_page.render,
        "数字文件": export_page.render,
        "机器人控制": robot_page.render,
    }
    selected_page=workspace.enter(ROOT_DIR,pages)
    with st.sidebar:
        st.markdown('<div class="sidebar-title">模块导航</div>', unsafe_allow_html=True)
        st.radio(
            "选择工作模块",
            list(pages.keys()),
            index=0,
            key="main_navigation",
            label_visibility="collapsed",
            on_change=workspace.navigation_changed,
            disabled=bool(st.session_state.get('wf_running')),
        )
        st.divider()
        st.caption("前几个模块只生成数字文件；机器人控制页负责加载文件并执行。")
        if st.button("素材库", icon=":material/folder_open:", width="stretch"):
            request_assets(ROOT_DIR)

    notice=st.session_state.pop('wf_notice',None)
    if notice:st.info(notice)
    if st.session_state.get('wf_running'):
        st.html("<script>if(!window.__workspaceUnload){window.__workspaceUnload=e=>{e.preventDefault();e.returnValue=true;};window.addEventListener('beforeunload',window.__workspaceUnload)}</script>",unsafe_allow_javascript=True)
    with workspace.workspace_context(ROOT_DIR,selected_page),parameter_scope(ROOT_DIR,workspace.GROUPS[selected_page]):
        rerun=False
        try:
            pages[selected_page](config=config, root_dir=ROOT_DIR)
            render_current_actions()
        except FileNotFoundError:
            workspace.clear_result(workspace.current_group());st.warning('文件已删除或移动，请重新导入或生成。')
        finally:
            rerun=workspace.after_render()
        if rerun:st.rerun()
        workspace.render_controls()
        if not workspace.show_confirmation():show_pending()


if __name__ == "__main__":
    main()



