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
logger = logging.getLogger("Consumer_Payment")
url = f"http://payment-container:8002/api/v1/"


def callback(ch, method, properties, body):

    message = json.loads(body)

    event = method.routing_key
    _, payment_id, action = event.split('.')

    if action == "created":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "amount": data["amount"],
            "debt_id": data["debt_id"],
            "description": data["description"],
            "month": data["month"],
            "payment_id": data["payment_id"],
            "semester": data["semester"],
            "type": data["type"],
            "year": data["year"]
        }
        try:
            response = requests.post(
                url+f"{student_id}/payments", json=body)
            response.raise_for_status()
            logger.info("✅ Pago registrado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al registrar el pago:", e)

    elif action == "updated":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "amount": data["amount"],
            "debt_id": data["debt_id"],
            "description": data["description"],
            "month": data["month"],
            "payment_id": data["payment_id"],
            "semester": data["semester"],
            "type": data["type"],
            "year": data["year"]
        }
        try:
            response = requests.put(
                url+f"{student_id}/payments/{payment_id}", json=body)
            response.raise_for_status()
            logger.info("✅ Pago actualizado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al actualizar el pago:", e)

    elif action == "deleted":
        student_id = message.get("student_id")
        try:
            response = requests.delete(
                url+f"{student_id}/payments/{payment_id}")
            response.raise_for_status()
            logger.info("✅ Pago eliminado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al eliminar el pago:", e)

    ch.basic_ack(delivery_tag=method.delivery_tag)


Consumer("payments", callback)
