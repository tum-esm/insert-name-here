UPDATE configurations
SET
    acknowledgement_timestamp = {acknowledgement_timestamp},
    ack_reception_timestamp = now(),
    successful = {successful}
WHERE
    sensor_identifier = {sensor_identifier}
    AND revision = {revision}
    AND acknowledgement_timestamp IS NULL;
