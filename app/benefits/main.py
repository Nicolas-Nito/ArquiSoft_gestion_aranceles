import threading
from pydantic import BaseModel, ConfigDict
from fastapi import FastAPI, APIRouter, HTTPException, Request, requests
from pymongo import MongoClient
from pydantic import BaseModel, Field
from bson import ObjectId
from datetime import datetime
from typing import List
import os
from ..routers.router import prefix, router
from ..rabbit.main import publish_event
import pika
from pika.exchange_type import ExchangeType
from typing import Optional
import json
from fastapi.middleware.cors import CORSMiddleware
# Obtener las credenciales desde el entorno
rabbitmq_url = os.getenv("RABBITMQ_URL")
mongo_user = os.getenv("MONGO_ADMIN_USER")
mongo_pass = os.getenv("MONGO_ADMIN_PASS")

client = MongoClient("mongodb://mongodb:27017/",
                     username=mongo_user,
                     password=mongo_pass)
db = client["benefit"]
benefits_collection = db["benefits"]

app = FastAPI()
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------Schemas-------------------------------
class Payment(BaseModel):
    payment_id: str
    debt_id: str
    type: str
    amount: float
    month: str
    semester: str
    year: int
    description: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "payment_id": "PAY123",
                "debt_id": "DEBT123",
                "type": "arancel",
                "amount": 1500.00,
                "month": "marzo",
                "semester": "2024-1",
                "year": "2024",
                "description": "Descripción del pago",
            }
        }
    }


class UpdatePayment(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = None
    month: Optional[str] = None
    semester: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    status: Optional[str] = None
    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "matricula",
                "amount": 2000.00,
                "month": "marzo",
                "semester": "2024-1",
                "year": 2025,
                "description": "Pago de matricula del estudiante",
                "status": "actived",
            }
        }
    }


class Benefit(BaseModel):
    benefit_id: str
    name: str
    description: str
    amount: float
    start_date: datetime
    end_date: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "benefit_id": "BEN123",
                    "name": "Nombre del beneficio",
                    "description": "Descripción del beneficio",
                    "amount": 500.00,
                    "start_date": "2024-10-20T22:16:23.930Z",
                    "end_date": "2024-10-20T22:16:23.930Z"
                }
            ]
        }
    }


class UpdateBenefit(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Nombre de pago actualizado",
                    "description": "Descripción de pago actualizado",
                    "amount": 600.00,
                    "start_date": "2024-10-20T22:16:23.930Z",
                    "end_date": "2024-10-20T22:16:23.930Z",
                    "status": "actived"
                }
            ]
        }
    }


# ----------------------End Points-------------------------------


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
def register_benefit(student_id: str, benefit: Benefit):
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

    publish_event(f"benefits.{benefit_id}.updated",
                  {
        "origin_service": "benefits",
        "student_id": student_id,
        "data": update_benefit.dict()
    })

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

    publish_event(f"benefits.{benefit_id}.deleted",
                  {
        "origin_service": "benefits",
        "student_id": student_id,
        "benefit_id": benefit_id
    })
    return {"msg": "Beneficio eliminado exitosamente"}

# Endpoint: Consultar información de un beneficio (GET)


@ app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", summary="Consultar información de un beneficio", tags=["GET"])
def get_benefit(student_id: str, benefit_id: str):
    """
    Obtiene la información detallada de un beneficio específico asignado a un estudiante.

    Parámetros:
    - student_id: Identificador único del estudiante
    - benefit_id: Identificador único del beneficio a consultar
    """
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
def list_benefits(student_id: str, skip: Optional[int] = None, limit: Optional[int] = None, status: Optional[str] = None):
    """
    Obtiene la lista de todos los beneficios asociados a un estudiante específico.

    Parámetros:
    - student_id: Identificador único del estudiante
    - skip: Número de registros a omitir para la paginación (opcional)
    - limit: Número máximo de registros a retornar (opcional)
    - status: Filtro por estado del beneficio ("actived", "inactived" o "expired") (opcional)
    """
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
            publish_event(f"payments.{payment.
                                      payment_id}.created",
                          {
                "origin_service": "benefits",
                "student_id": student_id,
                "data": payment.dict()
            })
            return {"msg": "Pago registrado exitosamente", "payment_id": payment.payment_id}

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")

# Endpoint: Actualizar información de un pago mediante un beneficio (PUT)


@ app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Actualizar información de un pago mediante un beneficio", description="""
  `amount`: Valor monetario del pago.\n
  `description`: Descripción del pago.\n
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
    # payment.description = "Pago"

    publish_event(f"payments.{payment_id}.updated",
                  {
        "origin_service": "benefits",
        "student_id": student_id,
        "payment_id": payment_id,
        "data": payment
    })

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
    publish_event(f"payments.{payment_id}.deleted",
                  {
        "origin_service": "benefits",
        "student_id": student_id,
        "payment_id": payment_id
    })
    return {"msg": "Pago eliminado exitosamente"}

# Endpoint: Consultar información de un pago mediante un beneficio (GET)


@ app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", summary="Consultar información de un pago mediante un beneficio", tags=["GET"])
def consultar_pago(student_id: str, benefit_id: str, payment_id: str):
    """
    Obtiene la información detallada de un pago específico asociado a un beneficio de un estudiante.

    Parámetros:
    - student_id: Identificador único del estudiante
    - benefit_id: Identificador único del beneficio asociado al pago
    - payment_id: Identificador único del pago a consultar
    """
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
    """
    Obtiene la lista de todos los pagos realizados para un beneficio específico de un estudiante, con opciones de filtrado y paginación.

    Parámetros:
    - student_id: Identificador único del estudiante
    - benefit_id: Identificador único del beneficio
    - skip: Número de registros a omitir para la paginación (opcional)
    - limit: Número máximo de registros a retornar (opcional)
    - status: Estado de los pagos a filtrar ("actived", "inactived" o "expired") (opcional)
    """
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
