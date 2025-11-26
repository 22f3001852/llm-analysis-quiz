# app/__init__.py

import sys
import asyncio

# On Windows, the default ProactorEventLoop does NOT support subprocesses.
# Playwright needs subprocess support, so we switch to the Selector event loop.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
