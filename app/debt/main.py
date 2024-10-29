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
from ..rabbit.main import publish_event
from typing import Optional, List

rabbitmq_url = os.getenv("RABBITMQ_URL")

load_dotenv()

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["debt"]
debts_collection = db["debt"]

app = FastAPI()
app.include_router(router)

# ----- Schemas ------


class DebtPaid(str, Enum):
    TRUE = True
    FALSE = False


class DebtStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactived"


class Debt(BaseModel):
    debt_id: str
    amount: float
    description: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "debt_id": "DEBT123",
                "amount": 1500.00,
                "description": "Matricula 2024"
            }
        }
    }


class Student(BaseModel):
    student_id: str
    debts: List[Debt] = []


class UpdateDebt(BaseModel):
    amount: Optional[float] = None
    status: Optional[str] = None
    description: Optional[str] = None
    paid: Optional[bool] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "amount": 2000.00,
                "status": "actived",
                "description": "Matricula 2025",
                "paid": False
            }
        }
    }


class DebtResponse(BaseModel):
    debt_id: str
    amount: float
    status: str
    paid: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class PaginatedDebtsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    debts: List[DebtResponse]

# ----------------------End Points-------------------------------

# Registrar aranceles:


@app.post(f"{prefix}/{{student_id}}/debts",
          status_code=status.HTTP_201_CREATED,
          summary="Registrar un arancel para un estudiante",
          description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["POST"])
def store_debt(student_id: str, debt: Debt):
    try:
        existing_debt = debts_collection.find_one(
            {"dets": {"$elemMatch": {"det_id": debt.debt_id}}}
        )

        if existing_debt:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"El arancel con ID {debt.debt_id} ya existe"
            )

        debt_dict = debt.model_dump()
        debt_dict.update({
            "status": "active",
            "created_at": datetime.now(),
            "paid": False
        })

        result = debts_collection.update_one(
            {"student_id": student_id},
            {"$push": {"debts": debt_dict}}
        )

        if result.matched_count == 0:
            new_student = {
                "student_id": student_id,
                "debts": [debt_dict]
            }
            debts_collection.insert_one(new_student)

        student = debts_collection.find_one({"student_id": student_id})
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No se pudo recuperar el estudiante con ID: {
                    student_id}"
            )

        student.pop('_id', None)
        return {"msg": "Arancel registrado correctamente!", "student_debts": student}

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


# Actualizar información de un arancel:

@app.put(
    f"{prefix}/{{student_id}}/debts/{{debt_id}}",
    status_code=status.HTTP_200_OK,
    summary="Actualizar información de un arancel de un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["PUT"]
)
async def update_debt(student_id: str, debt_id: str, update_debt: UpdateDebt):
    try:
        update_data = {
            k: v for k, v in update_debt.model_dump().items()
            if v is not None
        }
        update_data['updated_at'] = datetime.now()

        result = debts_collection.update_one(
            {
                "student_id": student_id,
                "debts.debt_id": debt_id
            },
            {
                "$set": {
                    f"debts.$.{key}": value
                    for key, value in update_data.items()
                }
            }
        )

        if result.matched_count == 0:
            student = debts_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Arancel con ID {
                    debt_id} no encontrado para estudiante {student_id}"
            )

        if result.modified_count == 0:
            return debts_collection.find_one({"student_id": student_id})

        updated_student = debts_collection.find_one(
            {"student_id": student_id})
        if not updated_student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se pudo recuperar el registro actualizado del estudiante"
            )

        updated_student.pop('_id', None)
        return {"msg": "Arancel actualizado correctamente!", "student_updated": updated_student}

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

# Eliminar un arancel:


@app.delete(
    f"{prefix}/{{student_id}}/debts/{{debt_id}}",
    response_model=DebtResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar arancel de un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["DELETE"]
)
async def delete_debt(student_id: str, debt_id: str):
    try:
        try:
            debt = debts_collection.aggregate([
                {"$match": {"student_id": student_id}},
                {"$unwind": "$debts"},
                {"$match": {"debts.debt_id": debt_id}},
                {"$project": {
                    "_id": 0,
                    "status": "$debts.status"
                }}
            ]).next()

        except StopIteration:
            student = debts_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Arancel con ID {
                    debt_id} no encontrado para estudiante {student_id}"
            )
        if debt.get('status') == 'inactived':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Arancel con ID {debt_id} ya fue eliminado"
            )

        update_result = debts_collection.update_one(
            {
                "student_id": student_id,
                "debts.debt_id": debt_id
            },
            {
                "$set": {
                    "debts.$.status": "inactived",
                    "debts.$.updated_at": datetime.now()
                }
            }
        )

        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al eliminar el arancel"
            )

        updated_debt = debts_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$debts"},
            {"$match": {"debts.debt_id": debt_id}},
            {"$project": {
                "_id": 0,
                "debt_id": "$debts.debt_id",
                "amount": "$debts.amount",
                "status": "$debts.status",
                "paid": "$debts.paid",
                "description": "$debts.description",
                "created_at": "$debts.created_at",
                "updated_at": "$debts.updated_at"
            }}
        ]).next()

        return updated_debt

    except StopIteration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se pudo recuperar el arancel actualizado"
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

# Consultar información de un arancel:


