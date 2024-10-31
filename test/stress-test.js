import http from "k6/http";
import { sleep } from "k6";
import { randomString } from "k6/data";

export const options = {
    stages: [
        { duration: "30s", target: 10 },
        { duration: "1m", target: 10 },
        { duration: "30s", target: 20 },
        { duration: "1m", target: 20 },
        { duration: "30s", target: 0 },
    ],
};

export default function () {
    // Reemplaza EXTERNAL_IP con tu IP externa
    const EXTERNAL_IP = "174.138.126.193";

    // Genera un ID de estudiante aleatorio para cada request
    const student_id = Math.floor(Math.random() * 1000) + 1;

    // Ejemplo de payload para crear un beneficio
    const payload = JSON.stringify({
        benefit_id: "supscription" + student_id,
        amount: 1000.0,
        description: "free supscription",
        start_date: "2024-10-20T22:16:23.930Z",
        end_date: "2024-10-20T22:16:23.930Z",
        name: "Supscription",
    });

    const params = {
        headers: {
            "Content-Type": "application/json",
        },
    };

    const url = `http://${EXTERNAL_IP}:8001/api/v1/${student_id}/benefits`;

    const response = http.post(url, payload, params);
    console.log(`Status: ${response.status}, URL: ${url}, Method: POST`);

    sleep(0.6);
}
