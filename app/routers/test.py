from fastapi import APIRouter, HTTPException

prefix = "/api/v1"

router = APIRouter(
    prefix=prefix,
    tags=["api"],
)


@router.get("/")
async def test():
    return {
        "msg": "ok"
    }
