from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from ..routers.test import prefix, router
from pymongo import MongoClient
from pydantic import BaseModel, Field
from bson.objectid import ObjectId

import os

# Obtener las credenciales desde el entorno
mongo_user = os.getenv("MONGO_ADMIN_USER")
mongo_pass = os.getenv("MONGO_ADMIN_PASS")

# Asegúrate de que la URI esté configurada correctamente
mongo_uri = f"mongodb://{mongo_user}:{mongo_pass}@mongodb:27017/admin"  # Nota: se agrega /admin


# Conectar a la base de datos MongoDB
client = MongoClient(mongo_uri)  # Usa la URI con las credenciales
benefits_collection  = client.admin.benefit  # Asegúrate de usar la base de datos correcta

app = FastAPI()
app.include_router(router)



class Payment(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    amount: float
    date: datetime = Field(default_factory=datetime.now)
    description: Optional[str] = None


class Benefit(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    student_id: str
    name: str
    description: str
    amount: float
    start_date: datetime
    end_date: Optional[datetime] = None
    status: str = "active"  # active, inactive, expired
    max_recipients: Optional[int] = None
    current_recipients: int = 0
    category: str  # financial, academic, housing, etc.
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    payments: List[Payment] = []  # Lista de pagos asociados al beneficio

    class Config:
        json_schema_extra = {
            "example": {
                "student_id": "123456",
                "name": "Merit Scholarship",
                "description": "Academic excellence scholarship",
                "amount": 5000.00,
                "start_date": "2024-01-01T00:00:00",
                "category": "financial"
            }
        }


# Registrar un beneficio
@app.post("/api/v1/{student_id}/benefits", response_model=Benefit)
def register_benefit(student_id: str, benefit: Benefit):
    benefit.student_id = student_id
    benefit_dict = benefit.dict()
    result = benefits_collection.insert_one(benefit_dict)
    benefit_dict["id"] = str(result.inserted_id)
    return benefit_dict


# Actualizar información de un beneficio
@app.put("/api/v1/{student_id}/benefits/{benefit_id}", response_model=Benefit)
def update_benefit(student_id: str, benefit_id: str, benefit: Benefit):
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$set": benefit.dict(exclude={"id"})}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return {**benefit.dict(), "id": benefit_id}


# Eliminar un beneficio (marcar como inactivo)
@app.delete("/api/v1/{student_id}/benefits/{benefit_id}")
def delete_benefit(student_id: str, benefit_id: str):
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$set": {"status": "inactive"}}  # Marcamos como inactivo
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return {"message": "Benefit marked as inactive"}


# Consultar información de un beneficio
@app.get("/api/v1/{student_id}/benefits/{benefit_id}", response_model=Benefit)
def get_benefit(student_id: str, benefit_id: str):
    benefit = benefits_collection.find_one({"_id": ObjectId(benefit_id), "student_id": student_id})
    if benefit is None:
        raise HTTPException(status_code=404, detail="Benefit not found")
    benefit["id"] = str(benefit["_id"])
    return benefit


# Listar todos los beneficios de un estudiante con paginación y filtros
@app.get("/api/v1/{student_id}/benefits", response_model=List[Benefit])
def list_benefits(student_id: str, skip: int = 0, limit: int = 10, status: Optional[str] = None):
    query = {"student_id": student_id}
    if status:
        query["status"] = status

    benefits = list(benefits_collection.find(query).skip(skip).limit(limit))
    for benefit in benefits:
        benefit["id"] = str(benefit["_id"])
    return benefits


# Registrar un pago mediante un beneficio
@app.post("/api/v1/{student_id}/benefits/{benefit_id}/payments", response_model=Payment)
def register_payment(student_id: str, benefit_id: str, payment: Payment):
    payment_dict = payment.dict()
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$push": {"payments": payment_dict}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return payment_dict


# Actualizar información de un pago mediante un beneficio
@app.put("/api/v1/{student_id}/benefits/{benefit_id}/payments/{payment_id}", response_model=Payment)
def update_payment(student_id: str, benefit_id: str, payment_id: str, payment: Payment):
    benefit = benefits_collection.find_one({"_id": ObjectId(benefit_id), "student_id": student_id})
    if benefit is None:
        raise HTTPException(status_code=404, detail="Benefit not found")

    payment_index = next((index for index, p in enumerate(benefit["payments"]) if p["id"] == payment_id), None)
    if payment_index is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    benefit["payments"][payment_index].update(payment.dict(exclude={"id"}))
    benefits_collection.update_one(
        {"_id": ObjectId(benefit_id)},
        {"$set": {"payments": benefit["payments"]}}
    )
    return benefit["payments"][payment_index]


# Eliminar un pago mediante un beneficio
@app.delete("/api/v1/{student_id}/benefits/{benefit_id}/payments/{payment_id}")
def delete_payment(student_id: str, benefit_id: str, payment_id: str):
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$pull": {"payments": {"id": payment_id}}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"message": "Payment deleted"}


# Consultar información de un pago mediante un beneficio
@app.get("/api/v1/{student_id}/benefits/{benefit_id}/payments/{payment_id}", response_model=Payment)
def get_payment(student_id: str, benefit_id: str, payment_id: str):
    benefit = benefits_collection.find_one({"_id": ObjectId(benefit_id), "student_id": student_id})
    if benefit is None:
        raise HTTPException(status_code=404, detail="Benefit not found")

    payment = next((p for p in benefit["payments"] if p["id"] == payment_id), None)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    return payment


# Listar todos los pagos de un beneficio
@app.get("/api/v1/{student_id}/benefits/{benefit_id}/payments", response_model=List[Payment])
def list_payments(student_id: str, benefit_id: str):
    benefit = benefits_collection.find_one({"_id": ObjectId(benefit_id), "student_id": student_id})
    if benefit is None:
        raise HTTPException(status_code=404, detail="Benefit not found")

    return benefit["payments"]