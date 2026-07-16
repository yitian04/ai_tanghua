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

from apps.gui.views import direct_curve_page, design_page, export_page, one_click_page, planning_page, robot_page, vector_page


CONFIG_PATH = os.path.join(ROOT_DIR, "config", "settings.yaml")


WORKFLOW_STATE_KEYS = [
    "job_name",
    "latest_image_path",
    "design_prompt",
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


def clear_generated_files(root_dir: str) -> int:
    deleted = 0
    for folder in ("images", "curves", "trajectories", "exports", "jobs"):
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
            margin-bottom: 0.65rem !important;
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
            margin: 0 0 0.35rem 0;
            padding: 0.25rem 0 0.2rem 0;
            overflow: visible;
            white-space: normal;
        }
        .sidebar-title {
            display: block;
            font-size: 1rem !important;
            line-height: 1.55 !important;
            font-weight: 700;
            margin: 0 0 0.45rem 0;
            padding: 0.1rem 0;
            overflow: visible;
        }
        h2, h3 {
            font-size: 0.95rem !important;
            line-height: 1.25 !important;
            margin-top: 0.2rem !important;
            margin-bottom: 0.15rem !important;
        }
        h4 {
            font-size: 0.95rem !important;
            margin-top: 0.25rem !important;
            margin-bottom: 0.2rem !important;
        }
        p, label, span, div, button, input, textarea {
            font-size: 0.8rem !important;
        }
        div[data-testid="stMarkdownContainer"] p {
            margin-bottom: 0.25rem !important;
        }
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

    apply_dense_layout()
    st.markdown('<div class="app-title">糖画机械臂控制系统</div>', unsafe_allow_html=True)
    pages = {
        "一键绘制": one_click_page.render,
        "设计输入": design_page.render,
        "AI生成图片": direct_curve_page.render,
        "图像转曲线": vector_page.render,
        "轨迹规划": planning_page.render,
        "数字文件": export_page.render,
        "机器人控制": robot_page.render,
    }
    with st.sidebar:
        st.markdown('<div class="sidebar-title">模块导航</div>', unsafe_allow_html=True)
        selected_page = st.radio(
            "选择工作模块",
            list(pages.keys()),
            index=0,
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("前几个模块只生成数字文件；机器人控制页负责加载文件并执行。")
        with st.expander("历史数据"):
            if st.button("清除当前会话记录", width="stretch"):
                clear_workflow_state()
                st.rerun()

            delete_files = st.checkbox("同时清空 data 下的中间文件")
            confirm_text = st.text_input("输入 CLEAR 确认清空文件", disabled=not delete_files)
            if st.button("清空历史文件", width="stretch", disabled=not (delete_files and confirm_text == "CLEAR")):
                deleted = clear_generated_files(ROOT_DIR)
                clear_workflow_state()
                st.success(f"已删除 {deleted} 个文件")
                st.rerun()

    pages[selected_page](config=config, root_dir=ROOT_DIR)


if __name__ == "__main__":
    main()



