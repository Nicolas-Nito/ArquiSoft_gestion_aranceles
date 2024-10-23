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

load_dotenv()


rabbitmq_url = os.getenv("RABBITMQ_URL")

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["payment"]

app = FastAPI()
app.include_router(router)

#---------------Consumer------------------------------
# Crear una función para conectarse a RabbitMQ
def get_rabbitmq_connection():
    try:
        params = pika.URLParameters(rabbitmq_url)
        connection = pika.BlockingConnection(params)
        print("Connected to RabbitMQ")

        return connection
    except Exception as e:
        print(f"Error connecting to RabbitMQ: {e}")
        return None
    
def callback(ch, method, properties, body):
    message = json.loads(body)
    print(f" [x] Received {message}")
    origin_service = message.get('origin_service')
    # Si el mensaje es de este mismo servicio, lo ignoramos.
    if origin_service == "payments":
        print("Ignoring message from the same service")
        return
    
    event = method.routing_key
    #split the event to get the action
    _,id,action= event.split('.')

    if action == "created":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        store_payment(student_id, data["amount"], data["description"])
        print("[x] Payment created")

    elif action == "updated":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        update_payment(student_id, id, data["amount"], data["description"])
        print("[x] Payment updated")

    elif action == "deleted":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        delete_payment(student_id, id)
        print("[x] Payment deleted")

    ch.basic_ack(delivery_tag=method.delivery_tag)

def Consumer():
    # Crear una conexión con RabbitMQ para escuchar los eventos
    print("Connecting to RabbitMQ...")
    connection = get_rabbitmq_connection()
    channel = connection.channel()
    channel.exchange_declare(exchange='topic_exchange', exchange_type=ExchangeType.topic)
    queue = channel.queue_declare(queue='payments', durable=True)
    channel.queue_bind(exchange='topic_exchange', queue=queue.method.queue, routing_key='payments.*.*')
    channel.basic_consume(queue=queue.method.queue, on_message_callback=callback)
    print('Waiting for messages...')
    channel.start_consuming()

@app.on_event("startup")
def start_rabbitmq_consumer():
    consumer_thread = threading.Thread(target=Consumer, daemon=True)
    consumer_thread.start()
    print("RabbitMQ consumer thread started.")

#---------------Publish to Rabbit-----------------------------------
def json_serial(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, ObjectId):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")
# Publicar un mensaje en RabbitMQ
def publish_event(event: str, body: dict):
    
    connection = get_rabbitmq_connection()
    if connection is None:
        raise HTTPException(status_code=500, detail="Cannot connect to RabbitMQ") 
    channel = connection.channel()
    channel.exchange_declare(exchange='topic_exchange', exchange_type=ExchangeType.topic)
    # Declarar una cola llamada 'hello'

    queue_payments=channel.queue_declare(queue='payments', durable=True)
    # Enlazar la cola con el exchange
    channel.queue_bind(exchange='topic_exchange', queue=queue_payments.method.queue, routing_key='payments.*.*')
    # Publicar el evento en RabbitMQ
    channel.basic_publish(
        exchange='topic_exchange',  # O puedes usar un exchange personalizado
        routing_key=event,  # Tipo de evento como clave de enrutamiento
        body=json.dumps(body,default=json_serial,ensure_ascii=False),
        # properties=pika.BasicProperties(
        #     delivery_mode=2,  # Hacer el mensaje persistente
        # )
    )
    print(f" [x] Sent to Queue: {event}")
    connection.close()

#----------------------End Points-------------------------------
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
