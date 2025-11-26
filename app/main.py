from json import JSONDecodeError
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .quiz_solver import solve_quiz_chain


app = FastAPI(title=settings.app_name)


@app.post("/quiz")
async def quiz_endpoint(request: Request) -> JSONResponse:
    """
    Main endpoint that the evaluation server will call.

    Expected JSON payload:
    {
      "email": "your email",
      "secret": "your secret",
      "url": "https://example.com/quiz-834",
      ... possibly other fields
    }

    Behaviour:
    - 400: invalid JSON or missing required fields
    - 403: invalid secret
    - 200: secret matches; we attempt to solve the quiz chain.
    """
    try:
        body: Dict[str, Any] = await request.json()
    except JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON payload."},
        )
    except Exception:
        # Any other error while reading body is treated as bad request
        return JSONResponse(
            status_code=400,
            content={"error": "Unable to read JSON payload."},
        )

    email = body.get("email")
    secret = body.get("secret")
    url = body.get("url")

    # Basic field validation
    if not isinstance(email, str) or not isinstance(secret, str) or not isinstance(
        url, str
    ):
        return JSONResponse(
            status_code=400,
            content={
                "error": "JSON must contain 'email', 'secret', and 'url' as strings."
            },
        )

    # Check secret
    if secret != settings.expected_secret:
        return JSONResponse(
            status_code=403,
            content={"error": "Invalid secret."},
        )

    # Now we know the secret matches. According to spec, we must return 200.
    # We also run the quiz solver. If it fails, we still return 200, but with an 'error' field.
    try:
        result = await solve_quiz_chain(email=email, secret=secret, start_url=url)
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "solver_result": result,
            },
        )
    except Exception as e:
        # We don't want to crash. Return status 200 but error info.
        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "message": "Exception during quiz solving.",
                "detail": repr(e),
            },
        )
