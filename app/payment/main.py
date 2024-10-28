from datetime import datetime
import json
import threading
from fastapi import FastAPI, Form, HTTPException, status, Query
from pydantic import BaseModel

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

# ----- Schemas ------


class PaymentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactived"


class Payment(BaseModel):
    payment_id: str
    amount: float
    description: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "payment_id": "PAY123",
                "amount": 1500.00,
                "description": "Matricula 2024"
            }
        }
    }


class Student(BaseModel):
    student_id: str
    payments: List[Payment] = []


class UpdatePayment(BaseModel):
    amount: Optional[float] = None
    status: Optional[str] = None
    description: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "amount": 2000.00,
                "status": "actived",
                "description": "Matricula 2025"
            }
        }
    }


class PaymentResponse(BaseModel):
    payment_id: str
    amount: float
    status: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class PaginatedPaymentsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    payments: List[PaymentResponse]

# ----------------------End Points-------------------------------


@app.post(
    f"{prefix}/{{student_id}}/payments",
    response_model=Student,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un pago para un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["POST"]
)
async def store_payment(student_id: str, payment: Payment):
    try:
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
        return student

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


@app.put(
    f"{prefix}/{{student_id}}/payments/{{payment_id}}",
    response_model=Student,
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
                detail=f"Payment with ID {
                    payment_id} not found for student {student_id}"
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
        return updated_student

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
        payment = payments_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$payments"},
            {"$match": {"payments.payment_id": payment_id}},
            {"$project": {
                "_id": 0,
                "status": "$payments.status"
            }}
        ]).next()

        if not payment:
            student = payments_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estdiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment with ID {
                    payment_id} not found for student {student_id}"
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
                    "payments.$.updated_at": datetime.utcnow()
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
                "amount": "$payments.amount",
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
                    "amount": "$payments.amount",
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


@app.get(
    f"{prefix}/{{student_id}}/payments/{{payment_id}}",
    response_model=PaymentResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener información de pago específica",
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
                "amount": "$payments.amount",
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
                    detail=f"Student with ID {student_id} not found"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment with ID {
                    payment_id} not found for student {student_id}"
            )

        return payment

    except HTTPException:
        raise
    except pymongo.errors.PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error occurred: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}"
        )


@app.get(f"{prefix}/{{student_id}}/debts/{{debts_id}}/payments", tags=["GET"])
def get_debt_payments(student_id: str, payment_id: str):
    return {"msg": "Endpoint no implementado"}
