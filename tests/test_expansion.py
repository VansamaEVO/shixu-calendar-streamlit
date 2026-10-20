"""Stage31 read-only telemetry; no real network, serial or device writes."""
from pathlib import Path
import json
import unittest

from onenet import OneNetError, snapshot, validate_params
from ui import expansion_html

NOW = 1_791_610_000_000


def props(**overrides):
    values = dict(McuOnline=True, AlcoholValid=True, AlcoholRaw=1933,
                  MotorValid=True, MotorLevel=2, MotorPWM=50)
    values.update(overrides)
    return [dict(identifier=k, value=v, time=NOW - 1000) for k, v in values.items()]


class ExpansionTests(unittest.TestCase):
    def test_all_adc_values_match_lcd_and_bluetooth(self):
        for raw in range(4096):
            value = snapshot(props(AlcoholRaw=raw), NOW)
            self.assertTrue(value['alcohol_valid'])
            self.assertEqual(value['alcohol_voltage'], (((raw >> 3) * 125) >> 7) / 100)
            self.assertEqual(value['alcohol_index'], (raw * 100 + 2047) // 4095)
            self.assertEqual(value['alcohol_raw'], raw)

    def test_motor_actual_gears_and_zero_are_not_missing(self):
        for level, pwm in enumerate((0, 40, 50, 60)):
            value = snapshot(props(MotorLevel=level, MotorPWM=pwm, AlcoholRaw=0), NOW)
            self.assertTrue(value['motor_valid'])
            self.assertEqual(value['motor_level'], level)
            self.assertEqual(value['motor_pwm'], pwm)
            self.assertEqual(value['alcohol_voltage'], 0)
            html = expansion_html(value, True, NOW)
            self.assertIn(('停止', '低档', '中档', '高档')[level], html)
            self.assertIn('0.00', html)

    def test_bad_raw_or_flags_do_not_look_valid(self):
        for raw in (-1, 4096, True, None, '', '01', ' 12', '12.0', '1e2', '0x12', float('nan')):
            value = snapshot(props(AlcoholRaw=raw), NOW)
            self.assertFalse(value['alcohol_valid'], repr(raw))
            self.assertIsNone(value['alcohol_raw'])
            self.assertTrue(value['motor_valid'])
        for flag in (False, None, 'invalid', 2):
            self.assertFalse(snapshot(props(AlcoholValid=flag), NOW)['alcohol_valid'])

    def test_motor_rejects_malformed_or_inconsistent_pwm(self):
        for level, pwm in ((4, 70), (1, 55), (True, 40), ('01', 40), (0, None), (1, '40.0')):
            value = snapshot(props(MotorLevel=level, MotorPWM=pwm), NOW)
            self.assertFalse(value['motor_valid'])
            self.assertIsNone(value['motor_level'])
            self.assertTrue(value['alcohol_valid'])

    def test_new_flags_and_timestamps_are_independent(self):
        for key in ('AlcoholRaw', 'AlcoholValid', 'MotorLevel', 'MotorPWM', 'MotorValid'):
            for age in (1001, 19000):
                values = props()
                next(v for v in values if v['identifier'] == key)['time'] -= age
                result = snapshot(values, NOW)
                self.assertFalse(result['alcohol_valid' if key.startswith('Alcohol') else 'motor_valid'])
                self.assertTrue(result['motor_valid' if key.startswith('Alcohol') else 'alcohol_valid'])
        for key in ('AlcoholValid', 'AlcoholRaw', 'MotorLevel', 'MotorPWM', 'MotorValid'):
            result = snapshot([v for v in props() if v['identifier'] != key], NOW)
            self.assertFalse(result['alcohol_valid' if key.startswith('Alcohol') else 'motor_valid'])

    def test_offline_stale_missing_data_never_fake_stopped(self):
        for values in ([], props(McuOnline=False), [dict(v, time=NOW - 20000) for v in props()]):
            result = snapshot(values, NOW)
            self.assertFalse(result['alcohol_valid'])
            self.assertFalse(result['motor_valid'])
            html = expansion_html(result, result['online'], NOW)
            self.assertNotIn('>停止<', html)
            self.assertNotIn('>0.00<', html)
            self.assertNotIn('is-selected', html)

    def test_read_only_and_escaped_no_fake_ppm(self):
        result = snapshot(props(), NOW)
        html = expansion_html(result, True, NOW)
        self.assertNotIn('<button', html)
        self.assertNotIn('<input', html)
        self.assertNotIn('ppm', html.lower())
        self.assertIn('未标定', html)
        self.assertIn('非实测转速', html)
        for params in ({'MotorLevel': 1}, {'MotorPWM': 40}, {'AlcoholRaw': 1}):
            with self.assertRaises(OneNetError):
                validate_params(params)

    def test_model_preserves_old_properties_and_seven_readonly_additions(self):
        model = json.loads((Path(__file__).resolve().parents[1] / 'docs/thing-model.json').read_text('utf-8'))
        fields = {p['identifier']: p for p in model['properties']}
        for name in ('AlcoholRaw', 'AlcoholVoltage', 'AlcoholIndex', 'AlcoholValid', 'MotorLevel', 'MotorPWM', 'MotorValid'):
            self.assertEqual(fields[name]['accessMode'], 'r')
        for name in ('TemperatureLow', 'TemperatureHigh', 'HumidityLow', 'HumidityHigh', 'DeviceTime', 'AlarmMuted'):
            self.assertEqual(fields[name]['accessMode'], 'rw')


if __name__ == '__main__':
    unittest.main()
