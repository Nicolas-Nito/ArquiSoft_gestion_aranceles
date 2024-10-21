from fastapi import APIRouter, HTTPException

prefix = "/api/v1"

router = APIRouter(
    prefix=prefix,
    tags=["api"],
)