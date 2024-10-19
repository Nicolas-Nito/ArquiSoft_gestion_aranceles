from fastapi import FastAPI
from dotenv import load_dotenv

from .routers import test
import logging

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test.router)

logging.basicConfig(level=logging.INFO)

load_dotenv()
