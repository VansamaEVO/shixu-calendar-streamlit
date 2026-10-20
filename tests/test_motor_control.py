"""Stage32 motor cloud command tests: offline, mocked network only."""
import json
import unittest
from onenet import snapshot, validate_params, OneNetError, _state_matches
from test_onenet import NOW, properties, client, ok


def motor_properties(at=NOW-1000, **overrides):
    values=dict(MotorTarget=0,MotorLevel=0,MotorPWM=0,MotorValid=True)
    values.update(overrides)
    return properties(at=at)+[dict(identifier=k,value=v,time=at) for k,v in values.items()]


class MotorCloudTests(unittest.TestCase):
    def test_only_four_integer_gears_and_no_direct_pwm_or_actual_write(self):
        for level in range(4):
            self.assertEqual(validate_params({'MotorTarget':level}),{'MotorTarget':level})
        for bad in (-1,4,70,True,False,None,'1',1.5,{},[]):
            with self.assertRaises(OneNetError):validate_params({'MotorTarget':bad})
        for params in ({'MotorTarget':1,'AlarmMuted':False},{'MotorLevel':1},{'MotorPWM':40}):
            with self.assertRaises(OneNetError):validate_params(params)

    def test_readiness_requires_actual_fresh_motor_model_and_original_controls(self):
        self.assertTrue(snapshot(motor_properties(),NOW)['motor_control_ready'])
        for values in (properties(),motor_properties(MotorValid=False),motor_properties(MotorPWM=40),
                       motor_properties(ControlReady=False),motor_properties(McuOnline=False),
                       [p for p in motor_properties() if p['identifier']!='MotorTarget']):
            self.assertFalse(snapshot(values,NOW)['motor_control_ready'])

    def test_actual_new_state_not_target_echo_is_required(self):
        baseline=motor_properties()
        self.assertFalse(_state_matches(motor_properties(MotorTarget=2),{'MotorTarget':2},NOW,NOW,baseline))
        self.assertFalse(_state_matches(motor_properties(MotorLevel=2,MotorPWM=50),{'MotorTarget':2},NOW,NOW,baseline))
        returned=motor_properties(at=NOW+1000,MotorLevel=2,MotorPWM=50,MotorTarget=0)
        self.assertTrue(_state_matches(returned,{'MotorTarget':2},NOW,NOW+1000,baseline))
        self.assertFalse(_state_matches(motor_properties(at=NOW+1000,MotorLevel=2,MotorPWM=40),{'MotorTarget':2},NOW,NOW+1000,baseline))

    def test_control_posts_once_and_waits_for_actual_motor(self):
        for level,pwm in enumerate((0,40,50,60)):
            baseline=motor_properties()
            returned=motor_properties(at=NOW+1000,MotorLevel=level,MotorPWM=pwm)
            c,s,clock=client([ok(baseline),ok({'status':1}),ok({'code':200}),ok(returned)])
            result=c.control({'MotorTarget':level})
            self.assertTrue(result['confirmed'])
            posts=[v for v in s.calls if v['method']=='POST']
            self.assertEqual(len(posts),1)
            self.assertEqual(posts[0]['json']['params'],{'MotorTarget':level})

    def test_no_motor_state_never_posts(self):
        c,s,_=client([ok(properties()),ok({'status':1})])
        with self.assertRaises(OneNetError):c.control({'MotorTarget':1})
        self.assertFalse(any(v['method']=='POST' for v in s.calls))

    def test_target_echo_or_local_stop_cannot_confirm_or_resend(self):
        c,s,_=client([ok(motor_properties()),ok({'status':1}),ok({'code':200}),
                      ok(motor_properties(at=NOW+1000,MotorTarget=3,MotorLevel=0,MotorPWM=0))])
        with self.assertRaises(OneNetError):c.control({'MotorTarget':3})
        self.assertEqual(len([v for v in s.calls if v['method']=='POST']),1)

    def test_uncertain_device_reply_never_retries_post(self):
        c,s,_=client([ok(motor_properties()),ok({'status':1}),TimeoutError('test-only')])
        with self.assertRaises(OneNetError):c.control({'MotorTarget':1})
        self.assertEqual(len([v for v in s.calls if v['method']=='POST']),1)


if __name__=='__main__':unittest.main()