@app.get(
    f"{prefix}/{{student_id}}/debts/{{debt_id}}",
    response_model=DebtResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar información de un arancel de un estudiante",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["GET"]
)
async def get_debt(student_id: str, debt_id: str):
    try:
        debt_cursor = debts_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$debts"},
            {"$match": {"debts.debt_id": debt_id}},
            {"$project": {
                "_id": 0,
                "debt_id": "$debts.debt_id",
                "amount": "$debts.amount",
                "status": "$debts.status",
                "apid": "$debts.paid",
                "description": "$debts.description",
                "created_at": "$debts.created_at",
                "updated_at": "$debts.updated_at"
            }}
        ])

        try:
            debt = debt_cursor.next()
        except StopIteration:
            student = debts_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Arancel con ID {
                    debt_id} no encontrado para estudiante {student_id}"
            )

        return debt

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


# Listar todos los aranceles de un estudiante:

@app.get(
    f"{prefix}/{{student_id}}/debts",
    response_model=PaginatedDebtsResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener los aranceles de los estudiantes con paginación y filtros",
    description="""
    (FALTA DESCRIPCIÓN)
    """, tags=["GET"]
)
async def get_debts(
    student_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100,
                           description="Items per page"),
    status: Optional[DebtStatus] = Query(
        default=None, description="Filter by debt status"),
    paid: Optional[DebtPaid] = Query(
        default=None, description="Filter by debt paid"),
    min_amount: Optional[float] = Query(
        default=None, ge=0, description="Minimum debt amount"),
    max_amount: Optional[float] = Query(
        default=None, ge=0, description="Maximum debt amount"),
    from_date: Optional[datetime] = Query(
        default=None, description="Filter debts from this date"),
    to_date: Optional[datetime] = Query(
        default=None, description="Filter debts until this date"),
    sort_by: Optional[str] = Query(
        default="created_at",
        enum=["created_at", "amount", "debt_id"],
        description="Field to sort by"
    ),
    sort_order: Optional[str] = Query(
        default="desc",
        enum=["asc", "desc"],
        description="Sort order"
    )
):
    try:
        student = debts_collection.find_one({"student_id": student_id})
        if not student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Estudiante con ID {student_id} no fue encontrado"
            )
        match_conditions = {"student_id": student_id}
        filter_conditions = {}

        if status:
            filter_conditions["debts.status"] = status.value
        if paid:
            filter_conditions["debts.paid"] = paid.value

        if min_amount is not None:
            filter_conditions["debts.amount"] = {"$gte": min_amount}
        if max_amount is not None:
            filter_conditions["debts.amount"] = {
                **filter_conditions.get("debts.amount", {}),
                "$lte": max_amount
            }

        if from_date:
            filter_conditions["debts.created_at"] = {"$gte": from_date}
        if to_date:
            filter_conditions["debts.created_at"] = {
                **filter_conditions.get("debts.created_at", {}),
                "$lte": to_date
            }

        pipeline = [
            {"$match": match_conditions},
            {"$unwind": "$debts"},
        ]

        if filter_conditions:
            pipeline.append({"$match": filter_conditions})

        sort_direction = pymongo.DESCENDING if sort_order == "desc" else pymongo.ASCENDING
        pipeline.append({"$sort": {f"debts.{sort_by}": sort_direction}})

        count_pipeline = pipeline.copy()
        count_pipeline.append({"$count": "total"})
        total_count = list(debts_collection.aggregate(count_pipeline))
        total = total_count[0]["total"] if total_count else 0

        pipeline.extend([
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
            {
                "$project": {
                    "_id": 0,
                    "debt_id": "$debts.debt_id",
                    "amount": "$debts.amount",
                    "status": "$debts.status",
                    "description": "$debts.description",
                    "created_at": "$debts.created_at",
                    "updated_at": "$debts.updated_at"
                }
            }
        ])

        debts = list(debts_collection.aggregate(pipeline))

        return PaginatedDebtsResponse(
            total=total,
            page=page,
            page_size=page_size,
            debts=debts
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

# Registrar matricula:


@app.post(f"{prefix}/{{student_id}}/enrollments")
def enroll_student(student_id: str, semester: str = Form(...)):
    enrollment_data = {
        "semester": semester,
        "student_id": int(student_id)
    }

    result = db["enrollments"].insert_one(enrollment_data)
    return {"succesfull inster in id": str(result.inserted_id)}

# Actualizar información de una matricula:


@app.put(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def update_enrollment(student_id: str, enrollment_id: str, semester: str = Form(...)):
    enrollment_data = {
        "semester": semester,
        "student_id": int(student_id)
    }
    db["enrollments"].update_one({"_id": ObjectId(enrollment_id)}, {
                                 "$set": enrollment_data})
    return {"Hello": student_id, "Enrollment": enrollment_id}

# Eliminar una matricula:


@app.delete(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def delete_enrollment(student_id: str, enrollment_id: str):
    enrollment_data = db["enrollments"].find_one(
        {"_id": ObjectId(enrollment_id)})
    enrollment_data["_id"] = str(enrollment_data["_id"])
    db["deleted_enrollments"].insert_one(enrollment_data)
    db["enrollments"].delete_one({"_id": ObjectId(enrollment_id)})

    return {"Hello": student_id, "Enrollment": enrollment_id}

# Consultar información de una matricula:


@app.get(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def get_enrollment(student_id: str, enrollment_id: str):
    enrollment = db["enrollments"].find_one({"_id": ObjectId(enrollment_id)})
    enrollment["_id"] = str(enrollment["_id"])
    return enrollment

# Listar todas las matriculas de un estudiante:


@app.get(f"{prefix}/{{student_id}}/enrollments")
def get_enrollments(student_id: str):
    enrollments = db["enrollments"].find({"student_id": int(student_id)})
    enrollments = list(enrollments)
    for enrollment in enrollments:
        enrollment["_id"] = str(enrollment["_id"])
    return enrollments
