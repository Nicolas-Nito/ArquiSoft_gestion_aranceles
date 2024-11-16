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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Schemas ------


class DebtPaid(str, Enum):
    TRUE = True
    FALSE = False


class DebtStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactived"


class Debt(BaseModel):
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
                "debt_id": "DEBT123",
                "type": "arancel",
                "amount": 1500.00,
                "month": "marzo",
                "semester": "2024-1",
                "year": 2024,
                "description": "Descripción del arancel",
            }
        }
    }


class Student(BaseModel):
    student_id: str
    debts: List[Debt] = []


class UpdateDebt(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = None
    month: Optional[str] = None
    semester: Optional[str] = None
    year: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None
    paid: Optional[bool] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "arancel",
                "amount": 2000.00,
                "month": "marzo",
                "semester": "2024-1",
                "year": 2024,
                "status": "actived",
                "description": "Matricula 2025",
                "paid": False
            }
        }
    }


class DebtResponse(BaseModel):
    debt_id: str
    type: str
    amount: float
    month: str
    semester: str
    year: int
    description: Optional[str] = None
    paid: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class PaginatedDebtsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    debts: List[DebtResponse]


class Enrollment(BaseModel):
    enrollment_id: str
    semester: str
    model_config = {
        "json_schema_extra": {
            "example": {
                "enrollment_id": "ENR123",
                "semester": "2024-1",
            }
        }
    }


class UpdateEnrollment(BaseModel):
    semester: Optional[str] = None
    paid: Optional[bool] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "semester": "2024-1",
                "paid": False
            }
        }
    }


class StudentEnrollment(BaseModel):
    student_id: str
    enrollmets: List[Enrollment] = []
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
    print("ENTRAAAAA")
    try:
        update_data = {
            k: v for k, v in update_debt.model_dump().items()
            if v is not None
        }

        if len(update_data) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se proporcionaron datos para actualizar"
            )

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
                "type": "$debts.type",
                "amount": "$debts.amount",
                "month": "$debts.month",
                "semester": "$debts.semester",
                "year": "$debts.year",
                "status": "$debts.status",
                "paid": "$debts.paid",
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
    description="""(FALTA DESCRIPCIÓN)""",
    tags=["GET"]
)
async def get_debts(
    student_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100, description="Items per page"),
    status: Optional[DebtStatus] = Query(default=None, description="Filter by debt status"),
    paid: Optional[DebtPaid] = Query(default=None, description="Filter by debt paid"),
    min_amount: Optional[float] = Query(default=None, ge=0, description="Minimum debt amount"),
    max_amount: Optional[float] = Query(default=None, ge=0, description="Maximum debt amount"),
    from_date: Optional[datetime] = Query(default=None, description="Filter debts from this date"),
    to_date: Optional[datetime] = Query(default=None, description="Filter debts until this date"),
    sort_by: Optional[str] = Query(default="created_at", enum=["created_at", "amount", "debt_id"], description="Field to sort by"),
    sort_order: Optional[str] = Query(default="desc", enum=["asc", "desc"], description="Sort order")
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

        sort_direction = pymongo.DESCENDING if sort_order == "desc" else pymongo.ASCENDING
        pipeline = [
            {"$match": match_conditions},
            {"$unwind": "$debts"},
            {"$match": filter_conditions} if filter_conditions else {"$match": {}},
            {"$sort": {f"debts.{sort_by}": sort_direction}},
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
            {
                "$project": {
                    "_id": 0,
                    "debt_id": "$debts.debt_id",
                    "type": "$debts.type",
                    "amount": "$debts.amount",
                    "month": "$debts.month",
                    "semester": "$debts.semester",
                    "year": "$debts.year",
                    "description": "$debts.description",
                    "paid": "$debts.paid",
                    "status": "$debts.status",
                    "created_at": "$debts.created_at",
                    "updated_at": "$debts.updated_at",
                }
            }
        ]
        count_pipeline = pipeline.copy()
        count_pipeline.append({"$count": "total"})
        total_count = list(debts_collection.aggregate(count_pipeline))
        total = total_count[0]["total"] if total_count else 0

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
            detail=f"Se produjo un error inesperado: {str(e)}"
        )

