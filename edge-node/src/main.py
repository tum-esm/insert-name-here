import os
import signal
import time
from typing import Any, Optional

from src import custom_types, utils, hardware, procedures


def run() -> None:
    """Entry point for the measurement automation

    (e) Indicates possibility of an exception that blocks further execution

    INIT

    - State Interface
    - Timeouts
    - MQTT Agent
    - Initialize Hardware Interface (e)
    - Initialize Config Procedure (e)
    - Initialize Procedures (e) (System Checks, Calibration, Measurement)

    RUN INFINITE MAIN LOOP
    - Procedure: System Check
    - Procedure: Calibration
    - Procedure: Measurements (CO2, Wind)
    - Check for configuration update
    """
    simulate = os.environ.get("HERMES_MODE") == "simulate"

    logger = utils.Logger(origin="main", print_to_console=simulate)
    logger.horizontal_line()

    try:
        config = utils.ConfigInterface.read()
    except Exception as e:
        logger.exception(e, label="could not load local config.json")
        raise e

    logger.info(
        f"Started new automation process with SW version {config.version} and PID {os.getpid()}.",
        config=config,
    )

    # -------------------------------------------------------------------------

    # check and provide valid state file
    utils.StateInterface.init()

    # define timeouts for parts of the automation
    max_setup_time = 180
    max_config_update_time = 1200
    max_system_check_time = 180
    max_calibration_time = ((len(config.calibration.gas_cylinders) + 1) *
                            config.calibration.sampling_per_cylinder_seconds +
                            300  # flush time
                            + 180  # extra time
                            )
    max_measurement_time = config.measurement.procedure_seconds + 180  # extra time
    utils.set_alarm(max_setup_time, "setup")

    # Exponential backoff time
    ebo = utils.ExponentialBackOff()

    # -------------------------------------------------------------------------
    # initialize mqtt receiver, archiver, and sender (sending is optional)

    try:
        procedures.MQTTAgent.init(config)
    except Exception as e:
        logger.exception(
            e,
            label="Could not start messaging agent.",
            config=config,
        )

    # -------------------------------------------------------------------------
    # initialize all hardware interfaces
    # tear down hardware on program termination

    logger.info("Initializing hardware interfaces.", config=config)

    try:
        hardware_interface = hardware.HardwareInterface(config=config,
                                                        simulate=simulate)
    except Exception as e:
        logger.exception(e,
                         label="Could not initialize hardware interface.",
                         config=config)
        raise e

    # tear down hardware on program termination
    def _graceful_teardown(*_args: Any) -> None:
        utils.set_alarm(10, "graceful teardown")

        logger.info("Start: Graceful teardown.")
        try:
            logger.info("Start: Hardware teardown.")
            hardware_interface.teardown()
            logger.info("Stop: Hardware teardown.")
        except Exception as e:
            logger.exception(e,
                             label="Issue while hardware interface teardown.",
                             config=config)

        try:
            logger.info("Start: MQTT Agent deinit.")
            procedures.MQTTAgent.deinit()
            logger.info("Stop: MQTT Agent deinit.")
        except Exception as e:
            logger.exception(e,
                             label="Issue while MQTT Agent deinit.",
                             config=config)

        logger.info("Stop: Graceful teardown.")

    signal.signal(signal.SIGINT, _graceful_teardown)
    signal.signal(signal.SIGTERM, _graceful_teardown)
    logger.info("Established graceful teardown hook.")

    # -------------------------------------------------------------------------
    # initialize procedures

    # initialize config procedure
    configuration_procedure = procedures.ConfigurationProcedure(
        config, simulate=simulate)

    # initialize procedures interacting with hardware:
    #   system_check:   logging system statistics and reporting hardware/system errors
    #   calibration:    using the two reference gas bottles to calibrate the CO2 sensor
    #   measurements:   do regular measurements for x minutes

    logger.info("Initializing procedures.", config=config)

    try:
        system_check_procedure = procedures.SystemCheckProcedure(
            config, hardware_interface, simulate=simulate)
        calibration_procedure = procedures.CalibrationProcedure(
            config, hardware_interface, simulate=simulate)
        wind_measurement_procedure = procedures.WindMeasurementProcedure(
            config, hardware_interface, simulate=simulate)
        co2_measurement_procedure = procedures.CO2MeasurementProcedure(
            config, hardware_interface, simulate=simulate)
    except Exception as e:
        logger.exception(e,
                         label="could not initialize procedures",
                         config=config)
        raise e

    # -------------------------------------------------------------------------
    # infinite mainloop

    logger.info("Successfully finished setup, starting mainloop.",
                config=config)

    last_successful_mainloop_iteration_time = 0.0
    while True:
        try:
            logger.info("Starting mainloop iteration.")

            # -----------------------------------------------------------------
            # SYSTEM CHECKS

            utils.set_alarm(max_system_check_time, "system check")

            logger.info("Running system checks.")
            system_check_procedure.run()

            # -----------------------------------------------------------------
            # CALIBRATION

            utils.set_alarm(max_calibration_time, "calibration")

            if config.active_components.run_calibration_procedures:
                if calibration_procedure.is_due():
                    logger.info("Running calibration procedure.",
                                config=config)
                    calibration_procedure.run()
                else:
                    logger.info("Calibration procedure is not due.")
            else:
                logger.info("Skipping calibration procedure due to config.")

            # -----------------------------------------------------------------
            # MEASUREMENTS

            utils.set_alarm(max_measurement_time, "measurement")

            # if messages are empty, run regular measurements
            logger.info("Running measurements.")
            wind_measurement_procedure.run()
            co2_measurement_procedure.run()

            # -----------------------------------------------------------------
            # CONFIGURATION

            utils.set_alarm(max_config_update_time, "config update")

            logger.info("Checking for new config messages.")
            new_config_message: Optional[
                custom_types.MQTTConfigurationRequest] = (
                    procedures.MQTTAgent.get_config_message())

            if new_config_message is not None:
                # run config update procedure
                logger.info("Running configuration procedure.", config=config)
                try:
                    configuration_procedure.run(new_config_message)
                    # -> Exit, Restarts via Cron Job to load new config
                except Exception:
                    # reinitialize hardware if configuration failed
                    logger.info("Exception during configuration procedure.",
                                config=config)
                    hardware_interface.reinitialize(config)

            # -----------------------------------------------------------------
            # MQTT Agent Checks

            if config.active_components.send_messages_over_mqtt:
                procedures.MQTTAgent.check_errors()
                # raises CommunicationOutage if communication loop has stopped

            # update state config
            state = utils.StateInterface.read()
            if state.offline_since:
                state.offline_since = None
                utils.StateInterface.write(state)

            # -----------------------------------------------------------------

            logger.info("Finished mainloop iteration.")
            last_successful_mainloop_iteration_time = time.time()

        except procedures.MQTTAgent.CommunicationOutage as e:
            logger.exception(e, label="exception in mainloop")

            # cancel the alarm for too long mainloops
            signal.alarm(0)

            # update state config if first raise
            state = utils.StateInterface.read()
            if not state.offline_since:
                state.offline_since = time.time()
                utils.StateInterface.write(state)

            # reboot if exception lasts longer than 24 hours
            # & the last reboot has been performed longer than 24h ago
            if (time.time() - state.offline_since) >= 86400:
                if utils.read_os_uptime() >= 86400:
                    logger.info(
                        "Rebooting because no successful MQTT connect for 24 hours.",
                        config=config,
                    )
                    os.system("sudo reboot")
                    exit(0)
                else:
                    logger.info(
                        "System is offline. Last reboot is less than 24h ago. No action."
                    )

            try:
                # check timer with exponential backoff
                if time.time() > ebo.next_try_timer():
                    ebo.set_next_timer()
                    # try to establish mqtt connection
                    logger.info(f"Restarting messaging agent.")
                    procedures.MQTTAgent.deinit()
                    procedures.MQTTAgent.init(config)
                    logger.info(
                        f"Performed attempt to restart messaging agent.")
            except Exception as e:
                logger.exception(e, label="Failed to restart messaging agent.")

        except Exception as e:
            logger.exception(e, label="exception in mainloop", config=config)

            # cancel the alarm for too long mainloops
            signal.alarm(0)

            # reboot if exception lasts longer than 24 hours
            # & the last reboot has been performed longer than 24h ago
            if (time.time() -
                    last_successful_mainloop_iteration_time) >= 86400:
                if utils.read_os_uptime() >= 86400:
                    logger.info(
                        "Rebooting because no successful mainloop iteration for 24 hours.",
                        config=config,
                    )
                    os.system("sudo reboot")
                    exit(0)

                else:
                    logger.info(
                        "Persisting exception. Last reboot is less than 24h ago. No action."
                    )

            try:
                # check timer with exponential backoff
                if time.time() > ebo.next_try_timer():
                    ebo.set_next_timer()
                    # reinitialize all hardware interfaces
                    logger.info("Performing hardware reset.", config=config)
                    hardware_interface.teardown()
                    hardware_interface.reinitialize(config)
                    logger.info("Hardware reset was successful.",
                                config=config)

            except Exception as e:
                logger.exception(
                    e,
                    label="exception during hard reset of hardware",
                    config=config,
                )
                exit(1)
