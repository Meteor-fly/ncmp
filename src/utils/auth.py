import hashlib
from typing import Callable, Dict, Tuple, Optional
from ..utils.logger import Logger

try:
    from pyncm.apis.login import (
        LoginViaCellphone,
        LoginRefreshToken,
        LoginQrcodeUnikey,
        LoginQrcodeCheck,
    )
    from pyncm import GetCurrentSession, DumpSessionAsString, SetNewSession
    PYNCM_AVAILABLE = True
except ImportError:
    PYNCM_AVAILABLE = False


class AuthService:
    def __init__(self, logger: Logger):
        self.logger = logger
        
        if not PYNCM_AVAILABLE:
            self.logger.error("pyncm 库未安装，无法使用登录功能")
            raise ImportError("pyncm 库未安装，请执行 pip install pyncm")
    
    def _hash_password(self, password: str) -> str:
        """将明文密码转换为 MD5 哈希"""
        return hashlib.md5(password.encode()).hexdigest()

    @staticmethod
    def _collect_cookie(session, name: str) -> list:
        """安全读取 session 中某名称的所有 Cookie 值。

        requests 的 RequestsCookieJar 在存在同名但 domain/path 不同的 Cookie 时，
        直接 `session.cookies.get(name)` 会抛 'There are multiple cookies with name'
        异常，这里通过遍历绕开该问题。
        """
        return [c.value for c in session.cookies if c.name == name]

    def refresh_by_token(self, music_u: str, csrf: str = "") -> Tuple[bool, Optional[Dict[str, str]]]:
        """
        通过已有的 MUSIC_U 刷新登录态（/eapi/login/token/refresh）。

        这是网页端"刷新登录令牌"接口，不需要重新输入密码，
        因此不会触发网易云"需要行为验证码"（错误码 8821）风控，
        适合在 GitHub Actions 这类数据中心 IP 环境下使用。
        """
        try:
            self.logger.info("尝试使用现有 MUSIC_U 刷新登录态（token/refresh）")

            # 使用全新会话，避免带上之前登录残留的状态
            SetNewSession()
            session = GetCurrentSession()
            session.cookies.set("MUSIC_U", music_u, domain="music.163.com", path="/")
            if csrf:
                session.cookies.set("__csrf", csrf, domain="music.163.com", path="/")

            result = LoginRefreshToken()

            # 刷新失败，例如登录态已过期（返回 301）或触发风控
            if result.get("code") != 200:
                error_msg = result.get("message", "未知错误")
                self.logger.error(f"刷新登录态失败，错误码: {result.get('code')}，错误信息: {error_msg}")
                return False, None

            # 服务端 Set-Cookie 会写入新的 MUSIC_U，与预置的旧值并存（同名不同域），
            # 直接 session.cookies.get("MUSIC_U") 会抛 'multiple cookies' 异常。
            # 这里取与旧值不同的新值；若服务端未更新 Cookie，则回退 result['token']。
            music_u_values = self._collect_cookie(session, "MUSIC_U")
            new_music_u = next((v for v in music_u_values if v != music_u), None)
            if new_music_u is None and result.get("token"):
                new_music_u = result["token"]
            if new_music_u is None:
                new_music_u = music_u_values[0] if music_u_values else None

            if not new_music_u:
                self.logger.error("刷新登录态成功但未能获取到新的 MUSIC_U")
                self.logger.debug(f"刷新接口返回: {result}")
                return False, None

            # 同样安全地读取新的 __csrf，优先取与旧值不同的新值
            csrf_values = self._collect_cookie(session, "__csrf")
            csrf_cookie = next((v for v in csrf_values if v != csrf), None) or csrf

            cookie_dict = {
                "Cookie_MUSIC_U": new_music_u,
                "Cookie___csrf": csrf_cookie,
            }

            self.logger.info("登录态刷新成功，已获取新的Cookie")
            return True, cookie_dict

        except Exception as e:
            self.logger.error(f"pyncm 刷新登录态过程发生异常: {str(e)}")
            return False, None

    def login_by_qrcode(self, timeout: int = 180, csrf: str = "", notify_qr: Optional[Callable[[str, str], None]] = None) -> Tuple[bool, Optional[Dict[str, str]]]:
        """
        通过扫码登录（手动兜底）。

        当 token/refresh 与密码登录都失败时使用：生成二维码并以 ASCII 形式打印到
        控制台/Actions 日志，用户用网易云音乐 App 扫码并确认后，轮询登录状态获取 Cookie。
        二维码也会以可扫描 URL 的形式记录在日志里，打开浏览器扫码同样有效。

        notify_qr: 可选回调，二维码生成后调用，参数为 (扫码地址, ASCII二维码文本)，
                   用于把二维码推送到邮箱等渠道，方便在手机上直接扫码，无需打开 GitHub。
        """
        try:
            import io
            import time

            self.logger.info("尝试使用扫码登录（请在网易云音乐 App 中扫码确认）")

            SetNewSession()
            session = GetCurrentSession()

            unikey_resp = LoginQrcodeUnikey()
            unikey = unikey_resp.get("unikey")
            if not unikey:
                self.logger.error(f"获取二维码失败: {unikey_resp}")
                return False, None

            scan_url = f"https://music.163.com/login?codekey={unikey}"
            self.logger.info(f"扫码地址: {scan_url}")

            # 以 ASCII 二维码打印到控制台/Actions 日志，并可选推送到邮箱
            ascii_qr = ""
            try:
                import qrcode
                qr = qrcode.QRCode(border=1)
                qr.add_data(scan_url)
                qr.make(fit=True)
                buf = io.StringIO()
                qr.print_ascii(out=buf)
                ascii_qr = buf.getvalue()
                print(ascii_qr, end="")
            except ImportError:
                self.logger.warning("未安装 qrcode 库，无法打印二维码图片，请使用上方扫码地址")
            except Exception as e:
                self.logger.debug(f"二维码打印失败（不影响扫码地址）: {str(e)}")

            if notify_qr:
                try:
                    notify_qr(scan_url, ascii_qr)
                except Exception as e:
                    self.logger.debug(f"推送二维码通知失败: {str(e)}")

            # 轮询扫码状态：801=等待扫码，802=待确认，803=扫码成功，800=二维码过期
            elapsed = 0
            interval = 3
            while elapsed < timeout:
                result = LoginQrcodeCheck(unikey)
                code = result.get("code")
                if code == 803:
                    self.logger.info("扫码登录成功")
                    break
                elif code == 800:
                    self.logger.error("二维码已过期，请重新运行任务")
                    return False, None
                elif code in (801, 802):
                    self.logger.debug(f"等待用户扫码/确认中 (code={code})")
                else:
                    self.logger.debug(f"扫码状态未知: {result}")
                time.sleep(interval)
                elapsed += interval
            else:
                self.logger.error("等待扫码超时，未完成登录")
                return False, None

            # 提取登录后的 Cookie（使用安全读取，避免同名 Cookie 冲突）
            music_u_values = self._collect_cookie(session, "MUSIC_U")
            new_music_u = music_u_values[0] if music_u_values else None
            if not new_music_u:
                self.logger.error("扫码登录成功但未能获取到 MUSIC_U")
                self.logger.debug(f"会话中的所有 cookies: {dict(session.cookies)}")
                return False, None

            csrf_values = self._collect_cookie(session, "__csrf")
            csrf_cookie = csrf_values[0] if csrf_values else csrf
            cookie_dict = {
                "Cookie_MUSIC_U": new_music_u,
                "Cookie___csrf": csrf_cookie,
            }

            self.logger.info("扫码登录成功，已获取新的Cookie")
            return True, cookie_dict

        except Exception as e:
            self.logger.error(f"pyncm 扫码登录过程发生异常: {str(e)}")
            return False, None

    def login(self, phone: str, password: str = None, md5_password: str = None) -> Tuple[bool, Optional[Dict[str, str]]]:
        """
        通过手机号和密码登录获取 Cookie
        
        Args:
            phone: 手机号
            password: 明文密码（与md5_password二选一）
            md5_password: MD5加密后的密码（与password二选一）
            
        Returns:
            (成功状态, Cookie字典)
        """
        try:
            self.logger.info(f"尝试使用 pyncm 登录账号: {phone[:3]}****{phone[-4:]}")

            # 使用全新会话，避免沿用之前失败尝试留下的 Cookie，防止同名冲突
            SetNewSession()
            
            # 确定使用哪种密码
            if md5_password:
                password_hash = md5_password
                self.logger.debug("使用提供的MD5密码登录")
            elif password:
                password_hash = self._hash_password(password)
                self.logger.debug("使用明文密码（转换为MD5）登录")
            else:
                self.logger.error("未提供密码，无法登录")
                return False, None
            
            # 使用 pyncm 登录
            self.logger.info(f"正在调用 pyncm 登录接口...")
            result = LoginViaCellphone(phone, passwordHash=password_hash, ctcode=86)

            # 检查登录结果
            self.logger.info(f"登录接口返回: {result}")
            if result.get("code") != 200:
                error_msg = result.get("message", "未知错误")
                self.logger.error(f"登录失败，错误码: {result.get('code')}，错误信息: {error_msg}")
                return False, None
            
            # 获取当前会话
            session = GetCurrentSession()

            # 从会话的 cookies 中获取（使用安全读取，避免同名 Cookie 冲突）
            music_u_values = self._collect_cookie(session, "MUSIC_U")
            music_u_cookie = music_u_values[0] if music_u_values else None
            csrf_values = self._collect_cookie(session, "__csrf")
            csrf_cookie = csrf_values[0] if csrf_values else None

            self.logger.info(f"从会话中获取的 cookies - MUSIC_U: {'存在' if music_u_cookie else '不存在'}, __csrf: {'存在' if csrf_cookie else '不存在'}")

            if not music_u_cookie:
                self.logger.error("未能从会话中获取 MUSIC_U cookie")
                self.logger.debug(f"会话中的所有 cookies: {dict(session.cookies)}")
                return False, None

            if not csrf_cookie:
                self.logger.error("未能从会话中获取 __csrf cookie")
                self.logger.debug(f"会话中的所有 cookies: {dict(session.cookies)}")
                return False, None
            
            # 构建返回的 Cookie 字典
            cookie_dict = {
                "Cookie_MUSIC_U": music_u_cookie,
                "Cookie___csrf": csrf_cookie
            }
            
            self.logger.info("登录成功并获取Cookie")
            self.logger.debug(f"成功获取MUSIC_U: {music_u_cookie[:10]}... 和 __csrf: {csrf_cookie}")
            
            # 记录会话信息（可选，用于调试）
            session_string = DumpSessionAsString(session)
            self.logger.debug(f"会话信息: {session_string[:50]}...")
            
            return True, cookie_dict
            
        except Exception as e:
            self.logger.error(f"pyncm 登录过程发生异常: {str(e)}")
            return False, None
