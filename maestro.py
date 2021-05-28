import serial
import time
import json
from sys import version_info
import os
import logging
import copy

PY2 = version_info[0] == 2  # Running Python 2.x?

logger = logging.getLogger('maestro')
logger.setLevel(logging.INFO)
# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(filename)10s:%(lineno)3d - %(levelname)10s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

# create file handler which logs even debug messages
# fh = logging.FileHandler('maestro.log')
# fh.setLevel(logging.DEBUG)
# fh.setFormatter(formatter)
# logger.addHandler(fh)


#
# ---------------------------
# Maestro Servo Controller
# ---------------------------
#
# Support for the Pololu Maestro line of servo controllers
#
# Steven Jacobs -- Aug 2013
# https://github.com/FRC4564/Maestro/
#
# These functions provide access to many of the Maestro's capabilities using the
# Pololu serial protocol
#

str_to_byte = {
}

DEFAULT_CONFIG = {
    'min': [500, 500, 500, 500, 500, 500],
    'max': [2500, 2500, 2500, 2500, 2500, 2500],
    'home': [110,110,130,110,45, 90],
    'cal' : [[2500, 900, 180], [2500, 900, 180], [2500, 900, 180], [2500, 900, 180], [2500, 900, 180], [3500,1600, 180]],
    'speed': [1000, 1000, 1000, 1000, 1000, 1000],
    'accel': [1000, 1000, 1000, 1000, 1000, 1000],
    'target_position' : [0,0,0,0,0,0],
    'last_position' : [-1,-1,-1,-1,-1,-1],
    'last_speed': [-1,-1,-1,-1,-1,-1],
    'timeout': 1,
    'delay_adjust' : 1,
    'num_of_channels' : 6
}

def load_config_file(filename="maestro.json"):
    """
    Loads config file in json format and returns config dictionary
    """
    if os.path.isfile(filename):
        try:
            fid = open(filename,'r')
            out = fid.read()
            fid.close()
            config = json.loads(out)
            return config
        except:            
            logger.error("cannot decode maestro config.json file - using DEFAULT_CONFIG")
            
    else:
        logger.error("cannot find maestro config.json file in the directory - using DEFAULT_CONFIG")
    return DEFAULT_CONFIG

def ang_2_pwm(ang, cal):
    """
    Converts rotation angle to PWM pulse duration based on calibration value for a given servo.  The calibration consists of 
    [pmw_at_0_deg, pwm_at_max_travel, max_travel_in_deg]
    """
            
    if not len(cal) == 3:
        raise NameError("in ang_2_pwm(ang, cal), cal must be a 3 element list")

    if ang >= 0 and ang <= 360:
        pwm_at_0_deg      = cal[0]
        pwm_at_max_travel = cal[1]
        max_travel_in_deg = cal[2]
        pwm = ang * (pwm_at_max_travel - pwm_at_0_deg) / max_travel_in_deg + pwm_at_0_deg
    else:
        # Ignore the coverson and we assume that the value is in units of PWM.
        # TODO could check if the value is between min/max PWM allowd, though it would require passing in the entire config structure
        pwm = ang

    return round(pwm)

