import paho.mqtt.client as mqtt
import json
import time
import random

BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC_IMU   = "telemetry/vehicle/imu"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(BROKER_HOST, BROKER_PORT)
client.loop_start()

print("Mock IMU publisher started — publishing at 10 Hz")

t = 0.0
try:
    while True:
        imu_payload = {
            "ts":       time.time(),
            "accel_x":  round(random.gauss(0, 0.3), 3),
            "accel_y":  round(random.gauss(0, 0.1), 3),
            "accel_z":  round(9.81 + random.gauss(0, 0.05), 3),
        }

        client.publish(TOPIC_IMU, json.dumps(imu_payload))

        time.sleep(0.1)
        t += 0.1

except KeyboardInterrupt:
    print("Mock IMU publisher stopped.")
    client.loop_stop()
    client.disconnect()