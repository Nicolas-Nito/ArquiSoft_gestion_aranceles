from fastapi import FastAPI

import pymongo
import os
from dotenv import load_dotenv

from ..routers.test import prefix, router

load_dotenv()

mongo_client = pymongo.MongoClient("mongodb://localhost:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["payment"]

app = FastAPI()
app.include_router(router)

@app.post(f"{prefix}/{{student_id}}/payments")
def store_payment(student_id: str):
    #Registrar un pago de un alumno
    return {"Hello": student_id}


@app.get(f"{prefix}/{{student_id}}/payments")
def get_payments(student_id: str):
    #Listar pagos de un alumno
    return {"Hello": student_id}

@app.get(f"{prefix}/{{student_id}}/payments/{{payment_id}}")
def get_payment(student_id: str, payment_id: str):
    #Obtener un pago de un alumno
    return {"Hello": student_id, "Payment": payment_id}


@app.get(f"{prefix}/{{student_id}}/debts/{{debts_id}}/payments")
def get_debt_payments(student_id: str, payment_id: str):
    #Listar pagos pendientes de un alumno
    return {"Hello": student_id, "Payment": payment_id}
