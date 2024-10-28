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
    logger.info(f" [x] Received {message}")
    origin_service = message.get('origin_service')
    if origin_service == "payments":
        logger.info("Ignoring message from the same service")
        return

    event = method.routing_key
    _, id, action = event.split('.')

    if action == "created":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "amount": data["amount"],
            "description": data["description"],
            "payment_id": data["payment_id"]
        }
        try:
            response = requests.post(
                url+f"{student_id}/payments", json=body)
            response.raise_for_status()
            logger.info("Detalles del pago:", response.json())
        except requests.exceptions.RequestException as e:
            logger.info("Error al realizar la request:", e)

        logger.info("[x] Payment created")

    elif action == "updated":

        student_id = message.get("student_id")
        payment_id = message.get("payment_id")
        data = message.get("data")
        body = {
            "amount": data["amount"],
            "description": data["description"],
            "status": data["status"]
        }
        try:
            response = requests.put(
                url+f"{student_id}/payments/{payment_id}", json=body)
            response.raise_for_status()
            logger.info("Detalles del pago actualizado:", response.json())
        except requests.exceptions.RequestException as e:
            logger.info("Error al realizar la request:", e)
        logger.info("[x] Payment updated")

    elif action == "deleted":
        student_id = message.get("student_id")
        payment_id = message.get("payment_id")
        try:
            response = requests.delete(
                url+f"{student_id}/payments/{payment_id}")
            response.raise_for_status()
            logger.info("Detalles del pago elimiado:", response.json())
        except requests.exceptions.RequestException as e:
            logger.info("Error al realizar la request:", e)
        logger.info("[x] Payment deleted")

    ch.basic_ack(delivery_tag=method.delivery_tag)


Consumer("payments", callback)
