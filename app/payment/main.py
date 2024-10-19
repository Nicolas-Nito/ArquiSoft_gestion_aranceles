from fastapi import FastAPI

from ..routers.test import prefix, router

app = FastAPI()
app.include_router(router)

@app.get(f"{prefix}/hello")
def read_root():
    return {"Hello": "World"}