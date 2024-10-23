import pika

# Conectarse al servidor RabbitMQ con credenciales
credentials = pika.PlainCredentials('user', 'password')
connection = pika.BlockingConnection(pika.ConnectionParameters('localhost', 5672, '/', credentials))
channel = connection.channel()

# Declarar una cola llamada 'hello'
channel.queue_declare(queue='hello')

# Enviar un mensaje
channel.basic_publish(exchange='', routing_key='hello', body='Hello, World!')
print(" [x] Sent 'Hello, World!'")

# Cerrar la conexión
connection.close()