# Registrar matricula:


@app.post(
    f"{prefix}/{{student_id}}/enrollments",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una matrícula para un estudiante",
    description="Registra una nueva matrícula para un estudiante específico", tags=["POST"]
)
def enroll_student(student_id: str, enrollment: Enrollment):
    try:
        existing_enrollment = debts_collection.find_one(
            {"enrollments": {"$elemMatch": {"enrollment_id": enrollment.enrollment_id}}}
        )

        if existing_enrollment:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La matrícula con ID {
                    enrollment.enrollment_id} ya existe"
            )

        enrollment_dict = enrollment.model_dump()
        enrollment_dict.update({
            "status": "active",
            "created_at": datetime.now(),
            "paid": False
        })

        result = debts_collection.update_one(
            {"student_id": student_id},
            {"$push": {"enrollments": enrollment_dict}}
        )

        if result.matched_count == 0:
            new_student = {
                "student_id": student_id,
                "enrollments": [enrollment_dict]
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
        return {"msg": "Matrícula registrada correctamente!", "student_enrollments": student}

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

# Actualizar información de una matricula:


@app.put(
    f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}",
    status_code=status.HTTP_200_OK,
    summary="Actualizar información de una matrícula",
    description="Actualiza la información de una matrícula existente", tags=["PUT"]
)
def update_enrollment(student_id: str, enrollment_id: str, enrollment: UpdateEnrollment):
    try:
        update_data = enrollment.model_dump(exclude_unset=True)
        if len(update_data) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se proporcionaron datos para actualizar"
            )

        update_data['updated_at'] = datetime.now()

        result = debts_collection.update_one(
            {
                "student_id": student_id,
                "enrollments.enrollment_id": enrollment_id
            },
            {
                "$set": {
                    f"enrollments.$.{key}": value
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
                detail=f"Matrícula con ID {
                    enrollment_id} no encontrada para estudiante {student_id}"
            )

        updated_student = debts_collection.find_one({"student_id": student_id})
        if not updated_student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se pudo recuperar el registro actualizado del estudiante"
            )

        updated_student.pop('_id', None)
        return {"msg": "Matrícula actualizada correctamente!", "student_updated": updated_student}

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

# Eliminar una matricula:


@app.delete(
    f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar matrícula de un estudiante",
    description="Marca como inactiva una matrícula existente", tags=["DELETE"]
)
def delete_enrollment(student_id: str, enrollment_id: str):
    try:
        try:
            enrollment = debts_collection.aggregate([
                {"$match": {"student_id": student_id}},
                {"$unwind": "$enrollments"},
                {"$match": {"enrollments.enrollment_id": enrollment_id}},
                {"$project": {
                    "_id": 0,
                    "status": "$enrollments.status"
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
                detail=f"Matrícula con ID {
                    enrollment_id} no encontrada para estudiante {student_id}"
            )

        if enrollment.get('status') == 'inactived':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Matrícula con ID {enrollment_id} ya fue eliminada"
            )

        update_result = debts_collection.update_one(
            {
                "student_id": student_id,
                "enrollments.enrollment_id": enrollment_id
            },
            {
                "$set": {
                    "enrollments.$.status": "inactived",
                    "enrollments.$.updated_at": datetime.now()
                }
            }
        )

        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al eliminar la matrícula"
            )

        updated_enrollment = debts_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$enrollments"},
            {"$match": {"enrollments.enrollment_id": enrollment_id}},
            {"$project": {
                "_id": 0,
                "enrollment_id": "$enrollments.enrollment_id",
                "semester": "$enrollments.semester",
                "status": "$enrollments.status",
                "paid": "$enrollments.paid",
                "created_at": "$enrollments.created_at",
                "updated_at": "$enrollments.updated_at"
            }}
        ]).next()

        return updated_enrollment

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

