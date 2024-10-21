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

load_dotenv()


rabbitmq_url = os.getenv("RABBITMQ_URL")

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["payment"]

app = FastAPI()
app.include_router(router)
# Crear una función para conectarse a RabbitMQ
def get_rabbitmq_connection():
    try:
        params = pika.URLParameters(rabbitmq_url)
        connection = pika.BlockingConnection(params)
       
        return connection
    except Exception as e:
        print(f"Error connecting to RabbitMQ: {e}")
        return None

# Publicar un mensaje en RabbitMQ
def publish_event(event: str, body: dict):
    
    connection = get_rabbitmq_connection()
    if connection is None:
        raise HTTPException(status_code=500, detail="Cannot connect to RabbitMQ") 
    channel = connection.channel()
    channel.exchange_declare(exchange='topic_exchange', exchange_type=ExchangeType.topic)
    # Declarar una cola llamada 'hello'
    queue_benefits=channel.queue_declare(queue='benefits', durable=True)
    queue_payments=channel.queue_declare(queue='payments', durable=True)

    # Enlazar la cola con el exchange
    channel.queue_bind(exchange='topic_exchange', queue=queue_benefits.method.queue, routing_key='benefits.*.*')
    channel.queue_bind(exchange='topic_exchange', queue=queue_payments.method.queue, routing_key='payments.*.*')
    # Publicar el evento en RabbitMQ
    channel.basic_publish(
        exchange='topic_exchange',  # O puedes usar un exchange personalizado
        routing_key=event,  # Tipo de evento como clave de enrutamiento
        body=str(body),
        properties=pika.BasicProperties(
            delivery_mode=2,  # Hacer el mensaje persistente
        )
    )
    print(f" [x] Sent to Queue: {event}")
    connection.close()

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
    return {"Hello": student_id, "Payment": payment_id}

@app.delete(f"{prefix}/{{student_id}}/payments/{{payment_id}}")
def delete_payment(student_id: str, payment_id: str):
    payment_data = db["payments"].find_one({"_id": ObjectId(payment_id)})
    payment_data["_id"] = str(payment_data["_id"])
    db["deleted_payments"].insert_one(payment_data)
    db["payments"].delete_one({"_id": ObjectId(payment_id)})

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
