import json
from pathlib import Path

CONFIG_FILE = (
    Path.home()
    / ".yay.json"
)

DEFAULT_CONFIG = {
    "provider": "openai",
    "model": None,
    "base_url": "http://localhost:1234/v1/",
    "openai_api_key": "",
    "openrouter_api_key": "",
    "api_key": "",
}

def load_config():

    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        cfg = DEFAULT_CONFIG.copy()
        cfg.update(data)

        return cfg

    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(cfg):

    with open(
        CONFIG_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            cfg,
            f,
            indent=2,
            ensure_ascii=False,
        )
