import starlette.applications
import starlette.routing
import starlette.responses
import asyncio
import ssl
import json

import app.asyncio_mqtt as amqtt
import app.settings as settings
import app.mqtt as mqtt
import app.utils as utils


async def get_status(request):
    """Return some status information about the server."""

    # test mqtt message
    async with amqtt.Client(
        hostname=settings.MQTT_URL,
        port=8883,
        protocol=amqtt.ProtocolVersion.V5,
        username=settings.MQTT_IDENTIFIER,
        password=settings.MQTT_PASSWORD,
        tls_params=amqtt.TLSParameters(
            tls_version=ssl.PROTOCOL_TLS,
        ),
    ) as client:

        import random

        message = {"timestamp": utils.timestamp(), "value": random.randint(0, 2**10)}
        await client.publish("measurements", payload=json.dumps(message).encode())

    return starlette.responses.JSONResponse(
        {
            "commit_sha": settings.COMMIT_SHA,
            "branch_name": settings.BRANCH_NAME,
            "start_time": settings.START_TIME,
        }
    )


app = starlette.applications.Starlette(
    routes=[
        starlette.routing.Route(
            path="/status",
            endpoint=get_status,
            methods=["GET"],
        ),
    ],
    # startup MQTT client for listening to sensor measurements
    # TODO either limit to one for multiple workers, or use shared subscriptions
    on_startup=[mqtt.startup],
)
