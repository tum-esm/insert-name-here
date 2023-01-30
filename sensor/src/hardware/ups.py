from src import utils, custom_types
import gpiozero

UPS_READY_PIN_IN = 5
UPS_BATTERY_MODE_PIN_IN = 10
UPS_ALARM_PIN_IN = 7


class UPSInterface:
    def __init__(self, config: custom_types.Config):
        self.logger, self.config = utils.Logger("ups"), config
        self.logger.info("Starting initialization")

        # use underlying pigpio library
        self.pin_factory = utils.get_gpio_pin_factory()

        # pin goes high if the system is powered by the UPS battery
        mode_input = gpiozero.DigitalInputDevice(
            UPS_BATTERY_MODE_PIN_IN,
            bounce_time=0.3,
            pin_factory=self.pin_factory,
        )
        mode_input.when_activated = lambda: self.logger.warning(
            "system is powered by battery", config=self.config
        )
        mode_input.when_deactivated = lambda: self.logger.info(
            "system is powered externally"
        )

        # pin goes high if the battery has any error or has been disconected
        alarm_input = gpiozero.DigitalInputDevice(
            UPS_ALARM_PIN_IN, bounce_time=0.3, pin_factory=self.pin_factory
        )
        alarm_input.when_activated = lambda: self.logger.warning(
            "battery error detected", config=self.config
        )
        alarm_input.when_deactivated = lambda: self.logger.info("battery status is ok")

        def _on_battery_is_ready() -> None:
            if mode_input.is_active:
                self.logger.error("battery voltage is under threshold", config=config)
                # TODO: https://github.com/tum-esm/insert-name-here/issues/33
            else:
                self.logger.info("battery is fully charged")

        # pin goes high if the battery is empty or fully charged (two thresholds like 10% and 90%)
        ready_input = gpiozero.DigitalInputDevice(
            UPS_READY_PIN_IN, bounce_time=0.3, pin_factory=self.pin_factory
        )
        ready_input.when_activated = _on_battery_is_ready

        self.logger.info("Finished initialization")

    def teardown(self) -> None:
        """ends all hardware/system connections"""
        self.pin_factory.close()
