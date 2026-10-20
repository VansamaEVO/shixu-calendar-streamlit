"""Final 40/50/60 profile: offline-only schema, display and validation guards."""
import json
from pathlib import Path
import unittest

from onenet import snapshot, validate_params, OneNetError
from ui import expansion_html
from test_expansion import NOW, props


class FinalMotorProfileTests(unittest.TestCase):
    def test_all_four_actual_states_and_scaled_track(self):
        for level, pwm in enumerate((0, 40, 50, 60)):
            with self.subTest(level=level):
                state = snapshot(props(MotorLevel=level, MotorPWM=pwm), NOW)
                self.assertTrue(state['motor_valid'])
                html = expansion_html(state, True, NOW)
                self.assertIn(f'width:{pwm / 60 * 100:.3f}%', html)
                self.assertIn('最高60% PWM', html)
                self.assertIn('<span>30%</span>', html)
                self.assertNotIn('最高70%', html)
                self.assertEqual(html.count('class="is-selected"'), 1)

    def test_old_profiles_and_wrong_pairs_never_look_live(self):
        for level, pwm in ((1, 25), (1, 30), (2, 40), (2, 55), (3, 55), (3, 70),
                           (2, 60), (3, 50), (0, 40)):
            with self.subTest(level=level, pwm=pwm):
                state = snapshot(props(MotorLevel=level, MotorPWM=pwm), NOW)
                self.assertFalse(state['motor_valid'])
                self.assertIsNone(state['motor_level'])
                self.assertIsNone(state['motor_pwm'])
                html = expansion_html(state, True, NOW)
                self.assertNotIn('class="is-selected"', html)
                self.assertNotIn('width:', html.split('calendar-pwm-track', 1)[1].split('</div>', 1)[0])

    def test_commands_still_accept_only_level_not_duty(self):
        for level in range(4):
            self.assertEqual(validate_params({'MotorTarget': level}), {'MotorTarget': level})
        for params in ({'MotorTarget': 60}, {'MotorTarget': 4}, {'MotorPWM': 60},
                       {'MotorLevel': 3}, {'MotorTarget': 3, 'AlarmMuted': False}):
            with self.assertRaises(OneNetError):
                validate_params(params)

    def test_schema_import_not_required_and_descriptions_fit_onenet(self):
        root = Path(__file__).resolve().parents[1]
        model = json.loads((root / 'docs/thing-model.json').read_text('utf-8'))
        fields = {item['identifier']: item for item in model['properties']}
        self.assertEqual(fields['MotorPWM']['dataType']['specs']['max'], '70')
        self.assertEqual(fields['MotorTarget']['dataType']['specs']['max'], '3')
        self.assertIn('0/40/50/60%', fields['MotorPWM']['desc'])
        self.assertIn('2中50%、3高60%', fields['MotorTarget']['desc'])
        for item in model['properties']:
            self.assertLessEqual(len(item.get('desc', '')), 100, item['identifier'])


if __name__ == '__main__':
    unittest.main()
