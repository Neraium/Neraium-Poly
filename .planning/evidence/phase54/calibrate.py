"""Positive control only: paired late headers and body under real HTTP deadlines."""

import asyncio

import replay

replay.DURATION = 35
app_server = replay.app_server


def wrap_server(runtime, port):
    server = app_server(runtime, port)
    if port != replay.PRODUCER_PORT:
        return server
    application = server.config.app
    count = 0

    async def delayed(scope, receive, send):
        nonlocal count
        if scope["type"] != "http" or scope["path"] != "/api/market-frame":
            return await application(scope, receive, send)
        count += 1
        target = {1: "http.response.start", 3: "http.response.body"}.get(count)
        paused = False

        async def send_delayed(message):
            nonlocal paused
            if message["type"] == target and not paused:
                paused = True
                await asyncio.sleep(3.45)
            await send(message)

        await application(scope, receive, send_delayed)

    server.config.app = delayed
    return server


replay.app_server = wrap_server

if __name__ == "__main__":
    asyncio.run(replay.main())
