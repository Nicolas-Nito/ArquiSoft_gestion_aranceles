from datetime import datetime
import json
import threading
from fastapi import FastAPI, Form, HTTPException, status, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

import time
from bson.objectid import ObjectId
import pymongo
import os
from dotenv import load_dotenv
import pika
from pika.exchange_type import ExchangeType
from enum import Enum
from ..routers.router import prefix, router
from ..rabbit.main import get_rabbitmq_connection, publish_event

from typing import Optional, List

load_dotenv()


rabbitmq_url = os.getenv("RABBITMQ_URL")

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["payment"]
payments_collection = db["payments"]

app = FastAPI()
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ----- Schemas ------


class PaymentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactived"


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
                "type": "matricula",
                "amount": 1500.00,
                "month": "marzo",
                "semester": "2024-1",
                "year": "2024",
                "description": "Pago de matricula del estudiante",
            }
        }
    }


class Student(BaseModel):
    student_id: str
    payments: List[Payment] = []


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


class PaymentResponse(BaseModel):
    payment_id: str
    debt_id: str
    type: str
    amount: float
    month: str
    semester: str
    year: int
    description: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class PaginatedPaymentsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    payments: List[PaymentResponse]

# ----------------------End Points-------------------------------

# Registrar un pago:


@app.post(
    f"{prefix}/{{student_id}}/payments",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un pago para un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["POST"]
)
async def store_payment(student_id: str, payment: Payment):
    try:
        existing_payment_check = payments_collection.find_one({
            "student_id": student_id,
            "payments": {
                "$elemMatch": {
                    "debt_id": payment.debt_id,
                    "month": payment.month,
                    "semester": payment.semester,
                    "year": payment.year
                }
            }
        })

        if existing_payment_check:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un pago registrado para la deuda {
                    payment.debt_id} del estudiante con ID {student_id} el {payment.month}/{payment.year}"
            )
        existing_payment = payments_collection.find_one(
            {"payments": {"$elemMatch": {"payment_id": payment.payment_id}}}
        )

        if existing_payment:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El pago con ID {payment.payment_id} ya existe"
            )

        payment_dict = payment.model_dump()
        payment_dict.update({
            "status": "active",
            "created_at": datetime.now()
        })

        result = payments_collection.update_one(
            {"student_id": student_id},
            {"$push": {"payments": payment_dict}}
        )

        if result.matched_count == 0:
            new_student = {
                "student_id": student_id,
                "payments": [payment_dict]
            }
            payments_collection.insert_one(new_student)

        student = payments_collection.find_one({"student_id": student_id})
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se pudo recuperar el estudiante con ID: {
                    student_id}"
            )

        student.pop('_id', None)

        publish_event(f"debts.{payment.debt_id}.updated",
                      {
            "origin_service": "payments",
            "student_id": student_id,
            "data": payment.dict()
        })
        return {"msg": "Pago registrado correctamente!", "student_payments": "student"}

    except HTTPException:
        raise
    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error en la base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error inesperado: {str(e)}"
        )

# Actualizar información de un pago:


@app.put(
    f"{prefix}/{{student_id}}/payments/{{payment_id}}",
    status_code=status.HTTP_200_OK,
    summary="Actualizar información de un pago de un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["PUT"]
)
async def update_payment(student_id: str, payment_id: str, update_payment: UpdatePayment):
    try:
        update_data = {
            k: v for k, v in update_payment.model_dump().items()
            if v is not None
        }

        if len(update_data) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se proporcionaron datos para actualizar"
            )

        update_data['updated_at'] = datetime.now()

        result = payments_collection.update_one(
            {
                "student_id": student_id,
                "payments.payment_id": payment_id
            },
            {
                "$set": {
                    f"payments.$.{key}": value
                    for key, value in update_data.items()
                }
            }
        )

        if result.matched_count == 0:
            student = payments_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pago con ID {
                    payment_id} no encontrado para estudiante {student_id}"
            )

        if result.modified_count == 0:
            return payments_collection.find_one({"student_id": student_id})

        updated_student = payments_collection.find_one(
            {"student_id": student_id})
        if not updated_student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se pudo recuperar el registro actualizado del estudiante"
            )

        updated_student.pop('_id', None)
        return {"msg": "Pago actualizado correctamente!", "student_updated": updated_student}

    except HTTPException:
        raise
    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error en la base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error inesperado: {str(e)}"
        )

# Eliminar un pago:


