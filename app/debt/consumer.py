import json
import os
import time
from fastapi import FastAPI
import pika
from pika.exchange_type import ExchangeType
import requests
import logging
from ..rabbit.main import Consumer

rabbitmq_url = os.getenv("RABBITMQ_URL")
RETRY_DELAY = 5


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Consumer_debt")
url = f"http://debt-container:8003/api/v1/"


def callback(ch, method, properties, body):

    message = json.loads(body)

    event = method.routing_key
    _, debt_id, action = event.split('.')

    if action == "created":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "debt_id": data["debt_id"],
            "type": data["type"],
            "amount": data["amount"],
            "month": data["month"],
            "semester": data["semester"],
            "year": data["year"],
            "description": data["description"]
        }
        try:
            response = requests.post(
                url+f"{student_id}/debts", json=body)
            response.raise_for_status()
            logger.info("✅ Arancel registrado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al registrar el arancel:", e)

    elif action == "updated":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "paid": True
        }
        try:
            if data["type"] == "arancel":
                response = requests.put(
                    url+f"{student_id}/debts/{debt_id}", json=body)
                response.raise_for_status()

            if data["type"] == "matricula":
                enrollment_id = debt_id
                response = requests.put(
                    url+f"{student_id}/enrollments/{enrollment_id}", json=body)
                response.raise_for_status()

            logger.info("✅ Arancel/Matricula actualizado(a)")

        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al actualizar el arancel/matricula:", e)

    elif action == "deleted":
        student_id = message.get("student_id")
        try:
            response = requests.delete(
                url+f"{student_id}/debts/{debt_id}")
            response.raise_for_status()
            logger.info("✅ Arancel/Matricula eliminado(a)")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al eliminar el arancel/matricula:", e)

    ch.basic_ack(delivery_tag=method.delivery_tag)


Consumer("debts", callback)
