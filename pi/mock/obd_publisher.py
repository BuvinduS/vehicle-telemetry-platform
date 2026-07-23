import paho.mqtt.client as mqtt
import json
import time
import math
import random

BROKER_HOST = "localhost"
BROKER_PORT = 1883
TOPIC_OBD   = "telemetry/vehicle/obd"

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(BROKER_HOST, BROKER_PORT)
client.loop_start()

# Simulate VIN not available
client.publish("telemetry/vehicle/info", json.dumps({
    "vin": None,
    "make": None,
    "model": None,
    "year": None,
    "extra_fields": {}
}))

print("Mock OBD publisher started — publishing at 10 Hz")

t = 0.0
try:
    while True:
        speed     = max(0, 60 + 30 * math.sin(t / 20))
        rpm       = max(800, speed * 40 + 1000 + random.gauss(0, 50))
        throttle  = max(0, min(100, 40 + 20 * math.sin(t / 15) + random.gauss(0, 3)))

        obd_payload = {
            "ts":               time.time(),
            "speed_kmh":        round(speed, 1),
            "rpm":              round(rpm),
            "throttle_pct":     round(throttle, 1),
            "coolant_temp_c":   round(85 + random.gauss(0, 1), 1),
            "engine_load_pct":  round(throttle * 0.8, 1),
        }

        client.publish(TOPIC_OBD, json.dumps(obd_payload))

        time.sleep(0.1)
        t += 0.1

except KeyboardInterrupt:
    print("Mock OBD publisher stopped.")
    client.loop_stop()
    client.disconnect()