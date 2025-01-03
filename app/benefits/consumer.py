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
logger = logging.getLogger("Consumer_Benefit")
url = f"http://benefits-container:8001/api/v1/"


def callback(ch, method, properties, body):

    message = json.loads(body)

    event = method.routing_key
    _, benefit_id, action = event.split('.')

    if action == "created":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "amount": data["amount"],
            "benefit_id": data["benefit_id"],
            "description": data["description"],
            "end_date": data["end_date"],
            "name": data["name"],
            "start_date": data["start_date"],
        }
        try:
            response = requests.post(
                url+f"{student_id}/benefits", json=body)
            response.raise_for_status()
            logger.info("✅ Beneficio registrado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al registrar el beneficio:", e)

        logger.info("[x] benefit created")

    elif action == "updated":
        student_id = message.get("student_id")
        data = message.get("data")
        body = {
            "amount": data["amount"],
            "description": data["description"],
            "end_date": data["end_date"],
            "name": data["name"],
            "start_date": data["start_date"],
            "status": data["status"],
        }
        try:
            response = requests.put(
                url+f"{student_id}/benefist/{benefit_id}", json=body)
            response.raise_for_status()
            logger.info("✅ Beneficio actualizado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al actualizar el beneficio:", e)

    elif action == "deleted":
        student_id = message.get("student_id")
        try:
            response = requests.delete(
                url+f"{student_id}/benefits/{benefit_id}")
            response.raise_for_status()
            logger.info("✅ Beneficio eliminado")
        except requests.exceptions.RequestException as e:
            logger.info("❌ Error al eliminar el beneficio:", e)

    ch.basic_ack(delivery_tag=method.delivery_tag)


Consumer("benefits", callback)
