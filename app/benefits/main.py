from datetime import datetime
from typing import List, Literal, Optional
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
payment_collection  = client.admin.payment  # Asegúrate de usar la base de datos correcta

app = FastAPI()
app.include_router(router)



class Payment(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    amount: float
    date: datetime = Field(default_factory=datetime.now)
    description: Optional[str] = None
    student_id: str
    benefit_id: str

    class Config:
        json_schema_extra = {
            "example": {
                "amount": 5000.00,
                "date": "2024-01-01T00:00:00",
                "description": "Payment for the scholarship" ,
                "student_id": "123456",
                "benefit_id": "123456"
            }
        }


class Benefit(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    student_id: str
    name: str
    description: str
     #amount float but must be greater or equal to 0
    amount: float = Field(..., ge=0)
    start_date: datetime
    end_date: Optional[datetime] = None
    #status must be one of the following: active, inactive, expired
    status: Literal['active', 'inactive', 'expired'] = "active"    
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
@app.post(f"{prefix}/{{student_id}}/benefits", response_model=Benefit,tags=["POST"])
async def register_benefit(student_id: str, benefit: Benefit):
    benefit.student_id = student_id
    benefit_dict = benefit.dict()
    result = benefits_collection.insert_one(benefit_dict)
    benefit_dict["id"] = str(result.inserted_id)
    return benefit_dict


# Actualizar información de un beneficio
@app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", response_model=Benefit,tags=["PUT"])
async def update_benefit(student_id: str, benefit_id: str, benefit: Benefit):
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$set": benefit.dict(exclude={"id"})}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return {**benefit.dict(), "id": benefit_id}


# Eliminar un beneficio (marcar como inactivo)
@app.delete(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}",tags=["DELETE"])
async def delete_benefit(student_id: str, benefit_id: str):
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$set": {"status": "inactive"}}  # Marcamos como inactivo
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return {"message": "Benefit marked as inactive"}


# Consultar información de un beneficio
@app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}", response_model=Benefit,tags=["GET"])
async def get_benefit(student_id: str, benefit_id: str):
    benefit = benefits_collection.find_one({"_id": ObjectId(benefit_id), "student_id": student_id})
    if benefit is None:
        raise HTTPException(status_code=404, detail="Benefit not found")
    benefit["id"] = str(benefit["_id"])
    return benefit


# Listar todos los beneficios de un estudiante con paginación y filtros
@app.get(f"{prefix}/{{student_id}}/benefits", response_model=List[Benefit],tags=["GET"])
async def list_benefits(student_id: str, skip: int = 0, limit: int = 10, status: Optional[str] = None):
    query = {"student_id": student_id}
    if status:
        query["status"] = status

    benefits = list(benefits_collection.find(query).skip(skip).limit(limit))
    for benefit in benefits:
        benefit["id"] = str(benefit["_id"])
    return benefits


# Registrar un pago mediante un beneficio
@app.post(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments", response_model=Payment,tags=["POST"])
async def register_payment(student_id: str, benefit_id: str, description: Optional[str] = None):

    benefit = benefits_collection.find_one({"_id": ObjectId(benefit_id), "student_id": student_id})
    if benefit is None:
        raise HTTPException(status_code=404, detail="Benefit not found")
    
    amount = benefit["amount"]
    # Crear el pago
    payment = {
        'amount': amount,
        'date': datetime.now(),
        'description': description,
        'student_id': student_id,
        'benefit_id': benefit_id,
    }

    result = payment_collection.insert_one(payment)
    #validar si se inserto el pago
    if result.inserted_id is None:
        raise HTTPException(status_code=500, detail="Error inserting payment")
    payment["_id"] = str(result.inserted_id)


    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$push": {"payments": payment}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Benefit not found")
    return payment


# Actualizar información de un pago mediante un beneficio
@app.put(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", response_model=Payment,tags=["PUT"])
async def update_payment(student_id: str, benefit_id: str, payment_id: str, payment: Payment):
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

    # Actualizar el pago en la colección de pagos
    payment_collection.update_one(
        {"_id": ObjectId(payment_id)},
        {"$set": payment.dict(exclude={"id"})}
    )
    return benefit["payments"][payment_index]


# Eliminar un pago mediante un beneficio
@app.delete(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}",tags=["DELETE"])
async def delete_payment(student_id: str, benefit_id: str, payment_id: str):
    result = benefits_collection.update_one(
        {"_id": ObjectId(benefit_id), "student_id": student_id},
        {"$pull": {"payments": {"id": payment_id}}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Eliminar el pago de la colección de pagos
    payment_collection.delete_one({"_id": ObjectId(payment_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=500, detail="Error deleting payment")
    
    return {"message": "Payment deleted"}


# Consultar información de un pago mediante un beneficio
@app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments/{{payment_id}}", response_model=Payment,tags=["GET"])
async def get_payment(student_id: str, benefit_id: str, payment_id: str):
    #query payments collection
    query = {"student_id": student_id, "benefit_id": benefit_id, "_id": ObjectId(payment_id)}
    payment = payment_collection.find_one(query)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment["id"] = str(payment["_id"])
    return payment


# Listar todos los pagos de un beneficio
@app.get(f"{prefix}/{{student_id}}/benefits/{{benefit_id}}/payments", response_model=List[Payment],tags=["GET"])
async def list_payments(student_id: str, benefit_id: str):
    #query payments collection
    query = {"student_id": student_id, "benefit_id": benefit_id}
    payments = list(payment_collection.find(query))
    if payments is None:
        raise HTTPException(status_code=404, detail="Payments not found")
    
    for payment in payments:
        payment["id"] = str(payment["_id"])
    return payments

    