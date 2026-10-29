import os
import time
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


def wait_until_run_time():
    """等待到指定北京时间再开始评分。

    GitHub Actions 的 schedule 任务存在短至几分钟、长至数小时的不确定延迟，
    cron 只能决定“最晚在哪个时刻前开始排队”，无法保证准点。因此 workflow 提前触发，
    由这里精确控制实际评分的时刻（默认北京时间 19:00）。
    """
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return  # 手动触发的任务不等待

    target_env = os.getenv("TARGET_RUN_TIME", "19:00")
    try:
        target_hour, target_minute = (int(part) for part in target_env.split(":"))
    except ValueError:
        print(f"[wait] TARGET_RUN_TIME 格式无效: {target_env!r}，跳过等待")
        return

    now = datetime.now(SHANGHAI_TZ)
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    wait_seconds = (target - now).total_seconds()

    # 排队太久（已超过目标时刻）时不再等待，直接执行；等待过长无意义。
    if wait_seconds <= 0:
        print(f"[wait] 当前已是 {now:%H:%M:%S}，已过目标时刻 {target_env}，直接开始执行")
        return
    if wait_seconds > 6 * 3600:
        print(f"[wait] 需等待 {wait_seconds / 3600:.1f} 小时，超过 6 小时上限，直接开始执行")
        return

    print(f"[wait] 当前 {now:%H:%M:%S}，等待至北京时间 {target_env}（还需 {wait_seconds / 60:.0f} 分钟）")
    time.sleep(wait_seconds)
    print(f"[wait] 到达目标时刻 {target_env}，开始执行")


def _qr_login_enabled() -> bool:
    return os.getenv("QR_LOGIN", "true").lower() in ("1", "true", "yes")


def _apply_recovered_cookies(config: Config, logger: Logger, session: requests.Session, cookies: dict) -> bool:
    """把恢复得到的新 Cookie 写入当前会话，并尽量回写 GitHub Secrets。"""
    music_u = cookies.get("Cookie_MUSIC_U")
    if not music_u:
        return False
    csrf = cookies.get("Cookie___csrf") or config.get("Cookie___csrf") or ""

    session.cookies.set("MUSIC_U", music_u)
    session.cookies.set("__csrf", csrf)

    gh_token = os.getenv("GH_TOKEN") or config.get("gh_token")
    gh_repo = os.getenv("GH_REPO") or config.get("gh_repo")
    if not gh_token or not gh_repo:
        logger.warning("未配置 GH_TOKEN / GH_REPO，无法自动更新 Secrets，请手动更新 MUSIC_U 和 CSRF")
        return True

    os.environ.setdefault("GH_TOKEN", gh_token)
    os.environ.setdefault("GH_REPO", gh_repo)
    try:
        from src.utils.github import GitHubService

        if GitHubService(logger).update_cookies({"MUSIC_U": music_u, "CSRF": csrf}):
            logger.info("已自动更新 GitHub Secrets 中的 MUSIC_U / CSRF")
        else:
            logger.warning("更新 GitHub Secrets 失败，请手动更新 MUSIC_U 和 CSRF")
    except Exception as error:
        logger.warning(f"更新 GitHub Secrets 失败: {error}")
    return True


def try_recover_cookie(config: Config, logger: Logger, notifier: NotificationService, session: requests.Session) -> bool:
    """Cookie 失效时先尝试刷新登录态，再尝试扫码登录；成功则更新会话并返回 True。"""
    if not _qr_login_enabled():
        logger.warning("扫码登录已被禁用（QR_LOGIN=false），跳过自动恢复")
        return False

    try:
        from src.utils.auth import AuthService
    except Exception as error:
        logger.warning(f"扫码登录依赖不可用（pyncm 未安装），跳过自动恢复: {error}")
        return False

    auth_service = AuthService(logger)
    music_u = config.get("Cookie_MUSIC_U") or ""
    csrf = config.get("Cookie___csrf") or ""

    # 第一步：刷新登录态，多数情况下不需要人工扫码
    if music_u:
        success, cookies = auth_service.refresh_by_token(music_u=music_u, csrf=csrf)
        if success and cookies and _apply_recovered_cookies(config, logger, session, cookies):
            is_valid, _ = CookieValidator(session, logger).validate()
            if is_valid:
                logger.info("通过 token/refresh 恢复 Cookie 成功")
                return True
            logger.warning("token/refresh 返回的新 Cookie 仍然无效，继续尝试扫码登录")

    # 第二步：扫码登录，二维码推送到邮箱（未配置邮箱时只打印在日志里）
    def notify_qr(scan_url: str, ascii_qr: str) -> None:
        qr_text = ascii_qr or "（当前环境未安装 qrcode 库，无法渲染二维码图片）"
        notifier.send_notification(
            "网易云音乐合伙人 - Cookie失效，请扫码登录",
            "自动评分开始前检测到 MUSIC_U 已失效，已自动发起扫码登录。\n\n"
            f"扫码地址（也可在手机浏览器打开后跳转 App 确认）：\n{scan_url}\n\n"
            f"请在网易云音乐 App 中扫码并确认，二维码约 3 分钟内有效：\n\n{qr_text}",
        )

    success, cookies = auth_service.login_by_qrcode(csrf=csrf, notify_qr=notify_qr)
    if not success or not cookies:
        logger.error("扫码登录未完成（未扫码或二维码已过期）")
        return False

    if not _apply_recovered_cookies(config, logger, session, cookies):
        return False

    is_valid, _ = CookieValidator(session, logger).validate()
    if is_valid:
        logger.info("通过扫码登录恢复 Cookie 成功")
        return True
    logger.warning("扫码登录成功，但新 Cookie 校验未通过")
    return False


def main():
    logger = None
    notifier = None

    try:
        wait_until_run_time()
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
            if not try_recover_cookie(config, logger, notifier, session):
                notifier.send_notification(
                    "网易云音乐合伙人 - Cookie失效提醒",
                    build_report(
                        logger,
                        "Cookie 失效",
                        "请及时更新 Cookie。\n"
                        "已自动尝试刷新登录态和扫码登录，均未成功（未扫码或二维码已过期）。\n"
                        f"详细信息：{message}",
                    ),
                )
                return
            logger.info("Cookie 已自动恢复，继续执行评分任务")

        task_mode = os.getenv("TASK_MODE", "") or "auto"
        run_extra = True
        # if task_mode == "auto":
        #     # 自动模式：每周日执行完整任务（含额外任务），其余日期仅执行基础任务
        #     is_sunday = datetime.now(SHANGHAI_TZ).weekday() == 6
        #     run_extra = is_sunday
        # else:
        #     run_extra = task_mode == "full"

        bot = MusicPartnerBot(config, logger, session)
        success = bot.run(run_extra=run_extra)

        end_message = "执行成功" if success else "执行失败"
        logger.end(end_message, not success)

        mode_label = "基础任务" if not run_extra else "完整任务（含额外任务）"
        if success:
            notifier.send_notification(
                "网易云音乐合伙人 - 自动评分成功报告",
                build_report(
                    logger,
                    "成功",
                    f"本次执行模式：{mode_label}\n自动评分任务已完成，请查看下方详细日志了解执行情况。",
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