@app.delete(
    f"{prefix}/{{student_id}}/payments/{{payment_id}}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar pago de un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["DELETE"]
)
async def delete_payment(student_id: str, payment_id: str):
    try:
        try:
            payment = payments_collection.aggregate([
                {"$match": {"student_id": student_id}},
                {"$unwind": "$payments"},
                {"$match": {"payments.payment_id": payment_id}},
                {"$project": {
                    "_id": 0,
                    "status": "$payments.status"
                }}
            ]).next()

        except StopIteration:
            student = payments_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pago con ID {
                    payment_id} no encontrado para estudiante {student_id}"
            )

        if payment.get('status') == 'inactived':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pago con ID {payment_id} ya fue eliminado"
            )

        update_result = payments_collection.update_one(
            {
                "student_id": student_id,
                "payments.payment_id": payment_id
            },
            {
                "$set": {
                    "payments.$.status": "inactived",
                    "payments.$.updated_at": datetime.now()
                }
            }
        )

        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al eliminar el pago"
            )

        updated_payment = payments_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$payments"},
            {"$match": {"payments.payment_id": payment_id}},
            {"$project": {
                "_id": 0,
                "payment_id": "$payments.payment_id",
                "debt_id": "$payments.debt_id",
                "type": "$payments.type",
                "amount": "$payments.amount",
                "semester": "$payments.semester",
                "month": "$payments.month",
                "year": "$payments.year",
                "status": "$payments.status",
                "description": "$payments.description",
                "created_at": "$payments.created_at",
                "updated_at": "$payments.updated_at"
            }}
        ]).next()

        return updated_payment

    except StopIteration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se pudo recuperar el pago actualizado"
        )
    except HTTPException:
        raise
    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error en la base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error inesperado: {str(e)}"
        )

# Consultar información de un pago:


@app.get(
    f"{prefix}/{{student_id}}/payments/{{payment_id}}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener información de un pago específico",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["GET"]
)
async def get_payment(student_id: str, payment_id: str):
    try:
        payment_cursor = payments_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$payments"},
            {"$match": {"payments.payment_id": payment_id}},
            {"$project": {
                "_id": 0,
                "payment_id": "$payments.payment_id",
                "debt_id": "$payments.debt_id",
                "type": "$payments.type",
                "amount": "$payments.amount",
                "semester": "$payments.semester",
                "month": "$payments.month",
                "year": "$payments.year",
                "status": "$payments.status",
                "description": "$payments.description",
                "created_at": "$payments.created_at",
                "updated_at": "$payments.updated_at"
            }}
        ])

        try:
            payment = payment_cursor.next()
        except StopIteration:
            student = payments_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pago con ID {
                    payment_id} no encontrado para estudiante{student_id}"
            )

        return payment

    except HTTPException:
        raise
    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error en la base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error inesperado: {str(e)}"
        )

# Listar todos los pagos de un estudiante:


@app.get(
    f"{prefix}/{{student_id}}/payments",
    response_model=PaginatedPaymentsResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener los pagos de los estudiantes con paginación y filtros",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["GET"]
)
async def get_payments(
    student_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100,
                           description="Items per page"),
    status: Optional[PaymentStatus] = Query(
        default=None, description="Filter by payment status"),
    min_amount: Optional[float] = Query(
        default=None, ge=0, description="Minimum payment amount"),
    max_amount: Optional[float] = Query(
        default=None, ge=0, description="Maximum payment amount"),
    from_date: Optional[datetime] = Query(
        default=None, description="Filter payments from this date"),
    to_date: Optional[datetime] = Query(
        default=None, description="Filter payments until this date"),
    sort_by: Optional[str] = Query(
        default="created_at",
        enum=["created_at", "amount", "payment_id"],
        description="Field to sort by"
    ),
    sort_order: Optional[str] = Query(
        default="desc",
        enum=["asc", "desc"],
        description="Sort order"
    )
):
    try:
        student = payments_collection.find_one({"student_id": student_id})
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Student with ID {student_id} not found"
            )
        match_conditions = {"student_id": student_id}
        filter_conditions = {}

        if status:
            filter_conditions["payments.status"] = status.value

        if min_amount is not None:
            filter_conditions["payments.amount"] = {"$gte": min_amount}
        if max_amount is not None:
            filter_conditions["payments.amount"] = {
                **filter_conditions.get("payments.amount", {}),
                "$lte": max_amount
            }

        if from_date:
            filter_conditions["payments.created_at"] = {"$gte": from_date}
        if to_date:
            filter_conditions["payments.created_at"] = {
                **filter_conditions.get("payments.created_at", {}),
                "$lte": to_date
            }

        pipeline = [
            {"$match": match_conditions},
            {"$unwind": "$payments"},
        ]

        if filter_conditions:
            pipeline.append({"$match": filter_conditions})

        sort_direction = pymongo.DESCENDING if sort_order == "desc" else pymongo.ASCENDING
        pipeline.append({"$sort": {f"payments.{sort_by}": sort_direction}})

        count_pipeline = pipeline.copy()
        count_pipeline.append({"$count": "total"})
        total_count = list(payments_collection.aggregate(count_pipeline))
        total = total_count[0]["total"] if total_count else 0

        pipeline.extend([
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
            {
                "$project": {
                    "_id": 0,
                    "payment_id": "$payments.payment_id",
                    "debt_id": "$payments.debt_id",
                    "type": "$payments.type",
                    "amount": "$payments.amount",
                    "month": "$payments.month",
                    "semester": "$payments.semester",
                    "year": "$payments.year",
                    "status": "$payments.status",
                    "description": "$payments.description",
                    "created_at": "$payments.created_at",
                    "updated_at": "$payments.updated_at"
                }
            }
        ])

        payments = list(payments_collection.aggregate(pipeline))

        return PaginatedPaymentsResponse(
            total=total,
            page=page,
            page_size=page_size,
            payments=payments
        )

    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error en la base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"A ocurrido un error inesperado: {str(e)}"
        )

