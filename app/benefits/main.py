from fastapi import FastAPI,APIRouter, HTTPException, Request
from pymongo import MongoClient
from pydantic import BaseModel, Field
from bson import ObjectId
from datetime import datetime
from typing import List
import os
from ..routers.test import prefix, router
import pika
from pika.exchange_type import ExchangeType

# Obtener las credenciales desde el entorno
rabbitmq_url = os.getenv("RABBITMQ_URL")
mongo_user = os.getenv("MONGO_ADMIN_USER")
mongo_pass = os.getenv("MONGO_ADMIN_PASS")

# Asegúrate de que la URI esté configurada correctamente
#mongo_uri = f"mongodb://{mongo_user}:{mongo_pass}@mongodb:27017/?authMechanism=DEFAULT" 
#client = MongoClient(mongo_uri)
client = MongoClient("mongodb://mongodb:27017/",
                                   username=mongo_user,
                                   password=mongo_pass)
db = client["tarea-unidad-04"]
benefits_collection = db["benefits"]

app = FastAPI()
app.include_router(router)

class Payment(BaseModel):
    payment_id: str
    amount: float
    date: datetime
    status: str


class Benefit(BaseModel):
    benefit_id: str
    name: str
    description: str
    amount: float
    start_date: datetime
    end_date: datetime
    status: str


class Student(BaseModel):
    student_id: str
    benfits: List[Benefit] = []

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

# Endpoint: Registrar un beneficio (POST)


@app.post(f"{prefix}/{{student_id}}/benefits", summary="Registrar un Beneficio",
             description="""
  `benefit_id`: ID del beneficio.\n
  `name`: Nombre del beneficio.\n
  `description`: Descripción del beneficio.\n
  `amount`: Valor monetario del beneficio.\n
  `start_date`: Fecha de inicio del beneficio (Ejemplo: 2024-10-20T22:16:23.930Z).\n
  `end_date`: Fecha de finalización del beneficio (Ejemplo: 2024-10-20T22:16:23.930Z).\n
  `status`: Estado del beneficio (Valores esperados: "active", "inactive" o "expired").
""",tags=["POST"])
async def register_benefit(student_id: str, benefit: Benefit):
    student_result = benefits_collection.find_one(
        {"student_id": student_id})
    if student_result:
        has_benefit = any(
            benefit.benefit_id == ben["benefit_id"] for ben in student_result["benefits"]
        )
        if has_benefit:
            raise HTTPException(
                status_code=400, detail="El beneficio ya fue asignado")
        result = benefits_collection.update_one(
            {"student_id": student_id},
            {"$push": {"benefits": benefit.dict()}}
        )
    else:
        student_dict = {
            "student_id": student_id,
            "benefits": [benefit.dict()]
        }
        result = benefits_collection.insert_one(student_dict)

    if not result:
        raise HTTPException(
            status_code=400, detail="No se pudo registrar el beneficio")
    
    publish_event(f"benefits.{benefit.benefit_id}.created",{"student_id":student_id,"data":benefit.dict()})
    return {"msg": "Beneficio registrado exitosamente!"}

# Endpoint: Actualizar información de un beneficio (PUT)


