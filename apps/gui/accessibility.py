from __future__ import annotations

import streamlit as st


def render_form_accessibility_patch() -> None:
    """Repair attributes omitted by Streamlit/BaseWeb's generated form DOM."""
    st.html(
        """
        <script>
        (() => {
          const doc = window.parent.document;
          const stateKey = "__tanghuaFormA11y";
          const state = window.parent[stateKey] || { nextId: 1, observer: null };
          window.parent[stateKey] = state;

          function repair() {
            const fields = doc.querySelectorAll("input, textarea, select");
            fields.forEach((field) => {
              if (!field.id) {
                field.id = `tanghua-field-${state.nextId++}`;
              }
              if (!field.getAttribute("name")) {
                field.setAttribute("name", field.id);
              }
              if (field.tagName === "INPUT" && !field.getAttribute("autocomplete")) {
                field.setAttribute(
                  "autocomplete",
                  field.type === "password" ? "new-password" : "off"
                );
              }
            });

            doc.querySelectorAll("label").forEach((label) => {
              if (label.htmlFor || label.querySelector("input, textarea, select")) return;
              const container = label.closest('[data-testid^="st"]') || label.parentElement;
              const field = container && container.querySelector("input, textarea, select");
              if (field) label.htmlFor = field.id;
            });
          }

          repair();
          if (state.observer) state.observer.disconnect();
          state.observer = new MutationObserver(repair);
          state.observer.observe(doc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )
