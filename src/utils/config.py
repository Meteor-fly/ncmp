import json
import os
import random
from typing import Any, Dict


class Config:
    def __init__(self):
        self.config_data: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if self._check_env_variables():
            return self._load_from_env()
        return self._load_from_file()

    def _check_env_variables(self) -> bool:
        required_vars = ["MUSIC_U", "CSRF"]
        return all(os.getenv(var) for var in required_vars)

    def _load_from_env(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {
            "Cookie_MUSIC_U": os.getenv("MUSIC_U"),
            "Cookie___csrf": os.getenv("CSRF"),
        }

        if notify_email := os.getenv("NOTIFY_EMAIL"):
            config["notify_email"] = notify_email
        if email_password := os.getenv("EMAIL_PASSWORD"):
            config["email_password"] = email_password
        if smtp_server := os.getenv("SMTP_SERVER"):
            config["smtp_server"] = smtp_server
        if smtp_port := os.getenv("SMTP_PORT"):
            config["smtp_port"] = int(smtp_port)
        if wait_min := os.getenv("WAIT_TIME_MIN"):
            config["wait_time_min"] = float(wait_min)
        if wait_max := os.getenv("WAIT_TIME_MAX"):
            config["wait_time_max"] = float(wait_max)
        if score := os.getenv("SCORE"):
            config["score"] = int(score)
        if full_extra_tasks := os.getenv("FULL_EXTRA_TASKS"):
            config["full_extra_tasks"] = full_extra_tasks.lower() in ("1", "true", "yes")
        if sync_yun_circle := os.getenv("SYNC_YUN_CIRCLE"):
            config["sync_yun_circle"] = sync_yun_circle.lower() in ("1", "true", "yes")

        if phone := os.getenv("NETEASE_PHONE"):
            config["netease_phone"] = phone
        if password := os.getenv("NETEASE_PASSWORD"):
            config["netease_password"] = password
        if md5_password := os.getenv("NETEASE_MD5_PASSWORD"):
            config["netease_md5_password"] = md5_password

        if gh_token := os.getenv("GH_TOKEN"):
            config["gh_token"] = gh_token
        if gh_repo := os.getenv("GH_REPO"):
            config["gh_repo"] = gh_repo

        config.setdefault("wait_time_min", 15)
        config.setdefault("wait_time_max", 20)
        config.setdefault("score", 3)
        config.setdefault("full_extra_tasks", False)
        config.setdefault("sync_yun_circle", False)

        return config

    def _load_from_file(self) -> Dict[str, Any]:
        try:
            config_path = "config/setting.json"
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"配置文件 {config_path} 不存在")

            with open(config_path, "r", encoding="utf-8") as file:
                config = json.loads(file.read())

            self._validate_config(config)
            return config
        except Exception as error:
            raise RuntimeError(f"配置加载失败: {error}")

    def _validate_config(self, config: Dict[str, Any]) -> None:
        required_keys = ["Cookie_MUSIC_U", "Cookie___csrf"]
        for key in required_keys:
            if not config.get(key):
                raise ValueError(f"配置文件中缺少必要配置项: {key}")

        config.setdefault("wait_time_min", 15)
        config.setdefault("wait_time_max", 20)
        config.setdefault("smtp_server", "smtp.gmail.com")
        config.setdefault("smtp_port", 465)
        config.setdefault("score", 3)
        config.setdefault("full_extra_tasks", False)
        config.setdefault("sync_yun_circle", False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.config_data.get(key, default)

    def get_wait_time(self) -> float:
        min_time = float(self.get("wait_time_min", 15))
        max_time = float(self.get("wait_time_max", 20))
        return random.uniform(min_time, max_time)
