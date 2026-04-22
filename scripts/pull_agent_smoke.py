import asyncio
import logging
import sys

from app.pull_agent.agent import handle_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    text = " ".join(sys.argv[1:]) or "请拉Linux操作系统和GaussDB的运维经理"
    result = await handle_message(text)
    print("\n=== RESULT ===")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
