from datetime import datetime
import json
import logging
import os
from bson import ObjectId
from fastapi import HTTPException
import pika
import time
from pika.exchange_type import ExchangeType


def get_rabbitmq_connection():
    rabbitmq_url = os.getenv("RABBITMQ_URL")
    logger = logging.getLogger("Connection_RabbitMQ")
    try:
        params = pika.URLParameters(rabbitmq_url)
        connection = pika.BlockingConnection(params)
        logger.info("Connected to RabbitMQ")

        return connection
    except Exception as e:

        logger.info(f"Error connecting to RabbitMQ: {e}")
        return None


def Consumer(service, callback):
    RETRY_DELAY = 5
    RETRY_ATTEMPS = 10
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("Consumer")

    logger.info("Consumer started...")
    logger.info("Connecting to RabbitMQ...")
    connection = get_rabbitmq_connection()
    tries = 0
    while connection is None or tries < RETRY_ATTEMPS:
        logger.info("Retrying connection to RabbitMQ...")
        time.sleep(RETRY_DELAY)
        connection = get_rabbitmq_connection()
        tries += 1
        if (tries == RETRY_ATTEMPS):
            logger.info("Connection to RabbitMQ failed")

    channel = connection.channel()
    channel.exchange_declare(exchange='aranceles',
                             exchange_type=ExchangeType.topic)
    # channel.exchange_declare(exchange='topic_exchange', exchange_type=ExchangeType.topic)
    queue = channel.queue_declare(queue=service, durable=True)
    channel.queue_bind(exchange='aranceles',
                       queue=queue.method.queue, routing_key=f'{service}.*.*')
    channel.basic_consume(queue=queue.method.queue,
                          on_message_callback=callback)
    logger.info('Waiting for messages...')

    try:
        channel.start_consuming()
    except pika.exceptions.ConnectionClosedByBroker:
        logger.info("Conexión cerrada por RabbitMQ, intentando reconectar...")
        Consumer()  # Reintento si RabbitMQ cierra la conexión
    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario.")
        channel.stop_consuming()
    finally:
        connection.close()


def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, ObjectId):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def publish_event(event: str, body: dict):

    connection = get_rabbitmq_connection()
    if connection is None:
        raise HTTPException(
            status_code=500, detail="Cannot connect to RabbitMQ")
    channel = connection.channel()

    # Publicar el evento en RabbitMQ
    channel.basic_publish(
        exchange='aranceles',
        routing_key=event,
        body=json.dumps(body, default=json_serial, ensure_ascii=False),
        # properties=pika.BasicProperties(
        #     delivery_mode=2,  # Hacer el mensaje persistente
        # )
    )
    print(f" [x] Sent to Queue: {event}")
    connection.close()
