from datetime import datetime
import math
import time
from src import custom_types, utils, hardware


# TODO: refactor calibration and measurement procedure to use same base class


class CalibrationProcedure:
    """runs when a calibration is due"""

    def __init__(
        self, config: custom_types.Config, hardware_interface: hardware.HardwareInterface
    ) -> None:
        self.logger, self.config = utils.Logger(origin="calibration-procedure"), config
        self.hardware_interface = hardware_interface

        # state variables
        self.last_measurement_time: float = 0
        self.message_queue = utils.MessageQueue()

    def _update_air_inlet_parameters(self) -> None:
        """
        1. fetches the latest temperature and pressure data at air inlet
        2. sends these values to the CO2 sensor
        """

        self.air_inlet_bme280_data = self.hardware_interface.air_inlet_bme280_sensor.get_data()
        self.air_inlet_sht45_data = self.hardware_interface.air_inlet_sht45_sensor.get_data()
        self.chamber_temperature = (
            self.hardware_interface.co2_sensor.get_current_chamber_temperature()
        )

        # update CO2 sensor compenstation info
        self.hardware_interface.co2_sensor.set_compensation_values(
            humidity=self.air_inlet_sht45_data.humidity,
            pressure=self.air_inlet_bme280_data.pressure,
        )

    def _alternate_bottle_for_drying(self) -> None:
        """1. sets time for drying the air chamber with first calibration bottle
        2. switches order of calibration bottles every other day"""

        # set time extension for first bottle
        self.seconds_drying_with_first_bottle = (
            self.config.calibration.timing.seconds_per_gas_bottle
        )

        # alternate order every other day
        days_since_unix = (datetime.now().date() - datetime(1970, 1, 1).date()).days
        alternate_order = days_since_unix % 2 == 1

        if alternate_order:
            self.sequence_calibration_bottle = self.config.calibration.gases[::-1]
        else:
            self.sequence_calibration_bottle = self.config.calibration.gases

    def run(self) -> None:
        calibration_time = datetime.utcnow().timestamp()
        self.logger.info(
            f"starting calibration procedure at timestamp {calibration_time}",
            config=self.config,
        )

        # alternate calibration bottle order every other day
        # first bottle receives additional time to dry air chamber
        self._alternate_bottle_for_drying()

        for gas in self.sequence_calibration_bottle:
            # switch to each calibration valve
            self.hardware_interface.valves.set_active_input(gas.valve_number)
            calibration_procedure_start_time = time.time()

            while True:
                # idle until next measurement period
                seconds_to_wait_for_next_measurement = max(
                    self.config.measurement.timing.seconds_per_measurement
                    - (time.time() - self.last_measurement_time),
                    0,
                )
                self.logger.debug(
                    f"sleeping {round(seconds_to_wait_for_next_measurement, 3)} seconds"
                )
                time.sleep(seconds_to_wait_for_next_measurement)
                self.last_measurement_time = time.time()

                # update air inlet parameters
                self._update_air_inlet_parameters()

                # perform a CO2 measurement
                current_sensor_data = self.hardware_interface.co2_sensor.get_current_concentration()
                self.logger.debug(f"new calibration measurement")

                # send out MQTT measurement message
                self.message_queue.enqueue_message(
                    self.config,
                    custom_types.MQTTDataMessageBody(
                        revision=self.config.revision,
                        timestamp=round(time.time(), 2),
                        value=custom_types.MQTTCalibrationData(
                            variant="calibration",
                            data=custom_types.CalibrationProcedureData(
                                gas_bottle_id=gas.bottle_id,
                                raw=current_sensor_data.raw,
                                compensated=current_sensor_data.compensated,
                                filtered=current_sensor_data.filtered,
                                bme280_temperature=self.air_inlet_bme280_data.temperature,
                                bme280_humidity=self.air_inlet_bme280_data.humidity,
                                bme280_pressure=self.air_inlet_bme280_data.pressure,
                                sht45_temperature=self.air_inlet_sht45_data.temperature,
                                sht45_humidity=self.air_inlet_sht45_data.humidity,
                                chamber_temperature=self.chamber_temperature,
                            ),
                        ),
                    ),
                )

                if (
                    (self.last_measurement_time - calibration_procedure_start_time)
                    >= self.config.calibration.timing.seconds_per_gas_bottle
                    + self.seconds_drying_with_first_bottle
                ):
                    break

            # reset drying time extension for following bottles
            self.seconds_drying_with_first_bottle = 0

        # switch back to measurement inlet
        # TODO: clean up the hard coded first measurement inlet
        self.hardware_interface.valves.set_active_input(
            self.config.measurement.air_inlets[0].valve_number
        )

        # save last calibration time
        self.logger.debug("finished calibration: updating state")
        state = utils.StateInterface.read()
        state.last_calibration_time = calibration_time
        utils.StateInterface.write(state)

    def is_due(self) -> bool:
        """returns true when calibration procedure should run now"""

        # load state, kept during configuration procedures
        state = utils.StateInterface.read()
        current_utc_timestamp = datetime.utcnow().timestamp()

        # if last calibration time is unknown, calibrate now
        # should only happen when the state.json is not copied
        # during the upgrade routine or its interface changes
        if state.last_calibration_time is None:
            self.logger.info("last calibration time is unknown, calibrating now")
            return True

        seconds_between_calibrations = (
            3600 * self.config.calibration.timing.hours_between_calibrations
        )
        calibrations_since_start_time = math.floor(
            (current_utc_timestamp - self.config.calibration.timing.start_timestamp)
            / seconds_between_calibrations
        )
        last_calibration_time = (
            calibrations_since_start_time * seconds_between_calibrations
            + self.config.calibration.timing.start_timestamp
        )

        if state.last_calibration_time > last_calibration_time:
            self.logger.info("last calibration is up to date")
            return False

        # skip calibration when sensor has had power for less than 30
        # minutes (a full warming up is required for maximum accuracy)
        seconds_since_last_co2_sensor_boot = round(
            time.time() - self.hardware_interface.co2_sensor.last_powerup_time, 2
        )
        if seconds_since_last_co2_sensor_boot < 1800:
            self.logger.info(
                f"skipping calibration, sensor is still warming up (co2 sensor"
                + f" booted {seconds_since_last_co2_sensor_boot} seconds ago)"
            )
            return False

        self.logger.info(
            "last calibration is older than last calibration due date, calibrating now"
        )
        return True
