"""联盟 API 凭据与全局配置加载。

使用 pydantic-settings 从环境变量 / .env 文件读取三大平台的接入凭据。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class TaobaoConfig(BaseSettings):
    """淘宝联盟 (Taobao客 TOP API) 配置"""

    model_config = SettingsConfigDict(env_prefix="TB_")

    app_key: str = ""
    app_secret: str = ""
    adzone_id: str = ""


class JDConfig(BaseSettings):
    """京东联盟 (JD Union Open Platform) 配置"""

    model_config = SettingsConfigDict(env_prefix="JD_")

    app_key: str = ""
    app_secret: str = ""
    site_id: str = ""


class PDDConfig(BaseSettings):
    """多多进宝 (PDD Open Platform) 配置"""

    model_config = SettingsConfigDict(env_prefix="PDD_")

    client_id: str = ""
    client_secret: str = ""
    pid: str = ""


class Settings(BaseSettings):
    """全局配置聚合"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    taobao: TaobaoConfig = TaobaoConfig()
    jd: JDConfig = JDConfig()
    pdd: PDDConfig = PDDConfig()


# 全局单例 — import 即可用
settings = Settings()
