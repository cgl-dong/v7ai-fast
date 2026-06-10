from fastapi import APIRouter
from starlette.responses import RedirectResponse

router = APIRouter()


@router.get("/v7")
async def index():
    print("到达")
    return RedirectResponse(url="/static/index.html")