@ app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Actualizar información de un beneficio",tags=["PUT"])
def update_benefit(student_id: str, benefit_id: str, update_benefit: Benefit):
    result = benefits_collection.update_one(
        {"student_id": student_id, "benefits.benefit_id": benefit_id},
        {"$set": {"benefits.$": update_benefit.dict(exclude_unset=True)}}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Beneficio o estudiante no encontrado")
    
    publish_event(f"benefits.{benefit_id}.updated",{"student_id":student_id,"data":update_benefit.dict()})
    return {"msg": "Beneficio actualizado exitosamente!"}

# Endpoint: Eliminar un beneficio (DELETE)


@app.delete(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Eliminar un beneficio",tags=["DELETE"])
def delete_benefit(student_id: str, benefit_id: str):
    result = benefits_collection.update_one(
        {"student_id": student_id},
        {"$pull": {"benefits": {"benefit_id": benefit_id}}}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Beneficio o estudiante no encontrado")

    publish_event(f"benefits.{benefit_id}.deleted",{"student_id":student_id,"benefit_id":benefit_id})
    return {"msg": "Beneficio eliminado exitosamente"}

# Endpoint: Consultar información de un beneficio (GET)


@app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Consultar información de un beneficio",tags=["GET"])
def get_benefit(student_id: str, benefit_id: str):
    student = benefits_collection.find_one(
        {"student_id": student_id, "benefits.benefit_id": benefit_id},
        {"benefits.$": 1}
    )

    if not student or "benefits" not in student or not student["benefits"]:
        raise HTTPException(
            status_code=404, detail="Beneficio o estudiante no encontrado")

    return student["benefits"][0]

# Endpoint: Listar todos los beneficios de un estudiante (GET)


# @app.get(f"{prefix}/{{student_id}}/benefits",tags=["GET"])
# def list_benefits(student_id: str,skip: int = 0, limit: int = 10):
#     query = {"student_id": student_id}
#     student = benefits_collection.find_one(query)
#     if not student:
#         raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
#     benefits = list(benefits_collection.find(query).skip(skip).limit(limit))
#     for benefit in benefits:
#         benefit["_id"] = str(benefit["_id"])

#     return benefits


@app.get(f"{prefix}/{{student_id}}/benefits",tags=["GET"])
def list_benefits(student_id: str,skip: int = None, limit: int = None, status: str = None):
    query = {"student_id": student_id}
    student = benefits_collection.find_one(query)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    benefits = student['benefits']
    
    # Filtrar por estado
    if status is not None:
        benefits = [benefit for benefit in benefits if benefit["status"] == status]

    # Aplicar paginación
    if skip is not None and limit is not None:
        benefits = benefits[skip:skip+limit]

    return benefits


# Endpoint: Registrar un pago mediante un beneficio (POST)


@app.post(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments", summary="Registrar un pago mediante un beneficio",tags=["POST"])
def registrar_pago(student_id: str, benefit_id: str, payment: Payment):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    for benefit in student["benefits"]:
        if benefit["benefit_id"] == benefit_id:
            if "payments" not in benefit or not benefit["payments"]:
                benefits_collection.update_one(
                    {"student_id": student_id, "benefits.benefit_id": benefit_id},
                    {"$set": {"benefits.$.payments": [payment.dict()]}}
                )
            else:
                payment_exists = any(
                    payment.payment_id == pay["payment_id"] for pay in benefit["payments"]
                )
                if payment_exists:
                    raise HTTPException(
                        status_code=400, detail="El pago ya fue registrado")
                benefits_collection.update_one(
                    {"student_id": student_id, "benefits.benefit_id": benefit_id},
                    {"$push": {"benefits.$.payments": payment.dict()}}
                )

            publish_event(f"payments.{payment.payment_id}.created",{"student_id":student_id,"data":payment.dict()})
            return {"message": "Pago registrado exitosamente", "payment_id": payment.payment_id}

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")

# Endpoint: Actualizar información de un pago mediante un beneficio (PUT)


@app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Actualizar información de un pago mediante un beneficio",tags=["PUT"])
def actualizar_pago(student_id: str, benefit_id: str, payment_id: str, updated_payment: Payment):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    result = benefits_collection.update_one(
        {"student_id": student_id, "benefits.benefit_id": benefit_id,
            "benefits.payments.payment_id": payment_id},
        {"$set": {
            "benefits.$.payments.$[payment].payment_id": updated_payment.payment_id,
            "benefits.$.payments.$[payment].amount": updated_payment.amount,
            "benefits.$.payments.$[payment].date": updated_payment.date,
            "benefits.$.payments.$[payment].status": updated_payment.status
        }},
        array_filters=[{"payment.payment_id": payment_id}]
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Pago no encontrado o no se pudo actualizar")

    publish_event(f"payments.{payment_id}.updated",{"student_id":student_id,"data":updated_payment.dict()})
    return {"message": "Pago actualizado exitosamente"}

# Endpoint: Eliminar un pago mediante un beneficio (DELETE)


@app.delete(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Eliminar un pago mediante un beneficio",tags=["DELETE"])
def eliminar_pago(student_id: str, benefit_id: str, payment_id: str):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    result = benefits_collection.update_one(
        {"student_id": student_id, "benefits.benefit_id": benefit_id},
        {"$pull": {"benefits.$.payments": {"payment_id": payment_id}}}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Pago no encontrado o no se pudo eliminar")

    publish_event(f"payments.{payment_id}.deleted",{"student_id":student_id,"payment_id":payment_id})
    return {"message": "Pago eliminado exitosamente"}

# Endpoint: Consultar información de un pago mediante un beneficio (GET)


@app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Consultar información de un pago mediante un beneficio",tags=["GET"])
def consultar_pago(student_id: str, benefit_id: str, payment_id: str):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    for benefit in student["benefits"]:
        if benefit["benefit_id"] == benefit_id:
            if "payments" not in benefit or not benefit["payments"]:
                raise HTTPException(
                    status_code=404, detail="No hay pagos registrados para este beneficio")
            for payment in benefit["payments"]:
                if payment["payment_id"] == payment_id:
                    return payment

    raise HTTPException(status_code=404, detail="Pago no encontrado")

# Endpoint: Listar todos los pagos de un beneficio (GET)


@app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments", summary="Listar todos los pagos de un beneficio",tags=["GET"])
def listar_pagos(student_id: str, benefit_id: str, skip: int = None, limit: int = None, status: str = None):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    for benefit in student["benefits"]:
        if benefit["benefit_id"] == benefit_id:

            if "payments" not in benefit or not benefit["payments"]:
                raise HTTPException(
                    status_code=404, detail="No hay pagos registrados para este beneficio")
            
            payments = benefit["payments"]

            # Filtrar por estado
            if status is not None:
                payments = [payment for payment in payments if payment["status"] == status]

            # Aplicar paginación si se especifican skip y limit
            if skip is not None and limit is not None:
                payments = payments[skip:skip + limit]
            return payments

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")