class Controller:
    """
    When connected via USB, the Maestro creates two virtual serial ports
    /dev/ttyACM0 for commands and /dev/ttyACM1 for communications.
    Be sure the Maestro is configured for "USB Dual Port" serial mode.
    "USB Chained Mode" may work as well, but hasn't been tested.
    
    Pololu protocol allows for multiple Maestros to be connected to a single
    serial port. Each connected device is then indexed by number.
    This device number defaults to 0x0C (or 12 in decimal), which this module
    assumes.  If two or more controllers are connected to different serial
    ports, or you are using a Windows OS, you can provide the tty port.  For
    example, '/dev/ttyACM2' or for Windows, something like 'COM3'.
    """
    def __init__(self, tty_str='/dev/ttyACM0', device=0x0c,config_file="maestro.json"):

        self.tty_str = tty_str
        self.tty_port_exists = False
        self.tty_port_connection_established = False
        # Command lead-in and device number are sent for each Pololu serial command.
        self.timeout = 1
        self.last_cmd_send = ''
        self.config_file = config_file
        self.pololu_cmd = chr(0xaa) + chr(device)
        self.last_exception = ''
        self.last_set_target_vector = []
        self.last_speed = []

        # Track target position for each servo. The function is_moving() will
        # use the Target vs Current servo position to determine if movement is
        # occuring.  Upto 24 servos on a Maestro, (0-23). target_positions start at 0.
        # self.target_positions = [0] * 24
        # Servo minimum and maximum targets can be restricted to protect components.
        # self.Mins = [0] * 24
        # self.Maxs = [0] * 24
        
        logger.info("Controller(tty_str={}, device={})".format(self.tty_str, device))

        self.establish_connection()
        
        if not self.tty_port_connection_established:
            logger.error("Did not establish connection during object initialization")
        else:
            logger.info("Connection established")

    def __del__(self):
        self.save_config_file(fileanme=self.config_file)

    def establish_connection(self):
        logger.debug("Attempting to establish connection with: {}".format(self.tty_str))
        try:
            logger.info("Load config fule: {}".format(self.config_file))
            self.config = load_config_file(self.config_file)

            if os.path.exists(self.tty_str):
                logger.debug("Found {} on the path".format(self.tty_str))
                self.usb = serial.Serial(self.tty_str, 115200, timeout=1)
                self.tty_port_exists = True
                self.last_set_target_vector = self.get_all_positions()
                
                # Set speed of all channels from the config file
                for s in enumerate(self.config['speed']):
                    self.set_speed(s[0], s[1])

                self.tty_port_connection_established = True
            else:
                logger.error('Specified serial port does not exist')
        except Exception as e:
            self.last_exception = e
            logger.error("Cannot connect to the controller. last_exception = {}".format(e))
    
    def reload_default_config(self, filename=""):
        if len(filename) == 0:
            filename = self.config_file
        self.config = load_config_file(filename)
    
    def save_config_file(self, fileanme="last_maestro_config.json"):
        """
        Save current configuration to file for future usage.
        """
        logger.info('Saving current config as: {}'.format(fileanme))
        try: 
            fid = open(fileanme,'w')
            fid.write(json.dumps(self.config))
        except Exception as e:
            logger.error(e)

    def close(self):
        """ Cleanup by closing USB serial port"""
        if self.tty_port_connection_established:
            self.usb.close()
    
    def send(self, cmd):
        """ Send a Pololu command out the serial port """ 
        self.last_cmd_send = cmd        
        if self.tty_port_connection_established:
            cmd_str = self.pololu_cmd + cmd
            if PY2:
                out = self.usb.write(cmd_str)
            else:
                out = self.usb.write(bytes(cmd_str, 'latin-1'))
            # logger.debug("send({})".format(out))
        else:
            logger.warning("Cannot send command connection is not established")
            out = -1
        return out

    def read(self):
        """ Read a Pololu response """ 
        response = -1
        if self.establish_connection:
            if self.usb.is_open:
                start_time = time.time()
                while time.time() - start_time < self.timeout:
                    if self.usb.in_waiting == 1:
                        response = ord(self.usb.read())
                        logger.debug("read() = {}".format(response))
            else:
                logger.warning("Cannot use read command when the port is closed")
        else:
            logger.warning("Cannot use read command when connection is not established")
        return response
   
    def set_range(self, chan, min, max):
        """ Set channels min and max value range.  Use this as a safety to protect
        from accidentally moving outside known safe parameters. A setting of 0
        allows unrestricted movement.
        
        ***Note that the Maestro itself is configured to limit the range of servo travel
        which has precedence over these values.  Use the Maestro Control Center to configure
        ranges that are saved to the controller.  Use set_range for software controllable ranges.
        """
       
        if chan >=0 and chan < self.config['num_of_channels']:
            self.config['min'][chan] = min
            self.config['max'][chan] = max          
        else:
            logger.error("Specified channel is out of range")
    
    def get_min(self, chan):
        """ Return Minimum channel range value"""        
        return self.config['min'][chan]

    def get_max(self, chan):
        """ Return Maximum channel range value """       
        return self.config['max'][chan]

    def set_target(self, chan: object, target: object) -> object:
        """
        Set channel to a specified target value.  Servo will begin moving based
        on Speed and Acceleration parameters previously set.
        Target values will be constrained within Min and Max range, if set.
        For servos, target represents the pulse width in of quarter-microseconds
        Servo center is at 1500 microseconds, or 6000 quarter-microseconds
        Typcially valid servo range is 3000 to 9000 quarter-microseconds
        If channel is configured for digital output, values < 6000 = Low ouput
        """
        
        # self.target_positions[chan] = target


        # if Min is defined and Target is below, force to Min
        if self.config['min'][chan] > 0 and target < self.config['min'][chan]:
            target = self.config['min'][chan]

        # if Max is defined and Target is above, force to Max
        if self.config['max'][chan] > 0 and target > self.config['max'][chan]:
            target = self.config['max'][chan]

        self.config['target_position'][chan] = target
        target = round(target * 4)
        lsb = target & 0x7f  # 7 bits for least significant byte
        msb = (target >> 7) & 0x7f  # shift 7 and take next 7 bits for msb
        cmd = chr(0x04) + chr(chan) + chr(lsb) + chr(msb)
        self.send(cmd)
        # Record Target value

    def set_target_vector(self, target_vector, match_speed=1, wait=True):
        
        initial_speed = copy.copy(self.config["speed"])
        self.config['last_speed'] = initial_speed
        for chan, pos in enumerate(target_vector):
            if pos >=0 or pos <= 360:
                pos = ang_2_pwm(pos, self.config["cal"][chan])
                target_vector[chan] = pos # update the target vector with pwm values if vector given in degrees
            self.set_target(chan, pos)        
        pause_sec = self.get_slowest_movement_time(target_vector)
        if match_speed:            
            new_speeds = self.match_movement_speed(target_vector)
            self.set_speed_vector(new_speeds)

        if wait:
            logger.debug("set_target_vector pause time: {}".format(pause_sec))
            time.sleep(pause_sec)
            if match_speed:
                self.set_speed_vector(initial_speed)

        self.config['last_position'] = target_vector


    def go_home(self):
        self.set_target_vector(self.config['home'])

    def run_sequency(self, sequencye, match_speed=1):
        for new_target_vector in sequencye:
            if len(new_target_vector) == 1:
                logger.debug("run_sequence pause for {} sec".format(new_target_vector[0]))
                time.sleep(new_target_vector[0])
            else:
                self.set_target_vector(new_target_vector, match_speed)
   
    def set_speed(self, chan, speed):
        """
        This command limits the speed at which a servo channel’s output value changes. 
        The speed limit is given in units of (0.25 μs)/(10 ms), except in special cases (see Section 4.b). 
        For example, the command 0x87, 0x05, 0x0C, 0x01 sets the speed of servo channel 5 to a value of 140, 
        which corresponds to a speed of 3.5 μs/ms. What this means is that if you send a Set Target 
        command to adjust the target from, say, 1000 μs to 1350 μs, it will take 100 ms to make that adjustment. 
        A speed of 0 makes the speed unlimited. Setting the target of a channel that has a speed of 0 
        and an acceleration 0 will immediately affect the channel’s position. Note that the actual 
        speed at which your servo moves is also limited by the design of the servo itself, 
        the supply voltage, and mechanical loads; this parameter will not help your servo go faster 
        than what it is physically capable of.
        At the minimum speed setting of 1, the servo output takes 40 seconds to move from 1 to 2 ms. 
        The speed setting has no effect on channels configured as inputs or digital outputs.
        """
        lsb = speed & 0x7f  # 7 bits for least significant byte
        msb = (speed >> 7) & 0x7f  # shift 7 and take next 7 bits for msb
        cmd = chr(0x07) + chr(chan) + chr(lsb) + chr(msb)
        self.send(cmd)
        self.config['speed'][chan] = speed

    def set_speed_vector(self, speed_vector):
        for chan, speed in enumerate(speed_vector):
            self.set_speed(chan, speed)

    def set_accel(self, chan, accel):
        """
        Set acceleration of channel
        This provide soft starts and finishes when servo moves to target position.
        Valid values are from 0 to 255. 0=unrestricted, 1 is slowest start.
        A value of 1 will take the servo about 3s to move between 1ms to 2ms range.
        """
        if accel <=0:
            accel = 0
        if accel >= 255:
            accel = 255

        lsb = accel & 0x7f  # 7 bits for least significant byte
        msb = (accel >> 7) & 0x7f  # shift 7 and take next 7 bits for msb
        cmd = chr(0x09) + chr(chan) + chr(lsb) + chr(msb)
        self.config['accel'][chan] = accel
        self.send(cmd)

    def get_position(self, chan):
        """
        Get the current position of the device on the specified channel
        The result is returned in a measure of quarter-microseconds, which mirrors
        the Target parameter of set_target.
        This is not reading the true servo position, but the last target position sent
        to the servo. If the Speed is set to below the top speed of the servo, then
        the position result will align well with the acutal servo position, assuming
        it is not stalled or slowed.
        """
        response = -1
        if self.tty_port_connection_established:
            cmd = chr(0x10) + chr(chan)
            self.send(cmd)
            self.timeout = 1
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                if self.usb.in_waiting == 2:
                    lsb = ord(self.usb.read())
                    msb = ord(self.usb.read())
                    return ((msb << 8) + lsb) / 4
            if time.time() - start_time > self.timeout:
                logger.error('Timeout during reading position')
        
        return response

    def get_all_positions(self):
        return [self.get_position(x) for x in range(0, self.config['num_of_channels'])]
    
    def is_moving(self, chan):
        """
        Test to see if a servo has reached the set target position.  This only provides
        useful results if the Speed parameter is set slower than the maximum speed of
        the servo.  Servo range must be defined first using set_range. See set_range comment.
        
        ***Note if target position goes outside of Maestro's allowable range for the
        channel, then the target can never be reached, so it will appear to always be
        moving to the target.
        """
        if self.config['target_positions'][chan] > 0:
            if abs(self.get_position(chan) - self.config['target_positions']) > 10:
                return 1
        return 0
    
    def get_moving_state(self):
        """
        Have all servo outputs reached their targets? This is useful only if Speed and/or
        Acceleration have been set on one or more of the channels. Returns True or False.
        Not available with Micro Maestro.
        """
        return sum([self.is_moving(x) for x in range(0, 5)])
        # Does not work on maestro6
        # cmd = chr(0x13)
        # self.send(cmd)
        # if self.read() == chr(0):
        #     return False
        # else:
        #     return True
    
    def run_script_sub(self, subNumber):
        """
        Run a Maestro Script subroutine in the currently active script. Scripts can
        have multiple subroutines, which get numbered sequentially from 0 on up. Code your
        Maestro subroutine to either infinitely loop, or just end (return is not valid).
        """
        cmd = chr(0x27) + chr(subNumber)
        # can pass a param with command 0x28
        # cmd = chr(0x28) + chr(subNumber) + chr(lsb) + chr(msb)
        self.send(cmd)
    
    def stop_script(self):
        """
        Stop the current Maestro Script
        """
        cmd = chr(0x24)
        self.send(cmd)

    def get_max_pwm(self, new_vector):
        '''
        Determine maximum displace angle between current and the new position.    
        '''
        max_pwm = max(self.get_pwm_delta(new_vector))
        old_vector = self.config['last_position']
        logger.debug("old: {}, new: {}, max angle: {}".format(old_vector, new_vector, max_pwm))
        return max_pwm

    def get_pwm_delta(self, new_vector):
        '''
        Determine displace pwm between current and the new position.
        '''
        old_vector = self.config['last_position']
        if len(new_vector) != len(old_vector):
            raise NameError("Input and output vectors must be the same length.")
        else:
            # ensure that the new_vector is in units of pwm duration not in degrees.  If it was passed in degrees convert to pwm
            new_vector = [ang_2_pwm(x, self.config['cal'][ix]) for ix, x in enumerate(new_vector)]
            pwm = [abs(a-b) for a,b in zip(new_vector, old_vector)]
        return pwm

    def calculate_movement_time(self, pwm_ms, speed_deg_per_sec=0):
        '''
        Calculate time to move the servo pwm increment.  This calculation is based only on the servo parameters and not maestro settings.
        '''

        # TODO - read max/min pwm values and servo speed from a cal file.  The values will vary for different servos
        angle_0deg = 500
        angle_180deg = 2500    
        angular_speed_sec_per_degree = 0.2 / 60.0 # servo speed is typically quoted in sec per 60 deg and vary with voltage and load

        deg_per_ms = 180 / (angle_180deg - angle_0deg)
        travel_angle = (pwm_ms * deg_per_ms) 
        return travel_angle * angular_speed_sec_per_degree

    def match_movement_speed(self, new_vector):
        """
        Sets the speed of all axis, such that all axis arrive at the new target vector at the same time.
        """
        pwm_delta = self.get_pwm_delta(new_vector)
        dt_sec = self.get_slowest_movement_time(new_vector)
        dt_ms = dt_sec * 1000
        if dt_ms > 0:
            new_speeds = [round( (d/dt_ms) * 4 * 10) for d in pwm_delta]
        else:
            new_speeds = self.config["speed"]
        return new_speeds

    def get_slowest_movement_time(self, new_vector):
        
        old_vector = self.config['last_position']
        speed = self.config['speed']

        speed_us_per_ms = [ 0.25 * v / 10.0 for v in speed]
        delta_pwm_us = [abs(a-b) for a,b in zip(new_vector, old_vector)]

        # check to make sure we will not be dividing by zero
        for (chan, dt) in enumerate(delta_pwm_us):
            if dt < 1e-4:
                delta_pwm_us[chan] = 1e-3

        max_pwm_per_sec = [0]
        for s, pwm in zip(speed_us_per_ms, delta_pwm_us):
            if s > 0:
                max_pwm_per_sec.append(pwm/s)

        slowest_movement_at_speed =  self.config['delay_adjust'] * max(max_pwm_per_sec) / 1000.0

        slowest_movement_at_speed_0 = self.calculate_movement_time(self.get_max_pwm(new_vector))
        logger.debug("slowest_movement_at_speed={}, slowest_movement_at_speed_0={}".format(slowest_movement_at_speed, slowest_movement_at_speed_0))
        return max([slowest_movement_at_speed, slowest_movement_at_speed_0])

    def chop(self, chan, minmax, num, pause):
        logger.debug("chop({}, {}, {}, {})".format(chan, minmax, num, pause))
        while num:
            num = num - 1
            self.set_target(chan, minmax[0])
            time.sleep(pause)
            self.set_target(chan, minmax[1])
            time.sleep(pause)
        

    