from datetime import datetime
import json
import threading
from fastapi import FastAPI, Form, HTTPException
from pydantic import BaseModel


import time
from bson.objectid import ObjectId
import pymongo
import os
from dotenv import load_dotenv
import pika
from pika.exchange_type import ExchangeType

from ..routers.router import prefix, router
from ..rabbit.main import publish_event


rabbitmq_url = os.getenv("RABBITMQ_URL")

load_dotenv()

mongo_client = pymongo.MongoClient("mongodb://mongodb:27017/",
                                   username=os.getenv("MONGO_ADMIN_USER"),
                                   password=os.getenv("MONGO_ADMIN_PASS"))

db = mongo_client["debt"]

app = FastAPI()
app.include_router(router)

# ----------------------End Points-------------------------------


@app.post(f"{prefix}/{{student_id}}/debts")
def store_debt(student_id: str, amount: float = Form(...), description: str = Form(...)):
    # Registrar un pago de un alumno
    debt_data = {
        "amount": amount,
        "date": time.strftime("%Y-%m-%d"),
        "description": description,
        "paid": False,
        "student_id": int(student_id)
    }

    result = db["debts"].insert_one(debt_data)
    debt_id = str(result.inserted_id)
    publish_event(f"debts.{debt_id}.created",
                  {
        "origin_service": "debts",
        "student_id": student_id,
        "data": debt_data
    })

    return {"succesfull inster in id": str(result.inserted_id)}


@app.put(f"{prefix}/{{student_id}}/debts/{{debt_id}}")
def update_debt(student_id: str, debt_id: str, amount: float = Form(...), description: str = Form(...), paid: bool = Form(...)):
    debt_data = {
        "amount": amount,
        "date": time.strftime("%Y-%m-%d"),
        "description": description,
        "student_id": int(student_id),
        "paid": paid
    }
    db["debts"].update_one({"_id": ObjectId(debt_id)}, {"$set": debt_data})
    publish_event(f"debts.{debt_id}.updated",
                  {
        "origin_service": "debts",
        "student_id": student_id,
        "data": debt_data
    })
    return {"Hello": student_id, "Debt": debt_id}


@app.delete(f"{prefix}/{{student_id}}/debts/{{debt_id}}")
def delete_debt(student_id: str, debt_id: str):
    debt_data = db["debts"].find_one({"_id": ObjectId(debt_id)})
    debt_data["_id"] = str(debt_data["_id"])
    db["deleted_debts"].insert_one(debt_data)
    db["debts"].delete_one({"_id": ObjectId(debt_id)})

    publish_event(f"debts.{debt_id}.deleted",
                  {
        "origin_service": "debts",
        "student_id": student_id,
        "debt_id": debt_id
    })
    return {"Hello": student_id, "Debt": debt_id}


@app.get(f"{prefix}/{{student_id}}/debts/{{debt_id}}")
def get_debt(student_id: str, debt_id: str):
    debt = db["debts"].find_one({"_id": ObjectId(debt_id)})
    debt["_id"] = str(debt["_id"])
    return debt


@app.get(f"{prefix}/{{student_id}}/debts")
def get_debts(student_id: str):
    debts = db["debts"].find({"student_id": int(student_id)})
    debts = list(debts)
    for debt in debts:
        debt["_id"] = str(debt["_id"])
    return debts


@app.post(f"{prefix}/{{student_id}}/enrollments")
def enroll_student(student_id: str, semester: str = Form(...)):
    # Registrar un pago de un alumno
    enrollment_data = {
        "semester": semester,
        "student_id": int(student_id)
    }

    result = db["enrollments"].insert_one(enrollment_data)
    return {"succesfull inster in id": str(result.inserted_id)}


@app.put(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def update_enrollment(student_id: str, enrollment_id: str, semester: str = Form(...)):
    enrollment_data = {
        "semester": semester,
        "student_id": int(student_id)
    }
    db["enrollments"].update_one({"_id": ObjectId(enrollment_id)}, {
                                 "$set": enrollment_data})
    return {"Hello": student_id, "Enrollment": enrollment_id}


@app.delete(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def delete_enrollment(student_id: str, enrollment_id: str):
    enrollment_data = db["enrollments"].find_one(
        {"_id": ObjectId(enrollment_id)})
    enrollment_data["_id"] = str(enrollment_data["_id"])
    db["deleted_enrollments"].insert_one(enrollment_data)
    db["enrollments"].delete_one({"_id": ObjectId(enrollment_id)})

    return {"Hello": student_id, "Enrollment": enrollment_id}


@app.get(f"{prefix}/{{student_id}}/enrollments/{{enrollment_id}}")
def get_enrollment(student_id: str, enrollment_id: str):
    enrollment = db["enrollments"].find_one({"_id": ObjectId(enrollment_id)})
    enrollment["_id"] = str(enrollment["_id"])
    return enrollment


@app.get(f"{prefix}/{{student_id}}/enrollments")
def get_enrollments(student_id: str):
    enrollments = db["enrollments"].find({"student_id": int(student_id)})
    enrollments = list(enrollments)
    for enrollment in enrollments:
        enrollment["_id"] = str(enrollment["_id"])
    return enrollments