# Listar todos los pagos de un arancel:


@app.get(
    f"{prefix}/{{student_id}}/debts/{{debts_id}}/payments",
    response_model=PaginatedPaymentsResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener todos los pagos asociados a una deuda específica de un estudiante",
    description="""
    Este endpoint permite obtener todos los pagos realizados para una deuda específica de un estudiante.
    Incluye paginación y la posibilidad de filtrar por estado y rango de fechas.
    """,
    tags=["GET"]
)
async def get_debt_payments(
    student_id: str,
    debts_id: str,
    page: int = Query(default=1, ge=1, description="Número de página"),
    page_size: int = Query(default=10, ge=1, le=100,
                           description="Elementos por página"),
    status: Optional[PaymentStatus] = Query(
        default=None, description="Filtrar por estado del pago"),
    from_date: Optional[datetime] = Query(
        default=None, description="Filtrar pagos desde esta fecha"),
    to_date: Optional[datetime] = Query(
        default=None, description="Filtrar pagos hasta esta fecha"),
    sort_order: Optional[str] = Query(
        default="desc",
        enum=["asc", "desc"],
        description="Orden de clasificación"
    )
):
    try:
        student = payments_collection.find_one({"student_id": student_id})
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Estudiante con ID {student_id} no fue encontrado"
            )

        pipeline = [
            {"$match": {"student_id": student_id}},
            {"$unwind": "$payments"},
            {"$match": {"payments.debt_id": debts_id}}
        ]

        filter_conditions = {}

        if status:
            filter_conditions["payments.status"] = status.value

        if from_date:
            filter_conditions["payments.created_at"] = {"$gte": from_date}
        if to_date:
            filter_conditions["payments.created_at"] = {
                **filter_conditions.get("payments.created_at", {}),
                "$lte": to_date
            }

        if filter_conditions:
            pipeline.append({"$match": filter_conditions})

        count_pipeline = pipeline.copy()
        count_pipeline.append({"$count": "total"})
        total_count = list(payments_collection.aggregate(count_pipeline))
        total = total_count[0]["total"] if total_count else 0

        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se encontraron pagos para la deuda {
                    debts_id} del estudiante {student_id}"
            )

        sort_direction = pymongo.DESCENDING if sort_order == "desc" else pymongo.ASCENDING
        pipeline.extend([
            {"$sort": {"payments.created_at": sort_direction}},
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
            {
                "$project": {
                    "_id": 0,
                    "payment_id": "$payments.payment_id",
                    "debt_id": "$payments.debt_id",
                    "type": "$payments.type",
                    "amount": "$payments.amount",
                    "semester": "$payments.semester",
                    "month": "$payments.month",
                    "year": "$payments.year",
                    "status": "$payments.status",
                    "description": "$payments.description",
                    "created_at": "$payments.created_at",
                    "updated_at": "$payments.updated_at"
                }
            }
        ])

        payments = list(payments_collection.aggregate(pipeline))

        return PaginatedPaymentsResponse(
            total=total,
            page=page,
            page_size=page_size,
            payments=payments
        )

    except HTTPException:
        raise
    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error en la base de datos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Se produjo un error inesperado: {str(e)}"
        )
