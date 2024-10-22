from pydantic import BaseModel, ConfigDict
from fastapi import FastAPI, APIRouter, HTTPException, Request
from pymongo import MongoClient
from pydantic import BaseModel, Field
from bson import ObjectId
from datetime import datetime
from typing import List
import os
from ..routers.test import prefix, router
import pika
from pika.exchange_type import ExchangeType
from typing import Optional

# Obtener las credenciales desde el entorno
rabbitmq_url = os.getenv("RABBITMQ_URL")
mongo_user = os.getenv("MONGO_ADMIN_USER")
mongo_pass = os.getenv("MONGO_ADMIN_PASS")

client = MongoClient("mongodb://mongodb:27017/",
                     username=mongo_user,
                     password=mongo_pass)
db = client["tarea-unidad-04"]
benefits_collection = db["benefits"]

app = FastAPI()
app.include_router(router)


class Payment(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "payment_id": "PAY123",
                "amount": 1500.00,
                "date": datetime.now().isoformat()
            }
        },
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True,
        strict=True
    )
    payment_id: str
    amount: float
    date: datetime


class UpdatePayment(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "amount": 2000.00,
                "date": datetime.now().isoformat(),
                "status": "actived"
            }
        },
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True
    )
    amount: Optional[float] = None
    date: Optional[datetime] = None
    status: Optional[str] = None


class Benefit(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "benefit_id": "BEN456",
                "name": "CAE",
                "description": "Descripción del CAE",
                "amount": 500.00,
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().isoformat()
            }
        },
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True,
        strict=True
    )
    benefit_id: str
    name: str
    description: str
    amount: float
    start_date: datetime
    end_date: datetime


class UpdateBenefit(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Nombre de pago actualizado",
                "description": "Descripción de pago actualizado",
                "amount": 600.00,
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().isoformat(),
                "status": "actived"
            }
        },
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True
    )
    name: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None

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
        raise HTTPException(
            status_code=500, detail="Cannot connect to RabbitMQ")
    channel = connection.channel()
    channel.exchange_declare(exchange='topic_exchange',
                             exchange_type=ExchangeType.topic)
    # Declarar una cola llamada 'hello'
    queue_benefits = channel.queue_declare(queue='benefits', durable=True)
    queue_payments = channel.queue_declare(queue='payments', durable=True)

    # Enlazar la cola con el exchange
    channel.queue_bind(exchange='topic_exchange',
                       queue=queue_benefits.method.queue, routing_key='benefits.*.*')
    channel.queue_bind(exchange='topic_exchange',
                       queue=queue_payments.method.queue, routing_key='payments.*.*')
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
""", tags=["POST"])
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

        benefits_collection.update_one(
            {"student_id": student_id, "benefits.benefit_id": benefit.benefit_id},
            {"$set": {"benefits.$.status": "actived"}}
        )

    if not result:
        raise HTTPException(
            status_code=400, detail="No se pudo registrar el beneficio")

    publish_event(f"benefits.{benefit.benefit_id}.created", {
                  "student_id": student_id, "data": benefit.dict()})
    return {"msg": "Beneficio registrado exitosamente!"}

# Endpoint: Actualizar información de un beneficio (PUT)


@ app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Actualizar información de un beneficio", description="""
  `name`: Nombre del beneficio.\n
  `description`: Descripción del beneficio.\n
  `amount`: Valor monetario del beneficio.\n
  `start_date`: Fecha de inicio del beneficio (Ejemplo: 2024-10-20T22:16:23.930Z).\n
  `end_date`: Fecha de finalización del beneficio (Ejemplo: 2024-10-20T22:16:23.930Z).\n
  `status`: estado del beneficio (Valores que puede tomar: "actived", "inactived" o "expired")
