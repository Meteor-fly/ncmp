import os
from typing import Dict, Optional, Tuple

from ...utils.auth import AuthService
from ...utils.github import GitHubService
from ...utils.logger import Logger
from ...utils.notification import NotificationService


class CookieRefreshTask:
    def __init__(self, logger: Logger, notifier: Optional[NotificationService] = None):
        self.logger = logger
        self.notifier = notifier
        self.auth_service = AuthService(logger)
        self.github_service = GitHubService(logger)
        
    def execute(self) -> bool:
        """执行Cookie刷新任务"""
        try:
            self.logger.info("开始执行Cookie刷新任务")
            
            # 获取登录凭据
            phone = os.environ.get("NETEASE_PHONE")
            password = os.environ.get("NETEASE_PASSWORD")
            md5_password = os.environ.get("NETEASE_MD5_PASSWORD")

            success, cookies = False, None

            # 第 1 步：优先使用现有 MUSIC_U 刷新登录态。
            # GitHub Actions 的数据中心 IP 下，密码登录会触发网易云"行为验证码"(8821)，
            # 而 /eapi/login/token/refresh 不需要重新鉴权，可以绕过该风控。
            music_u = os.environ.get("MUSIC_U")
            csrf = os.environ.get("CSRF")
            if music_u:
                self.logger.info("检测到已有 MUSIC_U，尝试通过 token/refresh 刷新登录态")
                success, cookies = self.auth_service.refresh_by_token(music_u=music_u, csrf=csrf or "")
                if success:
                    self.logger.info("通过 token/refresh 刷新登录态成功")
                else:
                    self.logger.warning("token/refresh 刷新失败")
            else:
                self.logger.warning("未提供已有 MUSIC_U，跳过 token/refresh")

            # 第 2 步：密码登录（本地/家庭网络下可用；Actions 数据中心 IP 下会被 8821 风控拦截）
            if not success:
                if not phone:
                    self.logger.warning("未设置手机号，跳过密码登录")
                elif not md5_password and not password:
                    self.logger.warning("未设置密码，跳过密码登录")
                else:
                    self.logger.info("尝试密码登录（token/refresh 失败，回退方案）")
                    # 优先使用MD5密码，如果使用明文密码，则自动转换为MD5
                    success, cookies = self.auth_service.login(
                        phone=phone,
                        password=password if not md5_password else None,
                        md5_password=md5_password
                    )

            # 第 3 步：扫码登录兜底。
            # 二维码以 ASCII 形式打印到控制台/Actions 日志，用网易云音乐 App 扫码并确认即可。
            # 可通过环境变量 QR_LOGIN=false 关闭。
            if not success:
                qr_enabled = os.environ.get("QR_LOGIN", "true").lower() in ("1", "true", "yes")
                if qr_enabled:
                    self.logger.warning("token/refresh 与密码登录均失败，尝试扫码登录兜底")
                    success, cookies = self.auth_service.login_by_qrcode(csrf=csrf or "")
                else:
                    self.logger.warning("扫码登录已被禁用（QR_LOGIN=false），跳过")

            if not success or not cookies:
                reason = "登录过程失败，请检查登录凭据是否正确"
                if not phone:
                    reason = "未设置手机号，请检查NETEASE_PHONE环境变量"
                elif not md5_password and not password:
                    reason = "未设置密码，请检查NETEASE_MD5_PASSWORD或NETEASE_PASSWORD环境变量"
                self.logger.error(f"登录失败，无法获取新的Cookie: {reason}")
                if self.notifier:
                    self.notifier.send_notification(
                        "网易云音乐合伙人 - 自动登录失败",
                        reason
                    )
                return False
                
            # 更新GitHub Secrets
            # 这里需要转换Cookie键名，使其与GitHub Actions中使用的名称匹配
            secrets_to_update = {
                "MUSIC_U": cookies.get("Cookie_MUSIC_U", ""),
                "CSRF": cookies.get("Cookie___csrf", "")
            }
            
            update_success = self.github_service.update_cookies(secrets_to_update)
            
            if update_success:
                self.logger.info("成功更新GitHub Secrets中的Cookie")
                if self.notifier:
                    self.notifier.send_notification(
                        "网易云音乐合伙人 - Cookie更新成功",
                        "已成功获取新的Cookie并更新到GitHub Secrets"
                    )
                return True
            else:
                self.logger.error("更新GitHub Secrets失败")
                if self.notifier:
                    self.notifier.send_notification(
                        "网易云音乐合伙人 - Cookie更新失败",
                        "登录成功但更新GitHub Secrets时失败"
                    )
                return False
                
        except Exception as e:
            error_message = f"Cookie刷新任务执行异常: {str(e)}"
            self.logger.error(error_message)
            
            if self.notifier:
                self.notifier.send_notification(
                    "网易云音乐合伙人 - Cookie刷新异常",
                    error_message
                )
                
            return False
