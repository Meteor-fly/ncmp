import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.core.bot import MusicPartnerBot
from src.utils.config import Config
from src.utils.logger import Logger
from src.utils.notification import NotificationService
from src.validators.cookie import CookieValidator


TRIGGER_LABELS = {
    "workflow_dispatch": "手动触发",
    "schedule": "定时触发",
}

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def build_run_url() -> str:
    repository = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")

    if repository and run_id:
        return f"{server_url}/{repository}/actions/runs/{run_id}"
    return ""


def build_report(logger: Logger, status: str, summary: str) -> str:
    trigger = TRIGGER_LABELS.get(os.getenv("GITHUB_EVENT_NAME", ""), os.getenv("GITHUB_EVENT_NAME", "未知触发"))
    repository = os.getenv("GITHUB_REPOSITORY", "未知仓库")
    branch = os.getenv("GITHUB_REF_NAME", "未知分支")
    actor = os.getenv("GITHUB_ACTOR", "未知用户")
    run_number = os.getenv("GITHUB_RUN_NUMBER", "未知")
    run_url = build_run_url()

    lines = [
        "网易云音乐合伙人自动评分执行报告",
        "",
        f"执行结果：{status}",
        f"执行时间：{datetime.now(SHANGHAI_TZ).strftime('%Y-%m-%d %H:%M:%S')}",
        f"触发方式：{trigger}",
        f"仓库：{repository}",
        f"分支：{branch}",
        f"触发人：{actor}",
        f"运行编号：{run_number}",
        "",
        "执行摘要：",
        summary,
    ]

    if run_url:
        lines.extend(["", f"运行链接：{run_url}"])

    history_text = logger.get_history_text().strip()
    if history_text:
        lines.extend(["", "详细日志：", history_text])

    return "\n".join(lines)


def main():
    logger = None
    notifier = None

    try:
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)

        session = requests.Session()
        session.cookies.set("MUSIC_U", config.get("Cookie_MUSIC_U"))
        session.cookies.set("__csrf", config.get("Cookie___csrf"))

        validator = CookieValidator(session, logger)
        is_valid, message = validator.validate()

        if not is_valid:
            logger.error(message)
            notifier.send_notification(
                "网易云音乐合伙人 - Cookie失效提醒",
                build_report(logger, "Cookie 失效", f"请及时更新 Cookie。\n详细信息：{message}"),
            )
            return

        bot = MusicPartnerBot(config, logger, session)
        success = bot.run()

        end_message = "执行成功" if success else "执行失败"
        logger.end(end_message, not success)

        if success:
            notifier.send_notification(
                "网易云音乐合伙人 - 自动评分成功报告",
                build_report(
                    logger,
                    "成功",
                    "自动评分任务已完成，请查看下方详细日志了解本次评分和额外任务处理情况。",
                ),
            )
        else:
            notifier.send_notification(
                "网易云音乐合伙人 - 自动评分失败报告",
                build_report(
                    logger,
                    "失败",
                    "自动评分任务执行失败，请根据下方详细日志排查问题。",
                ),
            )

    except Exception as error:
        error_message = f"程序异常：{error}"

        if logger is not None:
            logger.error(error_message)
            logger.end("执行失败", True)

        if notifier is not None and logger is not None:
            try:
                notifier.send_notification(
                    "网易云音乐合伙人 - 异常报告",
                    build_report(logger, "异常", error_message),
                )
            except Exception as notify_error:
                logger.error(f"发送异常通知时出错：{notify_error}")
        else:
            print(error_message)


if __name__ == "__main__":
    main()