""", tags=["PUT"])
def update_benefit(student_id: str, benefit_id: str, update_benefit: UpdateBenefit):
    result = benefits_collection.find_one(
        {"student_id": student_id},
        {
            "benefits": {
                "$elemMatch": {
                    "benefit_id": benefit_id
                }
            }
        }
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Estudiante no encontrado"
        )

    if not result.get("benefits"):
        raise HTTPException(
            status_code=404,
            detail="Beneficio o pago no encontrado"
        )

    # Crear un diccionario con solo los campos que no son None
    update_data = {
        k: v for k, v in update_benefit.dict().items()
        if v is not None
    }

    # Si no hay datos para actualizar, retornar error
    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No se proporcionaron datos para actualizar"
        )

    # Crear el diccionario de actualización con la notación correcta para arrays
    update_fields = {
        f"benefits.$.{key}": value
        for key, value in update_data.items()
    }

    result = benefits_collection.update_one(
        {
            "student_id": student_id,
            "benefits.benefit_id": benefit_id
        },
        {
            "$set": update_fields
        }
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Estudiante o beneficio no encontrado"
        )

    # Obtener el beneficio actualizado
    updated_student = benefits_collection.find_one(
        {
            "student_id": student_id,
            "benefits.benefit_id": benefit_id
        },
        {
            "benefits": {
                "$elemMatch": {
                    "benefit_id": benefit_id
                }
            }
        }
    )

    if not updated_student or not updated_student.get("benefits"):
        raise HTTPException(
            status_code=404,
            detail="No se pudo obtener el beneficio actualizado"
        )

    publish_event(f"benefits.{benefit_id}.updated", {
                  "student_id": student_id, "data": update_benefit.dict()})

    return updated_student["benefits"][0]

# Endpoint: Eliminar un beneficio (DELETE)


@ app.delete(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Eliminar un beneficio", description="Se puede eliminar un beneficio proporcionando el id del estudiante (student_id) y el id del beneficio (benefit_id)", tags=["DELETE"])
def delete_benefit(student_id: str, benefit_id: str):
    result = benefits_collection.update_one(
        {"student_id": student_id, "benefits.benefit_id": benefit_id},
        {"$set": {"benefits.$.status": "inactived"}}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Beneficio o estudiante no encontrado")

    publish_event(f"benefits.{benefit_id}.deleted", {
                  "student_id": student_id, "benefit_id": benefit_id})
    return {"msg": "Beneficio eliminado exitosamente"}

# Endpoint: Consultar información de un beneficio (GET)


@ app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Consultar información de un beneficio", tags=["GET"])
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


@ app.get(f"{prefix}/{{student_id}}/benefits", tags=["GET"], summary="Listar todos los beneficios de un estudiante")
def list_benefits(student_id: str, skip: int = None, limit: int = None, status: str = None):
    query = {"student_id": student_id}
    student = benefits_collection.find_one(query)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    benefits = student['benefits']

    # Filtrar por estado
    if status is not None:
        benefits = [
            benefit for benefit in benefits if benefit["status"] == status]

    # Aplicar paginación
    if skip is not None and limit is not None:
        benefits = benefits[skip:skip+limit]

    return benefits


# Endpoint: Registrar un pago mediante un beneficio (POST)


@ app.post(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments", summary="Registrar un pago mediante un beneficio", tags=["POST"])
def registrar_pago(student_id: str, benefit_id: str, payment: Payment):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    for benefit in student["benefits"]:
        if benefit["benefit_id"] == benefit_id:
            if "payments" not in benefit or not benefit["payments"]:
                benefits_collection.update_one(
                    {
                        "student_id": student_id,
                        "benefits.benefit_id": benefit_id
                    },
                    {
                        "$set": {"benefits.$.payments": [payment.dict()]}
                    }
                )

                benefits_collection.update_one(
                    {
                        "student_id": student_id,
                        "benefits.benefit_id": benefit_id,
                        "benefits.payments.payment_id": payment.payment_id
                    },
                    {
                        "$set": {
                            "benefits.$[b].payments.$[p].status": "actived"
                        }
                    },
                    array_filters=[
                        {"b.benefit_id": benefit_id},
                        {"p.payment_id": payment.payment_id}
                    ]
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

            publish_event(f"payments.{payment.payment_id}.created", {
                          "student_id": student_id, "data": payment.dict()})
            return {"msg": "Pago registrado exitosamente", "payment_id": payment.payment_id}

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")

# Endpoint: Actualizar información de un pago mediante un beneficio (PUT)


@ app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Actualizar información de un pago mediante un beneficio", description="""
  `amount`: Valor monetario del pago.\n
  `date`: Fecha del pago.\n
  `status`: estado del pago (Valores que puede tomar: "actived", "inactived" o "expired")
