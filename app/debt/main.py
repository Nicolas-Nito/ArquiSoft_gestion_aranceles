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


rabbitmq_url = os.getenv("RABBITMQ_URL")

load_dotenv()

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["debt"]

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
    if origin_service == "debts":
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
        store_debt(student_id, data["amount"], data["description"])
        print("[x] Debt created")

    elif action == "updated":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        update_debt(student_id, id, data["amount"], data["description"], data["paid"])
        print("[x] Debt updated")

    elif action == "deleted":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        delete_debt(student_id, id)
        print("[x] Debt deleted")

    ch.basic_ack(delivery_tag=method.delivery_tag)

def Consumer():
    # Crear una conexión con RabbitMQ para escuchar los eventos
    print("Connecting to RabbitMQ...")
    connection = get_rabbitmq_connection()
    channel = connection.channel()
    channel.exchange_declare(exchange='topic_exchange', exchange_type=ExchangeType.topic)
    queue = channel.queue_declare(queue='debts', durable=True)
    channel.queue_bind(exchange='topic_exchange', queue=queue.method.queue, routing_key='debts.*.*')
    channel.basic_consume(queue=queue.method.queue, on_message_callback=callback)
    print('Waiting for messages...')
    channel.start_consuming()

@app.on_event("startup")
def start_rabbitmq_consumer():
    consumer_thread = threading.Thread(target=Consumer, daemon=True)
    consumer_thread.start()
    #Consumer()
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
    queue_debts=channel.queue_declare(queue='debts', durable=True)
    queue_payments=channel.queue_declare(queue='payments', durable=True)

    # Enlazar la cola con el exchange
    channel.queue_bind(exchange='topic_exchange', queue=queue_debts.method.queue, routing_key='debts.*.*')
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
@app.post(f"{prefix}/{{student_id}}/debts")
def store_debt(student_id: str, amount: float = Form(...), description: str = Form(...)):
    #Registrar un pago de un alumno
    debt_data = {
        "amount": amount,
        "date": time.strftime("%Y-%m-%d"),
        "description": description,
        "paid": False,
        "student_id": int(student_id)
    }

    result = db["debts"].insert_one(debt_data)
    debt_id = str(result.inserted_id)
    publish_event(f"debts.{debt_id}.created",
                {
                    "origin_service": "debts",
                    "student_id": student_id,
                    "data":debt_data
                })

    return {"succesfull inster in id": str(result.inserted_id)}

@app.put(f"{prefix}/{{student_id}}/debts/{{debt_id}}")
def update_debt(student_id: str, debt_id: str, amount: float = Form(...), description: str = Form(...), paid: bool = Form(...)  ):
    debt_data = {
        "amount": amount,
        "date": time.strftime("%Y-%m-%d"),
        "description": description,
        "student_id": int(student_id),
        "paid": paid
    }
    db["debts"].update_one({"_id": ObjectId(debt_id)}, {"$set": debt_data})
    publish_event(f"debts.{debt_id}.updated",
                {
                    "origin_service": "debts",
                    "student_id": student_id,
                    "data": debt_data
                })
    return {"Hello": student_id, "Debt": debt_id}

@app.delete(f"{prefix}/{{student_id}}/debts/{{debt_id}}")
def delete_debt(student_id: str, debt_id: str):
    debt_data = db["debts"].find_one({"_id": ObjectId(debt_id)})
    debt_data["_id"] = str(debt_data["_id"])
    db["deleted_debts"].insert_one(debt_data)
    db["debts"].delete_one({"_id": ObjectId(debt_id)})

    publish_event(f"debts.{debt_id}.deleted",
                {
                    "origin_service": "debts",
                    "student_id": student_id,
                    "debt_id": debt_id
                })
    return {"Hello": student_id, "Debt": debt_id}

@app.get(f"{prefix}/{{student_id}}/debts/{{debt_id}}")
def get_debt(student_id: str, debt_id: str):
    debt = db["debts"].find_one({"_id": ObjectId(debt_id)})
    debt["_id"] = str(debt["_id"])
    return debt

@app.get(f"{prefix}/{{student_id}}/debts")
def get_debts(student_id: str):
    debts = db["debts"].find({"student_id": int(student_id)})
    debts = list(debts)
    for debt in debts:
        debt["_id"] = str(debt["_id"])
    return debts

@app.post(f"{prefix}/{{student_id}}/enrollments")
def enroll_student(student_id: str, semester: str = Form(...)):
    #Registrar un pago de un alumno
    enrollment_data = {
        "semester": semester,
        "student_id": int(student_id)
    }

    result = db["enrollments"].insert_one(enrollment_data)
    return {"succesfull inster in id": str(result.inserted_id)}

@app.put(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def update_enrollment(student_id: str, enrollment_id: str, semester: str = Form(...)):
    enrollment_data = {
        "semester": semester,
        "student_id": int(student_id)
    }
    db["enrollments"].update_one({"_id": ObjectId(enrollment_id)}, {"$set": enrollment_data})
    return {"Hello": student_id, "Enrollment": enrollment_id}

@app.delete(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def delete_enrollment(student_id: str, enrollment_id: str):
    enrollment_data = db["enrollments"].find_one({"_id": ObjectId(enrollment_id)})
    enrollment_data["_id"] = str(enrollment_data["_id"])
    db["deleted_enrollments"].insert_one(enrollment_data)
    db["enrollments"].delete_one({"_id": ObjectId(enrollment_id)})

    return {"Hello": student_id, "Enrollment": enrollment_id}

@app.get(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def get_enrollment(student_id: str, enrollment_id: str):
    enrollment = db["enrollments"].find_one({"_id": ObjectId(enrollment_id)})
    enrollment["_id"] = str(enrollment["_id"])
    return enrollment

@app.get(f"{prefix}/{{student_id}}/enrollments")
def get_enrollments(student_id: str):
    enrollments = db["enrollments"].find({"student_id": int(student_id)})
    enrollments = list(enrollments)
    for enrollment in enrollments:
        enrollment["_id"] = str(enrollment["_id"])
    return enrollments

