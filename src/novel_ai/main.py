import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from novel_ai import __version__
from novel_ai.api.router import router
from novel_ai.application.generation import GenerationConflictError
from novel_ai.application.writing import (
    WritingConflictError,
    WritingNotFoundError,
    WritingValidationError,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Novel AI",
        version=__version__,
        description="Long-form novel authoring workflow and structured memory API.",
    )
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(WritingNotFoundError)
    async def writing_not_found(_: Request, exc: WritingNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(WritingConflictError)
    @app.exception_handler(GenerationConflictError)
    async def writing_conflict(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(WritingValidationError)
    async def writing_validation(_: Request, exc: WritingValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(IntegrityError)
    async def database_conflict(_: Request, __: IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "编号或版本发生冲突"})

    @app.get("/", include_in_schema=False)
    async def writing_workspace_redirect() -> RedirectResponse:
        return RedirectResponse(url="/app/")

    app.mount(
        "/app",
        StaticFiles(packages=[("novel_ai.web", "static")], html=True),
        name="writing-workspace",
    )
    return app


app = create_app()


def run() -> None:
    uvicorn.run("novel_ai.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
