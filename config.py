"""muse2api 配置。"""
from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit, urlunsplit

_DEFAULT_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PROXY_BYPASS = "127.0.0.1,localhost,::1"
_PROXY_SCHEMES = {"http", "https", "socks4", "socks5", "socks5h"}


def _proxy_host_port(parsed) -> str:
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port else host


def _parse_proxy_url(value: str) -> tuple[str, str, str]:
    """Return a credential-free proxy URL and its optional credentials."""
    raw = str(value or "").strip()
    if not raw:
        return "", "", ""
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in _PROXY_SCHEMES:
        raise ValueError("代理协议必须是 http、https、socks4、socks5 或 socks5h")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理端口无效") from exc
    if not port or not 1 <= port <= 65535:
        raise ValueError("代理端口必须是 1-65535")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询参数或片段")
    base = urlunsplit((scheme, _proxy_host_port(parsed), "", "", ""))
    return base, unquote(parsed.username or ""), unquote(parsed.password or "")


def _proxy_url_with_auth(base: str, username: str, password: str) -> str:
    if not base:
        return ""
    parsed = urlsplit(base)
    host_port = _proxy_host_port(parsed)
    auth = ""
    if username:
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    return urlunsplit((parsed.scheme, auth + host_port, "", "", ""))


def _normalize_bypass(value: str | None) -> str:
    items = []
    for item in (value or "").replace(";", ",").split(","):
        item = item.strip()
        if item and item not in items:
            items.append(item)
    return ",".join(items) or _DEFAULT_PROXY_BYPASS


