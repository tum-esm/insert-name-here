import queue
import re
import serial
import time
import threading
from src import utils, types
import gpiozero

# returned when calling "errs"
error_regex = r"OK: No errors detected\."


# returned when powering up the sensor
# TODO

# returned when calling "corr"
# TODO

# returned when calling "average x"/"smooth x"/"median x"/"linear x"
filter_settings_regex = r"(AVERAGE \(s\)|SMOOTH|MEDIAN|LINEAR)\s*:\s(\d{1,3}|ON|OFF)"

# returned when calling "??"
sensor_info_regex = r"\n".join(
    [
        r"GMP343 / \d+\.\d+",
        r"SNUM           : .*",
        r"CALIBRATION    : \d{4}\-\d{4}\-\d{4}",
        r"CAL\. INFO      : .*",
        r"SPAN \(ppm\)     : 1000",
        r"PRESSURE \(hPa\) : \d+\.\d+",
        r"HUMIDITY \(%RH\) : \d+\.\d+",
        r"OXYGEN \(%\)     : \d+\.\d+",
        r"PC             : (ON|OFF)",
        r"RHC            : (ON|OFF)",
        r"TC             : (ON|OFF)",
        r"OC             : (ON|OFF)",
        r"ADDR           : .*",
        r"ECHO           : OFF",
        r"SERI           : 19200 8 NONE 1",
        r"SMODE          : .*",
        r"INTV           : .*",
    ]
)

# TODO: add pressure calibration
# TODO: add humidity calibration
# TODO: add oxygen calibration
# TODO: add temperature calibration


class RS232Interface:
    def __init__(self) -> None:
        self.serial_interface = serial.Serial("/dev/ttySC0", 19200)

    def write(
        self,
        message: str,
        sleep: float | None = None,
    ) -> None:
        self.serial_interface.write((f"\x1B {message}\r\n").encode("utf-8"))
        self.serial_interface.flush()

        if sleep is not None:
            time.sleep(sleep)

    def request(self, command: str, expected_regex: str, timeout: float = 8) -> str:
        # flush receiver stream
        time.sleep(0.2)
        self.serial_interface.read_all()

        # send command
        self.write(command)

        # wait for expected answer
        expected_pattern = re.compile(f"^{expected_regex}$")
        start_time = time.time()
        answer = ""

        while True:
            received_bytes = self.serial_interface.read_all()
            if received_bytes is not None:
                answer += received_bytes.decode(encoding="cp1252")
                if expected_pattern.match(answer) is not None:
                    return answer

            if (time.time() - start_time) > timeout:
                raise TimeoutError(
                    "sensor did not answer as expected: expected_regex "
                    + f"= {repr(expected_regex)}, answer = {repr(answer)}"
                )
            else:
                time.sleep(0.05)


class CO2SensorInterface:
    def __init__(self, config: types.Config, logger: utils.Logger | None = None) -> None:
        self.rs232_interface = RS232Interface()
        self.logger = logger if logger is not None else utils.Logger(config, origin="co2-sensor")
        self.sensor_power_pin = gpiozero.OutputDevice(pin=utils.Constants.co2_sensor.power_pin_out)

        self._reset_sensor()

    def _reset_sensor(self) -> None:
        """will reset the sensors default settings. takes about 6 seconds"""

        self.logger.info("reinitializing default sensor settings")

        self.logger.debug("powering down sensor")
        self.sensor_power_pin.off()
        time.sleep(1)

        self.logger.debug("powering up sensor")
        self.sensor_power_pin.on()
        time.sleep(5)

        self.logger.debug("sending default settings")
        for default_setting in [
            "echo off",
            "range 1",
            'form "Raw " CO2RAWUC " ppm; Comp." CO2RAW " ppm; Filt. " CO2 " ppm"',
        ]:
            self.rs232_interface.write(default_setting)

        # set default filters
        # self.set_filter_setting()

    def set_filter_setting(
        self,
        median: int = 0,
        average: int = 10,
        smooth: int = 0,
        linear: bool = True,
    ) -> None:
        """update the filter settings on the sensor"""

        # TODO: construct a few opinionated measurement setups

        assert average >= 0 and average <= 60, "invalid calibration setting, average not in [0, 60]"
        assert smooth >= 0 and smooth <= 255, "invalid calibration setting, smooth not in [0, 255]"
        assert median >= 0 and median <= 13, "invalid calibration setting, median not in [0, 13]"

        self.rs232_interface.write(f"average {average}")
        self.rs232_interface.write(f"smooth {smooth}")
        self.rs232_interface.write(f"median {median}")
        self.rs232_interface.write(f"linear {'on' if linear else 'off'}", sleep=0.5)
        self.logger.info(
            f"Updating filter settings (average = {average}, smooth"
            + f" = {smooth}, median = {median}, linear = {linear})"
        )

    def get_current_concentration(self) -> types.CO2SensorData:
        answer = self.rs232_interface.request(
            command="send",
            expected_regex=r"Raw\s*\d+\.\d ppm; Comp\.\s*\d+\.\d ppm; Filt\.\s*\d+\.\d ppm>?",
        )
        for s in [" ", "Raw", "ppm", "Comp.", "Filt.", ">"]:
            answer = answer.replace(s, "")
        raw_value_string, comp_value_string, filt_value_string = answer.split(";")
        return types.CO2SensorData(
            raw=float(raw_value_string),
            compensated=float(comp_value_string),
            filtered=float(filt_value_string),
        )

    def log_sensor_info(self) -> None:
        self.rs232_interface.write("??")
        # TODO: wait for sensor answer in an expected regex

    def log_sensor_correction_info(self) -> None:
        self.rs232_interface.write("corr")
        # TODO: wait for sensor answer in an expected regex

    def log_sensor_errors(self) -> None:
        self.rs232_interface.write("errs")
        # TODO: wait for sensor answer in an expected regex
