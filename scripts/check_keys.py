"""联盟 API 连通性探测脚本。

用法:
    uv run python scripts/check_keys.py

从 .env 读取凭据，对已配置的平台发送极简测试请求，
输出终端检查清单:
  🟢 真实 API 已连通
  🟡 未配置 (Dry-run 运行中)
  🔴 鉴权失败 / 签名错误
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 确保从项目根目录加载 .env
project_root = Path(__file__).resolve().parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")


async def _check_taobao() -> tuple[str, str]:
    """探测淘宝联盟连通性"""
    app_key = os.getenv("TB_APP_KEY", "")
    app_secret = os.getenv("TB_APP_SECRET", "")
    if not app_key or not app_secret:
        return "🟡", "未配置 (Dry-run 运行中)"

    try:
        from src.engines.taobao import TaobaoEngine
        from src.engines.base import ApiBusinessError, NetworkError

        engine = TaobaoEngine()
        try:
            products = await engine.search("测试", page_size=1)
            if products:
                return "🟢", f"已连通 — 返回 {len(products)} 条结果"
            return "🟢", "已连通 — 无结果 (可能搜索词受限)"
        except ApiBusinessError as e:
            if "签名" in str(e) or "sign" in str(e).lower():
                return "🔴", f"签名错误: {e}"
            return "🔴", f"业务错误: {e}"
        except NetworkError as e:
            return "🔴", f"网络错误: {e}"
        finally:
            await engine.close()
    except Exception as e:
        return "🔴", f"异常: {e}"


async def _check_jd() -> tuple[str, str]:
    """探测京东联盟连通性"""
    app_key = os.getenv("JD_APP_KEY", "")
    app_secret = os.getenv("JD_APP_SECRET", "")
    if not app_key or not app_secret:
        return "🟡", "未配置 (Dry-run 运行中)"

    try:
        from src.engines.jd import JDEngine
        from src.engines.base import ApiBusinessError, NetworkError

        engine = JDEngine()
        try:
            products = await engine.search("测试", page_size=1)
            if products:
                return "🟢", f"已连通 — 返回 {len(products)} 条结果"
            return "🟢", "已连通 — 无结果 (可能搜索词受限)"
        except ApiBusinessError as e:
            if "签名" in str(e) or "sign" in str(e).lower():
                return "🔴", f"签名错误: {e}"
            return "🔴", f"业务错误: {e}"
        except NetworkError as e:
            return "🔴", f"网络错误: {e}"
        finally:
            await engine.close()
    except Exception as e:
        return "🔴", f"异常: {e}"


async def _check_pdd() -> tuple[str, str]:
    """探测多多进宝连通性"""
    client_id = os.getenv("PDD_CLIENT_ID", "")
    client_secret = os.getenv("PDD_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return "🟡", "未配置 (Dry-run 运行中)"

    try:
        from src.engines.pdd import PDDEngine
        from src.engines.base import ApiBusinessError, NetworkError

        engine = PDDEngine()
        try:
            products = await engine.search("测试", page_size=1)
            if products:
                return "🟢", f"已连通 — 返回 {len(products)} 条结果"
            return "🟢", "已连通 — 无结果 (可能搜索词受限)"
        except ApiBusinessError as e:
            if "签名" in str(e) or "sign" in str(e).lower():
                return "🔴", f"签名错误: {e}"
            return "🔴", f"业务错误: {e}"
        except NetworkError as e:
            return "🔴", f"网络错误: {e}"
        finally:
            await engine.close()
    except Exception as e:
        return "🔴", f"异常: {e}"


async def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║       Price Hunter — 联盟 API 连通性探测             ║")
    print("╠══════════════════════════════════════════════════════╣")
    print()

    checks = [
        ("淘宝联盟 (TOP API)", _check_taobao),
        ("京东联盟 (JD Union)", _check_jd),
        ("多多进宝 (PDD DDK)", _check_pdd),
    ]

    results = []
    for name, checker in checks:
        icon, detail = await checker()
        results.append((icon, name, detail))
        print(f"  {icon}  {name}")
        print(f"     {detail}")
        print()

    print("╠══════════════════════════════════════════════════════╣")
    green = sum(1 for r in results if r[0] == "🟢")
    yellow = sum(1 for r in results if r[0] == "🟡")
    red = sum(1 for r in results if r[0] == "🔴")
    print(f"║  汇总: 🟢 {green} 连通  🟡 {yellow} 未配置  🔴 {red} 失败    ║")
    print("╚══════════════════════════════════════════════════════╝")

    if red > 0:
        print()
        print("💡 排查建议:")
        for icon, name, detail in results:
            if icon == "🔴":
                print(f"   • {name}: {detail}")
        sys.exit(1)

    if green == 0:
        print()
        print("💡 所有平台均处于 Dry-run 模式。编辑 .env 填入联盟 API 凭据后重新运行。")
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
