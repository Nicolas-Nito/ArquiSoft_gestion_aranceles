from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/test",
    tags=["test"],
)


@router.get("/")
async def test():
    return {
        "msg": "ok"
    }
