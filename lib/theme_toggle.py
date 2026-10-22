"""Botão de acesso rápido para alternar o tema do painel."""

from __future__ import annotations

import streamlit as st

_THEME_TOGGLE_HTML = """
<button id="sg-theme-toggle" type="button">
  <span class="icon" aria-hidden="true">
    <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="1.8" stroke-linecap="round">
      <circle cx="12" cy="12" r="4"></circle>
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41
               M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>
    </svg>
    <svg class="icon-moon is-hidden" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
         stroke-linejoin="round">
      <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z"></path>
    </svg>
  </span>
  <span class="label">Alternar tema</span>
</button>
"""

_THEME_TOGGLE_CSS = """
:host {
  display: block;
  color: inherit;
  font-family: inherit;
  font-size: inherit;
}

#sg-theme-toggle {
  width: 100%;
  min-height: 2.5rem;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.45rem 0.75rem;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: var(--st-button-radius, 0.5rem);
  background: rgba(148, 163, 184, 0.06);
  color: inherit;
  font-family: inherit;
  font-size: inherit;
  font-weight: 500;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: background-color 120ms ease, border-color 120ms ease;
}

#sg-theme-toggle:hover {
  background: rgba(148, 163, 184, 0.12);
  border-color: rgba(148, 163, 184, 0.45);
}

#sg-theme-toggle:focus-visible {
  outline: 2px solid var(--st-primary-color, #2dd4bf);
  outline-offset: 2px;
}

#sg-theme-toggle:disabled {
  cursor: progress;
  opacity: 0.7;
}

.icon {
  width: 1.1rem;
  height: 1.1rem;
  display: inline-flex;
  flex: 0 0 auto;
  color: var(--st-primary-color, #2dd4bf);
}

.icon svg {
  width: 100%;
  height: 100%;
  display: block;
}

.icon .is-hidden {
  display: none;
}

.label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
"""

_THEME_TOGGLE_JS = """
export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector("#sg-theme-toggle");
  if (!root) return;

  const label = root.querySelector(".label");
  const sun = root.querySelector(".icon-sun");
  const moon = root.querySelector(".icon-moon");

  const activeTheme = () => {
    const app = document.querySelector('[data-testid="stApp"]') || document.body;
    const bg = getComputedStyle(app).backgroundColor || "";
    const parts = bg.match(/[0-9.]+/g);
    if (!parts || parts.length < 3) return "light";
    const [r, g, b] = parts.slice(0, 3).map(Number);
    const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    return luminance < 0.5 ? "dark" : "light";
  };

  const sync = () => {
    const current = activeTheme();
    const target = current === "dark" ? "light" : "dark";
    const lightMode = target === "light";

    root.dataset.target = target;
    label.textContent = lightMode
      ? (data && data.light_label) || "Tema claro"
      : (data && data.dark_label) || "Tema escuro";
    root.setAttribute(
      "aria-label",
      lightMode
        ? (data && data.light_aria) || "Mudar para o tema claro"
        : (data && data.dark_aria) || "Mudar para o tema escuro"
    );
    root.title = root.getAttribute("aria-label");
    sun.classList.toggle("is-hidden", !lightMode);
    moon.classList.toggle("is-hidden", lightMode);
  };

  const closeMenu = () => {
    const menuButton = document.querySelector(
      '[data-testid="stMainMenuButton"]'
    );
    if (menuButton && menuButton.getAttribute("aria-expanded") === "true") {
      menuButton.click();
    }
  };

  const selectTheme = (target) => {
    const option = target === "light" ? "Light" : "Dark";
    const selector =
      '[data-testid="stMainMenuItem-theme-' + option + '"]';
    const existing = document.querySelector(selector);
    if (existing) {
      existing.click();
      window.setTimeout(closeMenu, 120);
      return;
    }

    const menuButton = document.querySelector(
      '[data-testid="stMainMenuButton"]'
    );
    if (!menuButton) return;

    if (menuButton.getAttribute("aria-expanded") !== "true") {
      menuButton.click();
    }

    let attempts = 0;
    const waitForOption = () => {
      const item = document.querySelector(selector);
      if (item) {
        item.click();
        window.setTimeout(closeMenu, 120);
        return;
      }
      attempts += 1;
      if (attempts < 40) window.setTimeout(waitForOption, 50);
    };
    window.setTimeout(waitForOption, 0);
  };

  sync();
  root.onclick = () => {
    const target = root.dataset.target === "light" ? "light" : "dark";
    root.disabled = true;
    selectTheme(target);
    window.setTimeout(() => {
      root.disabled = false;
      sync();
    }, 900);
  };

  return () => {
    root.onclick = null;
  };
}
"""

_THEME_TOGGLE = st.components.v2.component(
    "sg_theme_toggle",
    html=_THEME_TOGGLE_HTML,
    css=_THEME_TOGGLE_CSS,
    js=_THEME_TOGGLE_JS,
)


def theme_toggle_button(*, key: str = "sg_theme_toggle") -> None:
    """Renderiza o botão que alterna o tema sem recarregar a sessão."""
    _THEME_TOGGLE(
        key=key,
        data={
            "light_label": "Tema claro",
            "dark_label": "Tema escuro",
            "light_aria": "Mudar para o tema claro",
            "dark_aria": "Mudar para o tema escuro",
        },
    )
