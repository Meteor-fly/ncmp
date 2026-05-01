import base64
import codecs
import json
import random
import re
import string
import time
from typing import Tuple

import requests
from Crypto.Cipher import AES

from ..utils.config import Config
from ..utils.logger import Logger


MELODY_COMMENTS = [
    "旋律线条流畅，整体走向自然，听感很舒服。",
    "旋律记忆点比较明确，段落推进也比较顺耳。",
    "主旋律完成度不错，情绪表达比较连贯。",
    "旋律起伏处理得比较稳，整体氛围拿捏得可以。",
]

VOCAL_COMMENTS = [
    "演唱状态在线，情绪进入得比较快。",
    "声音辨识度不错，咬字和气息都比较自然。",
    "演唱表达比较真诚，情感传递是成立的。",
    "人声和旋律的贴合度不错，整体完成度较好。",
]

LYRIC_COMMENTS = [
    "歌词表达比较完整，画面感和情绪点都能接住。",
    "词意比较顺，句子之间的衔接也比较自然。",
    "歌词内容有一定记忆点，主题表达比较清晰。",
    "文字和情绪方向一致，整体听下来比较顺畅。",
]

OVERALL_COMMENTS = [
    "整体完成度不错，继续保持这个方向会更有辨识度。",
    "整体听感自然，作品已经具备比较稳定的表达。",
    "综合表现在线，细节再打磨一下会更亮眼。",
    "整体质感不错，已经能把作品的核心情绪传达出来。",
]

ENDING_COMMENTS = [
    "继续加油，期待你后续带来更多好作品。",
    "保持现在的创作状态，后续作品值得期待。",
    "整体方向是对的，继续积累会越来越成熟。",
    "已经有不错的完成度了，继续坚持创作。",
]


class Signer:
    def __init__(self, session: requests.Session, task_id: str, logger: Logger, config: Config):
        self.session = session
        self.task_id = task_id
        self.logger = logger
        self.config = config
        self.sign_url = "https://interface.music.163.com/weapi/music/partner/work/evaluate"

        self.random_str = self._generate_random_string(16)
        self.pub_key = "010001"
        self.modulus = (
            "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
            "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
            "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
            "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
        )
        self.iv = "0102030405060708"
        self.aes_key = "0CoJUm6Qyw8W8jud"

        self.name_pattern = re.compile(r".*[a-zA-Z].*")

    def _generate_random_string(self, length: int) -> str:
        return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

    def _add_to_16(self, text: str) -> bytes:
        pad = 16 - len(text) % 16
        text = text + chr(pad) * pad
        return text.encode("utf-8")

    def _aes_encrypt(self, text: str, key: str) -> str:
        encryptor = AES.new(key.encode("utf-8"), AES.MODE_CBC, self.iv.encode("utf-8"))
        encrypt_text = encryptor.encrypt(self._add_to_16(text))
        return base64.b64encode(encrypt_text).decode("utf-8")

    def _get_params(self, data: dict) -> str:
        text = json.dumps(data, ensure_ascii=False)
        params = self._aes_encrypt(text, self.aes_key)
        params = self._aes_encrypt(params, self.random_str)
        return params

    def _get_enc_sec_key(self) -> str:
        text = self.random_str[::-1]
        rs = int(codecs.encode(text.encode("utf-8"), "hex_codec"), 16)
        rs = pow(rs, int(self.pub_key, 16), int(self.modulus, 16))
        return format(rs, "x").zfill(256)

    def _get_score_and_tag(self, work: dict) -> Tuple[str, str]:
        score_strategy = int(self.config.get("score", 3))
        has_english = bool(self.name_pattern.match(work["name"] + work["authorName"]))

        if score_strategy == 1:
            score = "2" if has_english else "1"
        elif score_strategy == 2:
            score = "3" if has_english else "2"
        elif score_strategy == 3:
            score = "4" if has_english else "3"
        else:
            score = "4"

        return score, f"{score}-A-1"

    def _build_comment(self, work: dict) -> str:
        lines = [
            f"作品：《{work['name']}》",
            f"作者：{work['authorName']}",
            f"旋律：{random.choice(MELODY_COMMENTS)}",
            f"演唱：{random.choice(VOCAL_COMMENTS)}",
            f"歌词：{random.choice(LYRIC_COMMENTS)}",
            f"整体：{random.choice(OVERALL_COMMENTS)}",
            random.choice(ENDING_COMMENTS),
        ]
        return "\n".join(lines)

    def _should_sync_to_yun_circle(self) -> str:
        return "true" if self.config.get("sync_yun_circle", False) else "false"

    def sign(self, work: dict, is_extra: bool = False) -> None:
        try:
            delay = self.config.get_wait_time()
            self.logger.info(f"等待 {delay:.1f} 秒后继续...")
            time.sleep(delay)

            csrf = str(self.session.cookies["__csrf"])
            score, tag = self._get_score_and_tag(work)
            comment = self._build_comment(work)
            sync_yun_circle = self._should_sync_to_yun_circle()

            data = {
                "taskId": self.task_id,
                "workId": work["id"],
                "score": score,
                "tags": tag,
                "customTags": "%5B%5D",
                "comment": comment,
                "syncYunCircle": sync_yun_circle,
                "csrf_token": csrf,
            }

            if is_extra:
                data["extraResource"] = "true"

            params = {
                "params": self._get_params(data),
                "encSecKey": self._get_enc_sec_key(),
            }

            self.logger.debug(f"评分请求数据: {data}")

            response = self.session.post(
                url=f"{self.sign_url}?csrf_token={csrf}",
                data=params,
            ).json()

            self.logger.debug(f"评分响应数据: {response}")

            if response["code"] == 200:
                self.logger.info(f'{work["name"]}「{work["authorName"]}」评分完成：{score}分')
                self.logger.info(f"本次乐评内容如下：\n{comment}")
                self.logger.info(f"同步到云圈：{'是' if sync_yun_circle == 'true' else '否'}")
            else:
                error_msg = response.get("message") or response.get("msg", "未知错误")
                if "频繁" in error_msg:
                    retry_delay = self.config.get_wait_time()
                    self.logger.info(f"遇到频率限制，等待 {retry_delay:.1f} 秒后重试...")
                    time.sleep(retry_delay)
                    self.sign(work, is_extra)
                elif response["code"] == 405 and "资源状态异常" in error_msg:
                    self.logger.warning(f'歌曲「{work["name"]}」资源状态异常，跳过')
                else:
                    raise RuntimeError(f"评分失败: {error_msg} (响应码: {response.get('code')})")
        except Exception as error:
            self.logger.error(f'歌曲「{work["name"]}」评分异常：{error}')
            raise RuntimeError(f"评分过程出错: {error}")
