import pika

# Conectarse al servidor RabbitMQ con credenciales
credentials = pika.PlainCredentials('user', 'password')
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost', 5672, '/', credentials))
channel = connection.channel()

# Declarar la cola desde donde recibirá los mensajes
channel.queue_declare(queue='hello')

# Función para procesar los mensajes
def callback(ch, method, properties, body):
    print(f" [x] Received {body}")

# Consumir mensajes de la cola
channel.basic_consume(queue='hello', on_message_callback=callback, auto_ack=True)

print(' [*] Waiting for messages. To exit press CTRL+C')
channel.start_consuming()
