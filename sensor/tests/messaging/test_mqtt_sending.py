from datetime import datetime
import json
import os
import time
import pytest
from os.path import dirname, abspath, join
import sys
import deepdiff

from ..pytest_fixtures import (
    mqtt_client_environment,
    mqtt_data_files,
    mqtt_archiving_loop,
    mqtt_sending_loop,
    log_files,
    sample_config,
)
from ..pytest_utils import expect_log_lines, wait_for_condition

PROJECT_DIR = dirname(dirname(dirname(abspath(__file__))))
CONFIG_TEMPLATE_PATH = join(PROJECT_DIR, "config", "config.template.json")
sys.path.append(PROJECT_DIR)

from src import utils, custom_types

ACTIVE_MESSAGES_FILE = join(PROJECT_DIR, "data", "incomplete-mqtt-messages.json")
TEST_MESSAGE_DATE_STRING = datetime.now().strftime("%Y-%m-%d")
MESSAGE_ARCHIVE_FILE = join(
    PROJECT_DIR,
    "data",
    "archive",
    f"delivered-mqtt-messages-{TEST_MESSAGE_DATE_STRING}.json",
)


@pytest.mark.ci
def test_messaging_without_sending(
    mqtt_data_files: None,
    mqtt_archiving_loop: None,
    log_files: None,
    sample_config: None,
) -> None:
    _test_messaging(sending_enabled=False)


@pytest.mark.ci
def test_messaging_with_sending(
    mqtt_data_files: None,
    mqtt_archiving_loop: None,
    mqtt_sending_loop: None,
    log_files: None,
    sample_config: None,
) -> None:
    _test_messaging(sending_enabled=True)


def _test_messaging(sending_enabled: bool) -> None:
    utils.SendingMQTTClient.check_errors()

    active_mqtt_queue = utils.ActiveMQTTQueue()
    sending_mqtt_client = utils.SendingMQTTClient()

    assert len(active_mqtt_queue.get_rows_by_status("pending")) == 0
    assert len(active_mqtt_queue.get_rows_by_status("in-progress")) == 0
    assert len(active_mqtt_queue.get_rows_by_status("done")) == 0

    with open(CONFIG_TEMPLATE_PATH) as f:
        config = custom_types.Config(**json.load(f))
        config.revision = 17
        config.active_components.mqtt_data_sending = sending_enabled

    # enqueue dummy message
    dummy_data_message = custom_types.MQTTDataMessageBody(
        revision=config.revision,
        timestamp=datetime.now().timestamp(),
        value=custom_types.MQTTCO2Data(
            variant="co2",
            data=custom_types.CO2SensorData(
                raw=0.0,
                compensated=0.0,
                filtered=0.0,
            ),
        ),
    )
    sending_mqtt_client.enqueue_message(config, dummy_data_message)

    # assert dummy message to be in active queue
    records = active_mqtt_queue.get_rows_by_status(
        "pending" if sending_enabled else "done"
    )
    assert len(records) == 1
    record = records[0]

    differences = deepdiff.DeepDiff(
        record.content.body.dict(),
        dummy_data_message.dict(),
    )
    print(f"differences = {differences}")
    assert differences == {}

    return

    def empty_active_queue() -> bool:
        with open(ACTIVE_MESSAGES_FILE, "r") as f:
            active_mqtt_message_queue = custom_types.ActiveMQTTMessageQueue(
                **json.load(f)
            )
        return (
            len(active_mqtt_message_queue.messages) == 0
            and active_mqtt_message_queue.max_identifier == 1
        )

    # assert active queue to be empty
    wait_for_condition(
        is_successful=empty_active_queue,
        timeout_seconds=20,
        timeout_message="active queue is not empty after 20 second timeout",
    )

    # assert dummy message to be in archive
    with open(MESSAGE_ARCHIVE_FILE, "r") as f:
        archived_mqtt_messages = custom_types.ArchivedMQTTMessageQueue(
            messages=json.load(f)
        ).messages
    assert len(archived_mqtt_messages) == 1
    assert archived_mqtt_messages[0].header.identifier == 1
    assert archived_mqtt_messages[0].header.status == (
        "delivered" if sending_enabled else "sending-skipped"
    )
    assert (
        deepdiff.DeepDiff(
            archived_mqtt_messages[0].body.dict(),
            dummy_measurement_message.dict(),
        )
        == {}
    )

    # assert that sending loop is still functioning correctly
    utils.SendingMQTTClient.check_errors()