# Consultar información de una matricula:


@app.get(
    f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}",
    status_code=status.HTTP_200_OK,
    summary="Consultar información de una matrícula",
    description="Obtiene la información detallada de una matrícula específica", tags=["GET"]
)
def get_enrollment(student_id: str, enrollment_id: str):
    try:
        enrollment_cursor = debts_collection.aggregate([
            {"$match": {"student_id": student_id}},
            {"$unwind": "$enrollments"},
            {"$match": {"enrollments.enrollment_id": enrollment_id}},
            {"$project": {
                "_id": 0,
                "enrollment_id": "$enrollments.enrollment_id",
                "semester": "$enrollments.semester",
                "status": "$enrollments.status",
                "paid": "$enrollments.paid",
                "created_at": "$enrollments.created_at",
                "updated_at": "$enrollments.updated_at"
            }}
        ])

        try:
            enrollment = enrollment_cursor.next()
        except StopIteration:
            student = debts_collection.find_one({"student_id": student_id})
            if not student:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Estudiante con ID {student_id} no fue encontrado"
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Matrícula con ID {
                    enrollment_id} no encontrada para estudiante {student_id}"
            )

        return enrollment

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

# Listar todas las matriculas de un estudiante:


@app.get(
    f"{prefix}/{{student_id}}/enrollments",
    status_code=status.HTTP_200_OK,
    summary="Listar matrículas de un estudiante",
    description="Obtiene todas las matrículas de un estudiante con opciones de filtrado y paginación", tags=["GET"]
)
def get_enrollments(
    student_id: str,
    page: int = Query(default=1, ge=1, description="Número de página"),
    page_size: int = Query(default=10, ge=1, le=100,
                           description="Elementos por página"),
    status: Optional[str] = Query(
        default=None, description="Filtrar por estado de matrícula"),
    paid: Optional[bool] = Query(
        default=None, description="Filtrar por estado de pago"),
    semester: Optional[str] = Query(
        default=None, description="Filtrar por semestre"),
    sort_by: Optional[str] = Query(
        default="created_at",
        enum=["created_at", "enrollment_id", "semester"],
        description="Campo para ordenar"
    ),
    sort_order: Optional[str] = Query(
        default="desc",
        enum=["asc", "desc"],
        description="Orden de clasificación"
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
            filter_conditions["enrollments.status"] = status
        if paid is not None:
            filter_conditions["enrollments.paid"] = paid
        if semester:
            filter_conditions["enrollments.semester"] = semester

        pipeline = [
            {"$match": match_conditions},
            {"$unwind": "$enrollments"}
        ]

        if filter_conditions:
            pipeline.append({"$match": filter_conditions})

        sort_direction = pymongo.DESCENDING if sort_order == "desc" else pymongo.ASCENDING
        pipeline.append({"$sort": {f"enrollments.{sort_by}": sort_direction}})

        # Count total enrollments
        count_pipeline = pipeline.copy()
        count_pipeline.append({"$count": "total"})
        total_count = list(debts_collection.aggregate(count_pipeline))
        total = total_count[0]["total"] if total_count else 0

        # Add pagination
        pipeline.extend([
            {"$skip": (page - 1) * page_size},
            {"$limit": page_size},
            {
                "$project": {
                    "_id": 0,
                    "enrollment_id": "$enrollments.enrollment_id",
                    "semester": "$enrollments.semester",
                    "status": "$enrollments.status",
                    "paid": "$enrollments.paid",
                    "created_at": "$enrollments.created_at",
                    "updated_at": "$enrollments.updated_at"
                }
            }
        ])

        enrollments = list(debts_collection.aggregate(pipeline))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "enrollments": enrollments
        }

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
