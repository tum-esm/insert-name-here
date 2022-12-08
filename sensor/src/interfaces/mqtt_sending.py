import datetime
import json
import time
from typing import Callable, Literal
import paho.mqtt.client
from os.path import dirname, abspath, join, isfile
from src import custom_types, utils
import multiprocessing
import multiprocessing.synchronize

PROJECT_DIR = dirname(dirname(dirname(abspath(__file__))))
ACTIVE_QUEUE_FILE = join(PROJECT_DIR, "data", "incomplete-mqtt-messages.json")
QUEUE_ARCHIVE_DIR = join(PROJECT_DIR, "data", "archive")

lock = multiprocessing.Lock()


class SendingMQTTClient:
    sending_loop_process: multiprocessing.Process | None = None

    @staticmethod
    def init_sending_loop_process() -> None:
        # generate an empty queue file if the file does not exist
        with lock:
            if not isfile(ACTIVE_QUEUE_FILE):
                SendingMQTTClient._dump_active_queue(
                    custom_types.ActiveMQTTMessageQueue(
                        max_identifier=0,
                        messages=[],
                    )
                )

        # start the processing of messages in that sending queue
        if SendingMQTTClient.sending_loop_process is None:
            new_process = multiprocessing.Process(
                target=SendingMQTTClient.sending_loop, args=(lock,)
            )
            new_process.start()
            SendingMQTTClient.sending_loop_process = new_process

    @staticmethod
    def enqueue_message(
        config: custom_types.Config,
        message_body: custom_types.MQTTMessageBody,
    ) -> None:
        assert (
            SendingMQTTClient.sending_loop_process is not None
        ), "sending loop process has not been initialized"

        now = time.time()
        with lock:
            active_queue = SendingMQTTClient._load_active_queue()
            new_header = custom_types.MQTTMessageHeader(
                identifier=None,
                status="pending",
                revision=config.revision,
                issue_timestamp=now,
                success_timestamp=None,
            )
            new_message: custom_types.MQTTMessage

            if isinstance(message_body, custom_types.MQTTStatusMessageBody):
                new_message = custom_types.MQTTStatusMessage(
                    header=new_header, body=message_body
                )
            else:
                new_message = custom_types.MQTTMeasurementMessage(
                    header=new_header, body=message_body
                )

            active_queue.messages.append(new_message)
            SendingMQTTClient._dump_active_queue(active_queue)

    @staticmethod
    def _load_active_queue() -> custom_types.ActiveMQTTMessageQueue:
        with open(ACTIVE_QUEUE_FILE, "r") as f:
            active_queue = custom_types.ActiveMQTTMessageQueue(**json.load(f))
        # TODO: when active queue could not be loaded, move file to
        #       "corrupt" directory and start a new active queue file
        return active_queue

    @staticmethod
    def _dump_active_queue(active_queue: custom_types.ActiveMQTTMessageQueue) -> None:
        with open(ACTIVE_QUEUE_FILE, "w") as f:
            json.dump(active_queue.dict(), f, indent=4)

    @staticmethod
    def _archive_delivered_message(
        messages: list[custom_types.MQTTMessage],
    ) -> None:
        modified_lists: dict[str, list[custom_types.MQTTMessage]] = {}
        filename_for_datestring: Callable[[str], str] = lambda date_string: join(
            QUEUE_ARCHIVE_DIR, f"delivered-mqtt-messages-{date_string}.json"
        )

        for m in messages:
            date_string = datetime.datetime.fromtimestamp(
                m.header.issue_timestamp
            ).strftime("%Y-%m-%d")
            if date_string not in modified_lists:
                try:
                    with open(filename_for_datestring(date_string), "r") as f:
                        modified_lists[
                            date_string
                        ] = custom_types.ActiveMQTTMessageQueue(
                            messages=json.load(f)
                        ).messages
                except FileNotFoundError:
                    modified_lists[date_string] = []
                # TODO: move corrupt files
            modified_lists[date_string].append(m)

        for date_string in modified_lists.keys():
            modified_lists[date_string] = list(
                sorted(
                    modified_lists[date_string], key=lambda m: m.header.issue_timestamp
                )
            )
            with open(filename_for_datestring(date_string), "w") as f:
                json.dump(modified_lists[date_string], f, indent=4)

    @staticmethod
    def sending_loop(lock: multiprocessing.synchronize.Lock) -> None:
        """takes messages from the queue file and processes them"""
        logger = utils.Logger(origin="mqtt-sending-loop")
        logger.info("starting loop")

        mqtt_client, mqtt_config = utils.mqtt.get_mqtt_client()

        # this queue is necessary because paho-mqtt does not support
        # a function that answers the question "has this message id
        # been delivered successfully?"
        current_messages: dict[int, paho.mqtt.client.MQTTMessageInfo] = {}

        while True:
            with lock:
                active_queue = SendingMQTTClient._load_active_queue()

            processed_messages: dict[
                Literal["sent", "resent", "delivered"],
                list[custom_types.MQTTMessage],
            ] = {
                "sent": [],
                "resent": [],
                "delivered": [],
            }

            for message in active_queue.messages:

                if message.header.status == "pending":
                    # TODO: adjust message format to server spec (revision, etc.)
                    message_info = mqtt_client.publish(
                        topic=f"{mqtt_config.base_topic}/measurements/{mqtt_config.identifier}",
                        payload=json.dumps([message.body.dict()]),
                        qos=1,
                    )
                    message.header.identifier = message_info.mid
                    message.header.status = "sent"
                    current_messages[message.header.identifier] = message_info
                    processed_messages["sent"].append(message)

                elif message.header.status == "sent":
                    assert message.header.identifier is not None

                    # normal behavior
                    if message.header.identifier in current_messages:
                        if current_messages[message.header.identifier].is_published():
                            message.header.status = "delivered"
                            message.header.success_timestamp = time.time()
                            processed_messages["delivered"].append(message)
                            del current_messages[message.header.identifier]

                    # happens, when current_messages are lost due
                    # to restarting the program
                    else:
                        # TODO: adjust message format to server spec (revision, etc.)
                        message_info = mqtt_client.publish(
                            topic=f"{mqtt_config.base_topic}/measurements/{mqtt_config.identifier}",
                            payload=json.dumps([message.body.dict()]),
                            qos=1,
                        )
                        # TODO: mid might not be unique (tell felix about it)
                        message.header.identifier = message_info.mid
                        current_messages[message.header.identifier] = message_info
                        processed_messages["resent"].append(message)

            # remove successful message from active queue and save
            # them in the archive directory; no lock needed because
            # this is the only process that interacts with the archive
            active_queue.messages = list(
                filter(lambda m: m.header.status != "delivered", active_queue.messages)
            )
            SendingMQTTClient._archive_delivered_message(
                processed_messages["delivered"]
            )

            with lock:
                # add messages that have been added since calling
                # "_load_active_queue" at the beginning of the loop
                new_messages = list(
                    filter(
                        lambda m: m.header.status == "pending",
                        SendingMQTTClient._load_active_queue().messages,
                    )
                )
                active_queue.messages += new_messages
                SendingMQTTClient._dump_active_queue(active_queue)

            for key, value in processed_messages.items():
                logger.info(f"{len(value)} message(s) have been {key}")

            # TODO: adjust wait time based on length of "current_messages"
            time.sleep(5)

    @staticmethod
    def check_errors() -> None:
        """checks whether the sending loop process is still running"""

        if SendingMQTTClient.sending_loop_process is not None:
            assert (
                SendingMQTTClient.sending_loop_process.is_alive()
            ), "sending loop process is not running"

    @staticmethod
    def log_statistics() -> None:
        """logs a few statistics about the current MQTT sending activity"""

        # TODO: log when the last successful message has been sent
        # TODO: log how many messages were sent today
        pass

    # TODO: function "wait_for_message_sending" that blocks until the
    #       active queue is empty
