"""联盟 API 凭据与全局配置加载。

使用 pydantic-settings 从环境变量 / .env 文件读取三大平台的接入凭据。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置 — 所有字段平铺在顶层，确保 .env 正确加载"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 淘宝联盟 ──
    tb_app_key: str = ""
    tb_app_secret: str = ""
    tb_adzone_id: str = ""

    # ── 京东联盟 ──
    jd_app_key: str = ""
    jd_app_secret: str = ""
    jd_site_id: str = ""

    # ── 多多进宝 ──
    pdd_client_id: str = ""
    pdd_client_secret: str = ""
    pdd_pid: str = ""


# 全局单例 — import 即可用
settings = Settings()
