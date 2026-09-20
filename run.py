#!/usr/bin/env python3
import os
import uvicorn

if __name__ == "__main__":
    reload = os.environ.get("RELOAD") == "1"
    # one worker is fine for SQLite/local; set WEB_CONCURRENCY=2+ in production (Postgres)
    # so a slow request can't block everyone else.
    workers = 1 if reload else max(1, int(os.environ.get("WEB_CONCURRENCY", "1") or "1"))
    uvicorn.run(
        "folio.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=reload,
        workers=workers,
    )
