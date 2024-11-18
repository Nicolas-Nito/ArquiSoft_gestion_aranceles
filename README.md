# ArquiSoft_gestion_aranceles

-   Ejcutar: docker-compose up



#Para el despliegue en Kubernetes:
    #Despliegue local:
            -Inserta el archivo confidencial "kubeconfig.yaml" en la carpeta del proyecto
            -En el archivo kubernetes reemplaza tokifelipe por [TU-USUARIO-DOCKER]
            -Inicia sesion en docker con tu [TU-USUARIO-DOCKER] : docker login [TU-USUARIO-DOCKER]
            -Desde la carpeta app abrir una terminal y Ejecutar: 
                docker build -t [TU-USUARIO-DOCKER]/tarea-unidad-04:latest -f deploy/local/python.Dockerfile .
                docker push [TU-USUARIO-DOCKER]/tarea-unidad-04:latest
            -Ejecuta el comando:
                 kubectl apply -f kubernetes.yaml
                 kubectl apply -f hpa.yaml

    #Acceso al cluster en ambiente UNIX:
            -Abre una terminal en la carpeta del proyecto y ejecuta: 
                    kubectl --kubeconfig=kubeconfig.yaml get pods
                    export KUBECONFIG=kubeconfig.yaml
                    kubectl get pods
