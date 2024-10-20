from fastapi import APIRouter, HTTPException
from pymongo import MongoClient
from pydantic import BaseModel, Field
from bson import ObjectId
from datetime import datetime
from typing import List
import os

prefix = "/api/v1"

router = APIRouter(
    prefix=prefix,
    tags=["api"],
)
client = MongoClient(
    f"mongodb://admin:admin@mongodb:27017/?authMechanism=DEFAULT")
db = client["tarea-unidad-04"]
benefits_collection = db["benefits"]


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


def publish_event(event: str):
    # Publicar el evento (aquí simplemente imprimimos en consola)
    print(f"Evento publicado: {event}")

# Endpoint: Registrar un beneficio (POST)


@router.post("/{student_id}/benefits", summary="Registrar un Beneficio",
             description="""
  `benefit_id`: ID del beneficio.\n
  `name`: Nombre del beneficio.\n
  `description`: Descripción del beneficio.\n
  `amount`: Valor monetario del beneficio.\n
  `start_date`: Fecha de inicio del beneficio (Ejemplo: 2024-10-20T22:16:23.930Z).\n
  `end_date`: Fecha de finalización del beneficio (Ejemplo: 2024-10-20T22:16:23.930Z).\n
  `status`: Estado del beneficio (Valores esperados: "active", "inactive" o "expired").
""")
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

    return {"msg": "Beneficio registrado exitosamente!"}

# Endpoint: Actualizar información de un beneficio (PUT)


@ router.put("/{student_id}/benefits/{benefit_id}", summary="Actualizar información de un beneficio")
def update_benefit(student_id: str, benefit_id: str, update_benefit: Benefit):
    result = benefits_collection.update_one(
        {"student_id": student_id, "benefits.benefit_id": benefit_id},
        {"$set": {"benefits.$": update_benefit.dict(exclude_unset=True)}}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Beneficio o estudiante no encontrado")

    return {"msg": "Beneficio actualizado exitosamente!"}

# Endpoint: Eliminar un beneficio (DELETE)


@router.delete("/{student_id}/benefits/{benefit_id}", summary="Eliminar un beneficio")
def delete_benefit(student_id: str, benefit_id: str):
    result = benefits_collection.update_one(
        {"student_id": student_id},
        {"$pull": {"benefits": {"benefit_id": benefit_id}}}
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=404, detail="Beneficio o estudiante no encontrado")

    return {"msg": "Beneficio eliminado exitosamente"}

# Endpoint: Consultar información de un beneficio (GET)


@router.get("/{student_id}/benefits/{benefit_id}", summary="Consultar información de un beneficio")
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


@router.get("/{student_id}/benefits")
def list_benefits(student_id: str):
    student = benefits_collection.find_one(
        {"student_id": student_id}, {"benefits": 1})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    return student.get("benefits", [])


# Endpoint: Registrar un pago mediante un beneficio (POST)


@router.post("/{student_id}/benefits/{benefit_id}/payments", summary="Registrar un pago mediante un beneficio")
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

            return {"message": "Pago registrado exitosamente", "payment_id": payment.payment_id}

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")

# Endpoint: Actualizar información de un pago mediante un beneficio (PUT)


@router.put("/{student_id}/benefits/{benefit_id}/payments/{payment_id}", summary="Actualizar información de un pago mediante un beneficio")
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

    return {"message": "Pago actualizado exitosamente"}

# Endpoint: Eliminar un pago mediante un beneficio (DELETE)


@router.delete("/{student_id}/benefits/{benefit_id}/payments/{payment_id}", summary="Eliminar un pago mediante un beneficio")
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

    return {"message": "Pago eliminado exitosamente"}

# Endpoint: Consultar información de un pago mediante un beneficio (GET)


@router.get("/{student_id}/benefits/{benefit_id}/payments/{payment_id}", summary="Consultar información de un pago mediante un beneficio")
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


@router.get("/{student_id}/benefits/{benefit_id}/payments", summary="Listar todos los pagos de un beneficio")
def listar_pagos(student_id: str, benefit_id: str):
    student = benefits_collection.find_one({"student_id": student_id})

    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    for benefit in student["benefits"]:
        if benefit["benefit_id"] == benefit_id:

            if "payments" not in benefit or not benefit["payments"]:
                raise HTTPException(
                    status_code=404, detail="No hay pagos registrados para este beneficio")
            return benefit["payments"]

    raise HTTPException(status_code=404, detail="Beneficio no encontrado")
