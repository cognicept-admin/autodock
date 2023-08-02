import rospy
from enum import Enum
from std_srvs.srv import Trigger, TriggerResponse
from sensor_msgs.msg import BatteryState
from actionlib import GoalStatusArray, GoalStatus, GoalID


class UndockState(Enum):
    IDLE=0
    DISCHARGE = 1
    MOVE_OUT_DOCK = 2
    SUCCESS = 3
    FAILED = 4
    CANCELLED= 5

class UndockStateMachine:
    def __init__(self, sleep_period):
        self.exe = UndockExecutor()
        self.state = UndockState.IDLE
        self.sleep_period = sleep_period

    def start(self):
        while not rospy.is_shutdown():
            if self.exe.is_undock_srv_triggered:
                if self.do_discharge and self.do_moving:
                    # publish cmd_vel to 0 to stop
                    self.state = UndockState.SUCCESS
                    self.is_undock_srv_triggered = False
                elif self.state == UndockState.CANCELLED:
                    #TODO - Stop everything 
                    self.is_undock_srv_triggered = False
                else:
                    # publish cmd_vel to 0 to stop
                    self.state = UndockState.FAILED
                    self.is_undock_srv_triggered = False
                    # TODO - Retry
            rospy.sleep(self.sleep_period)

    def do_discharge(self):
        # This function should monitor first trigger # Trigger /xnergy_charger_rcu/trigger_stop
        # wait until the the batteryState to uint8 POWER_SUPPLY_STATUS_NOT_CHARGING = 3
        # Or fail when Battery state is not in NOT_CHARGING state for more than 20 seconds.
        rospy.loginfo("Do Stop Charging")
        if self.exe.trigger_discharge:
            wait_for_sec = 20
            while (not self.exe.is_battery_stop_charge) and wait_for_sec>0:
                rospy.sleep(1)
                wait_for_sec = wait_for_sec-1
            if self.exe.is_battery_stop_charge:
                rospy.loginfo("Successfully stop charging")
                return True
            else:
                rospy.logwarn("Charging is not stopped within 20 secs")
                return False
        else:
            return False
    
    def do_moving(self):
        # move to moving forward for 50cm through kopilot
        # TODO - call kopilot
        rospy.loginfo("Do Moving")
        self.state = UndockState.MOVE_OUT_DOCK
        return True
    
    def do_retry(self):
        # TODO - retry discharge and moving again
        print("Retry")

class UndockExecutor:
    def __init__(self):
        self.is_undock_srv_triggered = False
        self.is_battery_stop_charge = False
        # Setup ros part
        self.xnergy_state_sub = rospy.Subscriber("/xnergy_charger_rcu/battery_state",BatteryState,self.check_discharge)
        self.undock_service = rospy.Service('~trigger', Trigger, self.handle_undock_request)  # Replace with the actual service type and service name
        self.undock_status_pub = rospy.Publisher('~status', GoalStatusArray, queue_size=10)
        self.undock_cancel_sub = rospy.Subscriber('~cancel', GoalID, self.handle_undock_cancel)

    def handle_undock_request(self, request):
        rospy.loginfo("Enable undocking")
        self.is_undock_srv_triggered = True
        return TriggerResponse(success=True)

    def publish_undockState(self):
        print("publish undockState for missys")

    def handle_undock_cancel(self,msg):
        print("To cancel the undock task")
    
    def check_discharge(self,msg:BatteryState):
        if msg.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_NOT_CHARGING:
            self.is_battery_stop_charge = True
        else:
            self.is_battery_stop_charge = False

    def trigger_discharge(self):
        try:
            undock_trigger = rospy.ServiceProxy("/xnergy_charger_rcu/trigger_stop",Trigger)
            res = undock_trigger()
            rospy.loginfo(f"Trigger stop charging srv, "
                                f"success: [{res.success}] | msg: {res.message}")
            if not res.success:
                rospy.logerr("Stop charging failed")
                return False
        except rospy.ServiceException as e:
            rospy.logerr(f"Stop charging call failed: {e}")
            return False

if __name__ == "__main__":
    rospy.init_node("undock_server_node",disable_signals=True)
    loop_rate =  rospy.Rate(1)
    undock_sm = UndockStateMachine(loop_rate)
    undock_sm.start()
