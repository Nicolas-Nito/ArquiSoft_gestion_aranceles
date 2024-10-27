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
    # Si el mensaje es de este mismo servicio, lo ignoramos.
    if origin_service == "payments":
        logger.info("Ignoring message from the same service")
        return
    
    event = method.routing_key
    #split the event to get the action
    _,id,action= event.split('.')

    if action == "created":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        try:
            response = requests.post(url+f"{student_id}/payments",data={"amount":data["amount"],"description":data["description"]})
            response.raise_for_status()  # Levanta una excepción si hay error
            logger.info("Detalles del pago:", response.json())
        except requests.exceptions.RequestException as e:
            logger.info("Error al realizar el request:", e)
        # store_payment(student_id, data["amount"], data["description"])       
               
        logger.info("[x] Payment created")

    elif action == "updated":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        update_payment(student_id, id, data["amount"], data["description"])
        logger.info("[x] Payment updated")

    elif action == "deleted":
        # Get the student_id and the data from the message
        student_id = message.get("student_id")
        data = message.get("data")
        # Insert the data into the database
        delete_payment(student_id, id)
        logger.info("[x] Payment deleted")

    ch.basic_ack(delivery_tag=method.delivery_tag)


Consumer("payments",callback)

