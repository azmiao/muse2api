"""A model refusal is terminal and must not consume a second account."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

with tempfile.TemporaryDirectory() as home:
    os.environ.update(MUSE2API_HOME=home, MUSE2API_PROFILE_ROOT=home,
                      MUSE2API_KEY="test-only")
    spec = importlib.util.spec_from_file_location("refusal_rotation_candidate", ROOT / "app.py")
    app = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = app
    spec.loader.exec_module(app)
    first = app.store.add_account({"hatch_sess": "one", "hatch_vml": "one",
                                   "hatch_native_auth_device": "one"}, "one")
    app.store.add_account({"hatch_sess": "two", "hatch_vml": "two",
                           "hatch_native_auth_device": "two"}, "two")
    calls = []
    def refuse(cookies, prompt, **kwargs):
        calls.append(cookies["hatch_sess"])
        raise app.MuseModelRefusalError("模型未生成媒体，仅返回文本: 地区不可用")
    with patch.object(app, "_renew_and_persist", side_effect=lambda ident, **_: app.store.get_account(ident)), \
         patch.object(app.engine, "start"), patch.object(app.engine, "generate", side_effect=refuse), \
         patch.object(app.engine, "reset_thread"), patch.object(app.engine, "close_current_page"):
        try:
            app._run_generation_locked("video", "video", 30, account_id=first["id"],
                                       deadline=app.time.monotonic() + 30)
        except app.MuseModelRefusalError:
            pass
        else:
            raise AssertionError("refusal was not propagated")
    assert calls == ["one"], calls
print("PASS: model refusal is propagated without rotating to another account")
