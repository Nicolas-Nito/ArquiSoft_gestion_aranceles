from datetime import datetime
import json
import threading
from fastapi import FastAPI, Form, HTTPException
from pydantic import BaseModel

import time
from bson.objectid import ObjectId
import pymongo
import os
from dotenv import load_dotenv
import pika
from pika.exchange_type import ExchangeType

from ..routers.test import prefix, router
from ..rabbit.main import get_rabbitmq_connection, publish_event

load_dotenv()


rabbitmq_url = os.getenv("RABBITMQ_URL")

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["payment"]

app = FastAPI()
app.include_router(router)


    


#---------------Publish to Rabbit-----------------------------------

# Publicar un mensaje en RabbitMQ


#----------------------End Points-------------------------------
# @app.get(f"{prefix}/")
# def iniciarConsumer():
#     Consumer()
#     return {"Hello": "iniciado"}

@app.post(f"{prefix}/{{student_id}}/payments")
def store_payment(student_id: str, amount: float = Form(...), description: str = Form(...)):
    #Registrar un pago de un alumno
    payment_data = {
        "amount": amount,
        "date": time.strftime("%Y-%m-%d"),
        "description": description,
        "student_id": int(student_id)
    }

    result = db["payments"].insert_one(payment_data)
    payment_id = str(result.inserted_id)
    publish_event(f"payments.{payment_id}.created",
                {
                    "origin_service": "payments",
                    "student_id": student_id, 
                    "data": payment_data
                })
    return {"succesfull inster in id": str(result.inserted_id)}

@app.put(f"{prefix}/{{student_id}}/payments/{{payment_id}}")
def update_payment(student_id: str, payment_id: str, amount: float = Form(...), description: str = Form(...) ):
    payment_data = {
        "amount": amount,
        "date": time.strftime("%Y-%m-%d"),
        "description": description,
        "student_id": int(student_id)
    }
    db["payments"].update_one({"_id": ObjectId(payment_id)}, {"$set": payment_data})
    publish_event(f"payments.{payment_id}.updated", 
                {
                    "origin_service": "payments",
                    "student_id": student_id,
                    "data": payment_data
                })
    return {"Hello": student_id, "Payment": payment_id}

@app.delete(f"{prefix}/{{student_id}}/payments/{{payment_id}}")
def delete_payment(student_id: str, payment_id: str):
    payment_data = db["payments"].find_one({"_id": ObjectId(payment_id)})
    payment_data["_id"] = str(payment_data["_id"])
    db["deleted_payments"].insert_one(payment_data)
    db["payments"].delete_one({"_id": ObjectId(payment_id)})

    publish_event(f"payments.{payment_id}.deleted",
                {
                    "origin_service": "payments",
                    "student_id": student_id,
                    "payment_id": payment_id
                })
    return {"Hello": student_id, "Payment": payment_id}

@app.get(f"{prefix}/{{student_id}}/payments")
def get_payments(student_id: str):
    #Listar pagos de un alumno
    payments = db["payments"].find({"student_id": int(student_id)})
    payments = list(payments)
    for payment in payments:
        payment["_id"] = str(payment["_id"])
    return {"Payments": payments}

@app.get(f"{prefix}/{{student_id}}/payments/{{payment_id}}")
def get_payment(student_id: str, payment_id: str):
    #Obtener un pago de un alumno
    payment_data = db["payments"].find_one({"_id": ObjectId(payment_id)})
    if payment_data:
        payment_data["_id"] = str(payment_data["_id"])
    return {"Payment": payment_data}

@app.get(f"{prefix}/{{student_id}}/debts/{{debts_id}}/payments")
def get_debt_payments(student_id: str, payment_id: str):
    #Listar pagos pendientes de un alumno
    return {"Hello": student_id, "Payment": payment_id}
