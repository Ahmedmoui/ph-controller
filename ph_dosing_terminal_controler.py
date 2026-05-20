#!/usr/bin/env python3
"""
pH Dosing Controller -- Atlas Scientific EZO-pH + EZO-PMP
Usage: python3 ph_dosing.py <target_ph> [options]
       python3 ph_dosing.py 7.0 --dose-ml 1.0 --interval 60
"""

import argparse
import logging
import sys
import time

from ph_controller.hardware.ezo_i2c import EZOPH, EZOPump

# -- I2C addresses -- change to match your wiring
PH_SENSOR_ADDR  = 99   # EZO-pH  default: 99  (0x63)
PUMP_UP_ADDR    = 103  # EZO-PMP raising pH (base/alkali):  103 (0x67)
PUMP_DOWN_ADDR  = 114  # EZO-PMP lowering pH (acid):        104 (0x68)
I2C_BUS         = 1    # Raspberry Pi I2C bus

# -- Dosing parameters
DOSE_ML       = 0.5    # mL dosed per correction cycle
DEADBAND      = 0.1    # +/- pH tolerance before dosing triggers
POLL_INTERVAL = 15     # seconds between pH readings
MAX_DOSE_ML   = 2500.0 # safety cap: max cumulative mL per pump per session (2.5 L)


def parse_args():
    p = argparse.ArgumentParser(
        description="Atlas Scientific pH dosing controller",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("target_ph", type=float, help="Target pH value (e.g. 7.0)")
    p.add_argument("--deadband",       type=float, default=DEADBAND,      metavar="PH",  help="+/- pH tolerance before a dose is triggered")
    p.add_argument("--dose-ml",        type=float, default=DOSE_ML,       metavar="ML",  help="Volume to dose per correction cycle (mL)")
    p.add_argument("--interval",       type=int,   default=POLL_INTERVAL, metavar="SEC", help="Seconds between pH readings")
    p.add_argument("--max-dose",       type=float, default=MAX_DOSE_ML,   metavar="ML",  help="Safety cap: max mL per pump per session")
    p.add_argument("--ph-addr",        type=int,   default=PH_SENSOR_ADDR,               help="I2C address of the EZO-pH sensor")
    p.add_argument("--pump-up-addr",   type=int,   default=PUMP_UP_ADDR,                 help="I2C address of pH-UP pump (base/alkali)")
    p.add_argument("--pump-down-addr", type=int,   default=PUMP_DOWN_ADDR,               help="I2C address of pH-DOWN pump (acid)")
    p.add_argument("--bus",            type=int,   default=I2C_BUS,                      help="I2C bus number")
    p.add_argument("--log",            default="ph_dosing.log", metavar="FILE",           help="Log file path")
    return p.parse_args()


def setup_logging(log_path):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _dose(pump, label, dose_ml, dosed, max_dose):
    """Attempt one dose on pump. Returns updated cumulative volume."""
    if dosed + dose_ml > max_dose:
        logging.warning(
            "%s pump session cap %.0f mL reached -- skipping. Restart to reset.", label, max_dose
        )
        return dosed
    if pump.dispense(dose_ml):
        dosed += dose_ml
        logging.info("  Dosed %s %.2f mL  [session total: %.2f mL]", label, dose_ml, dosed)
    else:
        logging.error("  %s pump dose command failed -- check wiring/address.", label)
    return dosed


def main():
    args = parse_args()
    setup_logging(args.log)

    target = args.target_ph
    if not (0.0 <= target <= 14.0):
        logging.error("Target pH %.2f is outside the valid 0-14 range.", target)
        sys.exit(1)

    lo = target - args.deadband
    hi = target + args.deadband

    logging.info("=" * 60)
    logging.info("pH Dosing Controller starting")
    logging.info("  Target pH  : %.2f  (deadband +/-%.2f  ->  %.2f - %.2f)", target, args.deadband, lo, hi)
    logging.info("  Dose size  : %.2f mL  |  Session cap: %.0f mL per pump", args.dose_ml, args.max_dose)
    logging.info("  Poll every : %d s", args.interval)
    logging.info("  I2C bus %d  |  pH: %d  |  UP pump: %d  |  DOWN pump: %d",
                 args.bus, args.ph_addr, args.pump_up_addr, args.pump_down_addr)
    logging.info("  Press Ctrl+C to stop and save session summary.")
    logging.info("=" * 60)

    try:
        sensor    = EZOPH(args.ph_addr,          args.bus, "pH")
        pump_up   = EZOPump(args.pump_up_addr,   args.bus, "UP")
        pump_down = EZOPump(args.pump_down_addr, args.bus, "DOWN")
    except OSError as exc:
        logging.error("Failed to open I2C bus %d: %s", args.bus, exc)
        sys.exit(1)

    dosed_up = dosed_down = 0.0

    try:
        while True:
            ph = sensor.read_ph()

            if ph is None:
                logging.warning("Skipping cycle -- no valid pH reading.")
            else:
                logging.info("pH = %.3f  (target %.2f, delta %+.3f)", ph, target, ph - target)
                if ph < lo:
                    dosed_up   = _dose(pump_up,   "UP (base)",   args.dose_ml, dosed_up,   args.max_dose)
                elif ph > hi:
                    dosed_down = _dose(pump_down, "DOWN (acid)", args.dose_ml, dosed_down, args.max_dose)
                else:
                    logging.info("  pH in range -- no dose needed.")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        logging.info("Shutdown requested -- sending stop to both pumps.")
        pump_up.stop()
        pump_down.stop()

    finally:
        logging.info(
            "Session summary: UP dosed %.2f mL | DOWN dosed %.2f mL", dosed_up, dosed_down
        )
        sensor.close()
        pump_up.close()
        pump_down.close()
        logging.info("All I2C devices closed. Goodbye.")


if __name__ == "__main__":
    main()