""",  tags=["PUT"])
def actualizar_pago(student_id: str, benefit_id: str, payment_id: str, update_payment: UpdatePayment):
    result = benefits_collection.find_one(
        {"student_id": student_id},
        {
            "benefits": {
                "$elemMatch": {
                    "benefit_id": benefit_id,
                    "payments": {
                        "$elemMatch": {
                            "payment_id": payment_id
                        }
                    }
                }
            }
        }
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Estudiante no encontrado"
        )

    if not result.get("benefits"):
        raise HTTPException(
            status_code=404,
            detail="Beneficio o pago no encontrado"
        )

    # Accedemos al pago específico
    if not result["benefits"][0].get("payments"):
        raise HTTPException(
            status_code=404,
            detail="Pago no encontrado"
        )

    update_data = {
        k: v for k, v in update_payment.dict().items()
        if v is not None
    }

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No se proporcionaron datos para actualizar"
        )

    # Crear el diccionario de actualización para los campos del payment
    update_fields = {
        f"benefits.$[b].payments.$[p].{key}": value
        for key, value in update_data.items()
    }

    result = benefits_collection.update_one(
        {
            "student_id": student_id
        },
        {
            "$set": update_fields
        },
        array_filters=[
            {"b.benefit_id": benefit_id},
            {"p.payment_id": payment_id}
        ]
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Estudiante, beneficio o pago no encontrado"
        )

    # Obtener el payment actualizado
    updated_student = benefits_collection.find_one(
        {
            "student_id": student_id,
            "benefits": {
                "$elemMatch": {
                    "benefit_id": benefit_id,
                    "payments": {
                        "$elemMatch": {
                            "payment_id": payment_id
                        }
                    }
                }
            }
        }
    )

    if not updated_student or not updated_student.get("benefits"):
        raise HTTPException(
            status_code=404,
            detail="No se pudo obtener el pago actualizado"
        )

    # Extraer el payment actualizado
    payment = updated_student["benefits"][0]["payments"][0]

    publish_event(f"payments.{payment_id}.updated", {
                  "student_id": student_id, "data": update_payment.dict()})

    return {
        "payment": payment
    }

# Endpoint: Eliminar un pago mediante un beneficio (DELETE)


@ app.delete(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Eliminar un pago mediante un beneficio", description="Se puede eliminar el pago de un beneficio proporcionando el id del estudiante (student_id), el id del beneficio (benefit_id) y el id del pago (payment_id)", tags=["DELETE"])
def eliminar_pago(student_id: str, benefit_id: str, payment_id: str):
    result = benefits_collection.find_one(
        {"student_id": student_id},
        {
            "benefits": {
                "$elemMatch": {
                    "benefit_id": benefit_id,
                    "payments": {
                        "$elemMatch": {
                            "payment_id": payment_id
                        }
                    }
                }
            }
        }
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Estudiante no encontrado"
        )

    if not result.get("benefits"):
        raise HTTPException(
            status_code=404,
            detail="Beneficio o pago no encontrado"
        )

    # Accedemos al pago específico
    if not result["benefits"][0].get("payments"):
        raise HTTPException(
            status_code=404,
            detail="Pago no encontrado"
        )

    result = benefits_collection.update_one(
        {
            "student_id": student_id,
            "benefits.benefit_id": benefit_id,
            "benefits.payments.payment_id": payment_id
        },
        {
            "$set": {
                "benefits.$[b].payments.$[p].status": "inactived"
            }
        },
        array_filters=[
            {"b.benefit_id": benefit_id},
            {"p.payment_id": payment_id}
        ]
    )
    publish_event(f"payments.{payment_id}.deleted", {
                  "student_id": student_id, "payment_id": payment_id})
    return {"msg": "Pago eliminado exitosamente"}

# Endpoint: Consultar información de un pago mediante un beneficio (GET)


@ app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Consultar información de un pago mediante un beneficio", tags=["GET"])
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


@ app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments", summary="Listar todos los pagos de un beneficio", tags=["GET"])
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
                payments = [
                    payment for payment in payments if payment["status"] == status]

            # Aplicar paginación si se especifican skip y limit
            if skip is not None and limit is not None:
                payments = payments[skip:skip + limit]
            return payments

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")