def _load_dotenv():
    """自动加载项目根目录下的 .env 文件（不覆盖已存在的系统环境变量）。"""
    base = os.environ.get("MUSE2API_HOME") or _DEFAULT_BASE_DIR
    env_path = os.path.join(base, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _detect_chromium() -> str:
    """优先使用 MUSE2API_CHROMIUM；若未设置或路径不存在，则自动探测系统已安装的 Chromium/Chrome。"""
    configured = os.environ.get("MUSE2API_CHROMIUM", "").strip()
    if configured and (os.path.isfile(configured) or shutil.which(configured)):
        return configured
    candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "chromium",
        "chromium-browser",
        "google-chrome",
        "chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if os.path.isfile(c) or shutil.which(c):
            return c
    return configured or "chromium"


@dataclass
class Config:
    base_dir: str = field(default_factory=lambda: _env("MUSE2API_HOME", _DEFAULT_BASE_DIR))
    host: str = field(default_factory=lambda: _env("MUSE2API_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("MUSE2API_PORT", "18610")))

    # 浏览器
    chromium: str = field(default_factory=_detect_chromium)
    cdp_port: int = field(default_factory=lambda: int(_env("MUSE2API_CDP_PORT", "19210")))
    home_dir: str = field(default_factory=lambda: _env("MUSE2API_HOME_DIR", os.path.expanduser("~")))
    extra_path: str = field(default_factory=lambda: _env("MUSE2API_EXTRA_PATH", "/snap/bin"))
    site_url: str = field(default_factory=lambda: _env("MUSE2API_SITE", "https://muse.ai/"))
    login_wait: int = field(default_factory=lambda: int(_env("MUSE2API_LOGIN_WAIT", "60")))

    # 浏览器 profile 根目录。
    # 踩过的坑：snap 版 chromium 受 AppArmor 约束，只能读写 $HOME 下的路径。
    # 传 --user-data-dir=/opt/... 或 /tmp/... 不会报错，但会被静默忽略，
    # 浏览器回落到 ~/snap/chromium/common/chromium。
    # 所以必须落在 $HOME 下（不要用点开头的隐藏目录，snap 的 home 接口排除隐藏文件）。
    profile_root: str = field(
        default_factory=lambda: _env("MUSE2API_PROFILE_ROOT",
                                     os.path.join(os.path.expanduser("~"),
                                                  "muse2api-profiles")))

    # 鉴权
    api_key: str = field(default_factory=lambda: _env("MUSE2API_KEY", ""))

    # 对外地址（管理页面显示「接入地址」用；留空则页面用当前域名兜底）
    public_base: str = field(
        default_factory=lambda: _env("MUSE2API_PUBLIC_BASE", ""))

    # 允许跨域调用导入接口的来源（Cookie 助手脚本从 muse.ai 页面提交时用）
    cors_origins: str = field(
        default_factory=lambda: _env("MUSE2API_CORS_ORIGINS",
                                     "https://muse.ai,https://www.muse.ai"))

    # 生成
    image_timeout: int = field(default_factory=lambda: int(_env("MUSE2API_IMAGE_TIMEOUT", "240")))
    video_timeout: int = field(default_factory=lambda: int(_env("MUSE2API_VIDEO_TIMEOUT", "600")))
    chat_timeout: int = field(default_factory=lambda: int(_env("MUSE2API_CHAT_TIMEOUT", "300")))
    max_concurrency: int = field(default_factory=lambda: max(1, int(_env("MUSE2API_CONCURRENCY", "2"))))

    # 工具调用（function calling）协议适配开关，**默认关闭**。
    # 实测 muse.ai 的助手会明确拒绝输出"伪工具调用"（原话：「我不会按这种 JSON
    # 格式输出'伪工具调用'」），强行注入协议反而会污染正常回答。
    # 所以默认只做「参数兼容」（客户端传 tools 不会 422），不注入、不解析。
    # 若目标模型行为有变，可设 MUSE2API_TOOL_PROTOCOL=1 打开这层适配再试。
    tool_protocol: bool = field(
        default_factory=lambda: _env("MUSE2API_TOOL_PROTOCOL", "0").strip() != "0")

    # 保活设置：是否对已禁用的账号执行自动保活，**默认关闭**。
    # 开启后，被管理员在后台手动禁用的账号仍会由后台守护进程执行自动保活与 VM 唤醒，
    # 保持会话活性不失效，但依然不会参与正常业务生图、生视频与对话轮转调度。
    keepalive_disabled_accounts: bool = field(
        default_factory=lambda: _env("MUSE2API_KEEPALIVE_DISABLED_ACCOUNTS", "0").strip() != "0")

    _proxy_lock: threading.RLock = field(default_factory=threading.RLock,
                                         init=False, repr=False)
    _proxy_state: dict | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self.apply_proxy_environment()

    @property
    def data_dir(self) -> str:
        return os.path.join(self.base_dir, "data")

    @property
    def media_dir(self) -> str:
        return os.path.join(self.data_dir, "media")

    @property
    def download_dir(self) -> str:
        return os.path.join(self.data_dir, "downloads")

    @property
    def profile_dir(self) -> str:
        """生成用浏览器 profile。"""
        return os.path.join(self.profile_root, "generate")

    @property
    def accounts_file(self) -> str:
        return os.path.join(self.data_dir, "accounts.json")

    @property
    def tasks_file(self) -> str:
        return os.path.join(self.data_dir, "tasks.json")

    @property
    def proxy_file(self) -> str:
        return os.path.join(self.data_dir, "proxy.json")

    def _env_proxy_state(self) -> dict:
        """兼容已有 HTTP_PROXY/HTTPS_PROXY 环境变量。"""
        raw = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
               os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or
               os.environ.get("ALL_PROXY") or os.environ.get("all_proxy") or "")
        try:
            url, username, password = _parse_proxy_url(raw)
        except ValueError:
            url, username, password = "", "", ""
        return {
            "enabled": bool(url),
            "url": url,
            "username": username,
            "password": password,
            "bypass": _normalize_bypass(os.environ.get("NO_PROXY") or
                                         os.environ.get("no_proxy")),
        }

    def _read_proxy_state(self) -> dict:
        if not os.path.isfile(self.proxy_file):
            return self._env_proxy_state()
        try:
            with open(self.proxy_file, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("代理配置必须是 JSON 对象")
            url, embedded_user, embedded_password = _parse_proxy_url(raw.get("url", ""))
            username = str(raw.get("username", "") or embedded_user)
            password = str(raw.get("password", "") or embedded_password)
            return {
                "enabled": bool(raw.get("enabled", False)) and bool(url),
                "url": url,
                "username": username,
                "password": password,
                "bypass": _normalize_bypass(raw.get("bypass")),
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # 配置损坏时不要阻止服务启动，回退到环境变量配置。
            return self._env_proxy_state()

    def proxy_settings(self) -> dict:
        with self._proxy_lock:
            if self._proxy_state is None:
                self._proxy_state = self._read_proxy_state()
            return dict(self._proxy_state)

    def public_proxy_settings(self) -> dict:
        settings = self.proxy_settings()
        return {
            "enabled": settings["enabled"],
            "url": settings["url"],
            "username": settings["username"],
            "username_configured": bool(settings["username"]),
            "password_configured": bool(settings["password"]),
            "bypass": settings["bypass"],
        }

    def update_proxy(self, *, enabled: bool, url: str = "", username: str = "",
                     password: str = "", bypass: str = "",
                     clear_password: bool = False) -> dict:
        old = self.proxy_settings()
        normalized_url, embedded_user, embedded_password = _parse_proxy_url(url)
        username = str(username or embedded_user).strip()
        if clear_password:
            password = ""
        elif not password:
            password = embedded_password or old["password"]
        if not username:
            password = ""
        if enabled and not normalized_url:
            raise ValueError("启用代理时必须填写代理地址")
        state = {
            "enabled": bool(enabled) and bool(normalized_url),
            "url": normalized_url,
            "username": username,
            "password": str(password),
            "bypass": _normalize_bypass(bypass),
        }
        self.ensure_dirs()
        temp_file = self.proxy_file + ".tmp"
        with self._proxy_lock:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.write("\\n")
            try:
                os.chmod(temp_file, 0o600)
            except OSError:
                pass
            os.replace(temp_file, self.proxy_file)
            self._proxy_state = state
            self._apply_proxy_environment(state)
        return dict(state)

    def _apply_proxy_environment(self, settings: dict):
        proxy = ""
        if settings.get("enabled"):
            proxy = _proxy_url_with_auth(settings.get("url", ""),
                                         settings.get("username", ""),
                                         settings.get("password", ""))
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ[key] = proxy
            os.environ[key.lower()] = proxy
        bypass = _normalize_bypass(settings.get("bypass"))
        os.environ["NO_PROXY"] = bypass
        os.environ["no_proxy"] = bypass

    def apply_proxy_environment(self):
        """将代理配置应用到 requests、urllib 和 websocket-client 的环境变量。"""
        with self._proxy_lock:
            if self._proxy_state is None:
                self._proxy_state = self._read_proxy_state()
            self._apply_proxy_environment(self._proxy_state)

    def chromium_proxy_args(self) -> list[str]:
        settings = self.proxy_settings()
        if not settings["enabled"] or not settings["url"]:
            return []
        parsed = urlsplit(settings["url"])
        scheme = "socks5" if parsed.scheme == "socks5h" else parsed.scheme
        proxy_url = urlunsplit((scheme, parsed.netloc, "", "", ""))
        args = [f"--proxy-server={proxy_url}"]
        bypass = settings["bypass"].replace(",", ";")
        if bypass:
            args.append(f"--proxy-bypass-list={bypass}")
        return args

    def ensure_dirs(self):
        for d in (self.base_dir, self.data_dir, self.media_dir, self.download_dir,
                  self.profile_dir):
            os.makedirs(d, exist_ok=True)


CFG = Config()
