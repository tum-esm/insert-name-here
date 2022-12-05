import queue
import time
import gpiozero
import gpiozero.pins.pigpio
from src import utils, custom_types
from src.utils import Constants

rps_measurement_queue: queue.Queue[float] = queue.Queue()


class PumpInterface:
    def __init__(self, config: custom_types.Config) -> None:
        self.logger = utils.Logger(config, "pump")
        self.config = config

        self.pin_factory = utils.gpio.get_pin_factory()
        self.control_pin = gpiozero.PWMOutputDevice(
            pin=Constants.pump.control_pin_out,
            frequency=Constants.pump.frequency,
            active_high=True,
            initial_value=0,
            pin_factory=self.pin_factory,
        )
        self.speed_pin = gpiozero.DigitalInputDevice(
            pin=Constants.pump.speed_pin_in,
            pin_factory=self.pin_factory,
        )
        self.speed_pin.when_activated = lambda: rps_measurement_queue.put(1)

    def set_desired_pump_rps(self, rps: float) -> None:
        """set rps between 0 and 70"""
        assert 0 <= rps <= 70, f"rps have to be between 0 and 70 (passed {rps})"
        self.control_pin.value = rps / 70

    def _get_pump_cycle_count(self) -> float:
        count = 0
        while True:
            try:
                rps_measurement_queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        return count / 18

    def run(self, desired_rps: float, duration: float) -> None:
        assert 2 <= desired_rps <= 70, "pump hardware limitation is 70 rps"
        self._get_pump_cycle_count()  # empty rps_measurement_queue

        self.set_desired_pump_rps(desired_rps)
        time.sleep(duration)
        self.set_desired_pump_rps(0)

        self.logger.info(
            f"duration = {duration}, rps = {desired_rps}, actual "
            + f"average rps = {self._get_pump_cycle_count() / duration}"
        )

        # TODO: log warning when avg rps is differing more than 10% from the desired rps
        # TODO: do rps monitoring without blocking

    def teardown(self) -> None:
        """End all hardware connections"""
        self.pin_factory.close()
