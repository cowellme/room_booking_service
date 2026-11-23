from fastapi import HTTPException, Request


async def read_limited(request: Request, limit: int, message: str) -> bytes:
    """Read a request body without trusting Content-Length alone."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, message)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, message)
        chunks.append(chunk)
    return b"".join(chunks)
